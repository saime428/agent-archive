# 原生 function calling 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 deepseek / openai-compat provider 走原生工具调用(含流式分片拼装),JSON-in-text 协议保留为 fallback;`native_tools` 配置显式开关。

**Architecture:** 新模块 `core/tool_schemas.py` 从 `ARGS_MODELS` 导出 OpenAI tools schema;`openai_compat.py` 增 `chat_tools`(非流式)与 `stream_chat_tools`(流式生成器,return 值为信封);客户端把原生响应规整为现有信封 dict,`parse_model_action` 仍是唯一校验路径;`loop.py` 按 `use_native` 切换系统提示、模型调用与 repair 措辞。

**Tech Stack:** Python 3.11+, pydantic v2 `model_json_schema()`, stdlib。无新依赖。

**Spec:** `docs/superpowers/specs/2026-07-10-native-function-calling-design.md`

## Global Constraints

- 现有 `chat` / `stream_chat` / JSON 协议 / repair 通道行为逐字不变;`tests/test_deepseek.py` 与既有 `tests/test_openai_compat.py` 用例不改仍绿。
- 新配置键名固定 `native_tools`,默认 `False`。
- 原生请求固定 `"tool_choice": "required"`;多个 tool_calls 取 index 0 / 首个;参数 JSON 非法 → 客户端返回原始字符串;无 tool_call → 返回缺 `action` 的 `{"message": ...}` dict。
- `_envelope_from_tool_message` 是流式与非流式共用的唯一规整函数,不得复制两份逻辑。
- 错误恢复/连续错误预算/迭代提醒/观察回喂零改动。
- 验证协议:沙箱 `python3 -m py_compile` + 静态审查;pytest 在用户机器统一门禁。
- git 一律 `-c core.autocrlf=input`;只 stage 任务列出的文件;提交前必须验证暂存 blob(`git show :<path>` 提取后编译 + 行数比对),不符即 BLOCK 交控制器用 plumbing 提交——本仓库挂载陈旧已多次损坏提交,此条为硬性纪律。

---

### Task 1: 工具 Schema 导出模块

**Files:**
- Create: `src/agent/core/tool_schemas.py`
- Create: `tests/core/test_tool_schemas.py`

**Interfaces:**
- Produces: `ACTION_DESCRIPTIONS: dict[str, str]`;`native_tool_names(*, web_search_enabled: bool) -> list[str]`;`build_tool_schemas(action_names: Iterable[str]) -> list[dict]`。Task 5/6 消费。
- 注意:不 import `loop.py`(避免循环依赖);支持的工具集从 `ARGS_MODELS` 键推导。

- [ ] **Step 1: 写失败测试**

创建 `tests/core/test_tool_schemas.py`,完整内容:

```python
from __future__ import annotations

from agent.core.actions import ARGS_MODELS
from agent.core.tool_schemas import ACTION_DESCRIPTIONS, build_tool_schemas, native_tool_names


def test_every_action_has_a_description() -> None:
    assert set(ACTION_DESCRIPTIONS) == set(ARGS_MODELS)
    assert all(desc.strip() for desc in ACTION_DESCRIPTIONS.values())


def test_native_tool_names_always_include_terminals() -> None:
    names = native_tool_names(web_search_enabled=True)

    assert names[0] == "done"
    assert names[1] == "ask_user"
    assert "read_file" in names
    assert "web_search" in names


def test_native_tool_names_hide_web_search_when_disabled() -> None:
    names = native_tool_names(web_search_enabled=False)

    assert "web_search" not in names
    assert "read_file" in names


def test_build_tool_schemas_shape() -> None:
    schemas = build_tool_schemas(["done", "read_file"])

    assert [schema["function"]["name"] for schema in schemas] == ["done", "read_file"]
    for schema in schemas:
        assert schema["type"] == "function"
        assert schema["function"]["description"].strip()
        parameters = schema["function"]["parameters"]
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False
    read_file_params = schemas[1]["function"]["parameters"]
    assert "path" in read_file_params["properties"]
```

- [ ] **Step 2: 验证失败**

Run: `python3 -c "import ast, pathlib; ast.parse(pathlib.Path('tests/core/test_tool_schemas.py').read_text())" && ls src/agent/core/tool_schemas.py`
Expected: ast.parse 通过,ls 报 No such file

- [ ] **Step 3: 实现**

创建 `src/agent/core/tool_schemas.py`,完整内容:

```python
from __future__ import annotations

from collections.abc import Iterable

from agent.core.actions import ARGS_MODELS

ACTION_DESCRIPTIONS: dict[str, str] = {
    "done": "Finish the task and return the final user-facing answer.",
    "ask_user": "Ask the user a clarifying question when you cannot proceed.",
    "list_dir": "List entries in a directory.",
    "read_file": "Read a text file, optionally from a start line with a line limit.",
    "search_files": "Search file contents in the workspace for a query string.",
    "web_search": "Search the web for current information.",
    "write_file": "Create or overwrite a text file with the given content.",
    "apply_patch": "Apply one or more exact string-replacement edits to files.",
    "run_command": "Run an allowed command without a shell.",
    "git_status": "Show git status for the workspace.",
    "git_diff": "Show a git diff, optionally for one path or the staged index.",
    "read_pdf": "Extract text from a PDF file.",
    "read_docx": "Extract text from a Word document.",
    "read_xlsx": "Extract text from an Excel workbook.",
    "read_pptx": "Extract text from a PowerPoint file.",
    "write_markdown_report": "Write a Markdown report file with title, body, and sources.",
}

_TERMINAL_ACTIONS = ("done", "ask_user")


def native_tool_names(*, web_search_enabled: bool) -> list[str]:
    names = list(_TERMINAL_ACTIONS)
    for name in sorted(set(ARGS_MODELS) - set(_TERMINAL_ACTIONS)):
        if name == "web_search" and not web_search_enabled:
            continue
        names.append(name)
    return names


def build_tool_schemas(action_names: Iterable[str]) -> list[dict]:
    schemas: list[dict] = []
    for name in action_names:
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": ACTION_DESCRIPTIONS.get(name, ""),
                    "parameters": ARGS_MODELS[name].model_json_schema(),
                },
            }
        )
    return schemas
```

- [ ] **Step 4: 验证**

Run: `python3 -m py_compile src/agent/core/tool_schemas.py tests/core/test_tool_schemas.py`
Expected: 通过。注意:沙箱 Python 3.10 无法 import 本模块(间接依赖 StrEnum),py_compile 足矣。

- [ ] **Step 5: 暂存 blob 验证后提交**

```bash
git add src/agent/core/tool_schemas.py tests/core/test_tool_schemas.py
git show :src/agent/core/tool_schemas.py > /tmp/s1.py && git show :tests/core/test_tool_schemas.py > /tmp/s2.py && python3 -m py_compile /tmp/s1.py /tmp/s2.py && tail -1 /tmp/s1.py
# 暂存内容截断/不符 → BLOCK;否则:
git -c core.autocrlf=input commit -m "feat: export native tool schemas from action models"
```

---

### Task 2: chat_tools(非流式)与信封规整

**Files:**
- Modify: `src/agent/llm/openai_compat.py`
- Test: `tests/test_openai_compat.py`(末尾追加)

**Interfaces:**
- Produces: `OpenAICompatClient.chat_tools(messages, tools, *, temperature=None) -> dict | str`;模块级 `_envelope_from_tool_message(message_obj: dict) -> dict | str`(Task 3 复用)。

- [ ] **Step 1: 写失败测试**

`tests/test_openai_compat.py` 末尾追加(文件已有 `RecordingTransport` 与 `json`/`pytest` 导入):

```python
def _tools_response(message_obj: dict) -> bytes:
    return json.dumps({"choices": [{"message": message_obj}]}).encode("utf-8")


def _done_tool_call(arguments: str) -> dict:
    return {
        "content": "Finishing.",
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "done", "arguments": arguments}}
        ],
    }


DONE_ARGS = '{"final": "ok", "changed_files": [], "next_steps": []}'
TOOLS = [{"type": "function", "function": {"name": "done", "description": "d", "parameters": {"type": "object"}}}]


def test_chat_tools_sends_tools_and_required_choice() -> None:
    transport = RecordingTransport(_tools_response(_done_tool_call(DONE_ARGS)))
    client = OpenAICompatClient(api_key="", model="m", base_url="http://localhost:11434/v1", transport=transport)

    envelope = client.chat_tools([{"role": "user", "content": "hi"}], TOOLS)

    body = transport.calls[0]["body"]
    assert body["tools"] == TOOLS
    assert body["tool_choice"] == "required"
    assert body["stream"] is False
    assert envelope == {
        "message": "Finishing.",
        "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
    }


def test_chat_tools_takes_first_of_multiple_tool_calls() -> None:
    message_obj = {
        "content": "",
        "tool_calls": [
            {"function": {"name": "done", "arguments": DONE_ARGS}},
            {"function": {"name": "read_file", "arguments": '{"path": "x"}'}},
        ],
    }
    transport = RecordingTransport(_tools_response(message_obj))
    client = OpenAICompatClient(api_key="", model="m", base_url="http://localhost:11434/v1", transport=transport)

    envelope = client.chat_tools([{"role": "user", "content": "hi"}], TOOLS)

    assert envelope["action"]["name"] == "done"


def test_chat_tools_returns_raw_string_for_invalid_arguments_json() -> None:
    transport = RecordingTransport(_tools_response(_done_tool_call('{"final": broken')))
    client = OpenAICompatClient(api_key="", model="m", base_url="http://localhost:11434/v1", transport=transport)

    result = client.chat_tools([{"role": "user", "content": "hi"}], TOOLS)

    assert result == '{"final": broken'


def test_chat_tools_returns_actionless_envelope_when_no_tool_call() -> None:
    transport = RecordingTransport(_tools_response({"content": "just chatting"}))
    client = OpenAICompatClient(api_key="", model="m", base_url="http://localhost:11434/v1", transport=transport)

    result = client.chat_tools([{"role": "user", "content": "hi"}], TOOLS)

    assert result == {"message": "just chatting"}
```

- [ ] **Step 2: 实现**

`openai_compat.py` 两处新增:

**(a)** `OpenAICompatClient` 内、`stream_chat` 之后新增方法:

```python
    def chat_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        temperature: float | None = None,
    ) -> dict | str:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "required",
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        try:
            response_body = _retry_transient(
                lambda: self.transport(
                    f"{self.base_url}/chat/completions",
                    self._headers(),
                    body,
                    self.timeout,
                ),
                self.retry_sleep,
            )
        except HTTPError as exc:
            raise ProviderError(f"{self.provider_label} API request failed: {exc.code} {exc.reason}") from exc
        except URLError as exc:
            raise ProviderError(f"{self.provider_label} API request failed: {exc.reason}") from exc
        return _parse_tools_chat_response(response_body, self.provider_label)
```

**(b)** 模块级、`_parse_chat_response` 之后新增:

```python
def _parse_tools_chat_response(response_body: bytes, provider_label: str) -> dict | str:
    try:
        response = json.loads(response_body.decode("utf-8"))
        message_obj = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError(f"{provider_label} API returned an invalid chat completion response.") from exc
    if not isinstance(message_obj, dict):
        raise ProviderError(f"{provider_label} API returned an invalid chat completion response.")
    return _envelope_from_tool_message(message_obj)


def _envelope_from_tool_message(message_obj: dict) -> dict | str:
    content = message_obj.get("content")
    message_text = content if isinstance(content, str) else ""
    tool_calls = message_obj.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return {"message": message_text}
    first = tool_calls[0]
    function = first.get("function") if isinstance(first, dict) else None
    if not isinstance(function, dict):
        return {"message": message_text}
    name = function.get("name")
    arguments = function.get("arguments")
    if not isinstance(name, str) or not isinstance(arguments, str):
        return {"message": message_text}
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError:
        return arguments
    if not isinstance(args, dict):
        return arguments
    return {"message": message_text, "action": {"name": name, "args": args}}
```

- [ ] **Step 3: 验证 + 暂存 blob 验证后提交**

Run: `python3 -m py_compile src/agent/llm/openai_compat.py tests/test_openai_compat.py`

```bash
git add src/agent/llm/openai_compat.py tests/test_openai_compat.py
# 暂存 blob 提取+编译+tail 比对(同 Task 1 Step 5 模式);通过后:
git -c core.autocrlf=input commit -m "feat: add non-streaming native tool calling to openai-compat client"
```

---

### Task 3: stream_chat_tools(流式拼装)

**Files:**
- Modify: `src/agent/llm/openai_compat.py`
- Test: `tests/test_openai_compat.py`(末尾追加)

**Interfaces:**
- Consumes: Task 2 的 `_envelope_from_tool_message`。
- Produces: `OpenAICompatClient.stream_chat_tools(messages, tools, *, temperature=None)` — 生成器,yield 文本分片(content 与 arguments),**return 值**为信封 dict | str(经 `StopIteration.value` 获取)。

- [ ] **Step 1: 写失败测试**

`tests/test_openai_compat.py` 末尾追加:

```python
def _sse(events: list[str]) -> list[bytes]:
    return [f"data: {event}\n".encode("utf-8") for event in events] + [b"data: [DONE]\n"]


def _drive(generator):
    chunks: list[str] = []
    while True:
        try:
            chunks.append(next(generator))
        except StopIteration as stop:
            return chunks, stop.value


def test_stream_chat_tools_assembles_fragmented_tool_call() -> None:
    events = [
        '{"choices": [{"delta": {"content": "Think"}}]}',
        '{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "done", "arguments": ""}}]}}]}',
        '{"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\\"final\\": \\"o"}}]}}]}',
        '{"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "k\\", \\"changed_files\\": [], \\"next_steps\\": []}"}}]}}]}',
    ]
    client = OpenAICompatClient(
        api_key="",
        model="m",
        base_url="http://localhost:11434/v1",
        stream_transport=lambda url, headers, body, timeout: iter(_sse(events)),
    )

    chunks, envelope = _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))

    assert "Think" in "".join(chunks)
    assert '"final"' in "".join(chunks)
    assert envelope == {
        "message": "Think",
        "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
    }


def test_stream_chat_tools_requests_streaming_with_required_choice() -> None:
    captured: dict = {}

    def stream_transport(url, headers, body, timeout):
        captured["body"] = json.loads(body.decode("utf-8"))
        return iter(_sse(['{"choices": [{"delta": {"content": "x"}}]}']))

    client = OpenAICompatClient(
        api_key="", model="m", base_url="http://localhost:11434/v1", stream_transport=stream_transport
    )

    _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))

    assert captured["body"]["stream"] is True
    assert captured["body"]["tool_choice"] == "required"
    assert captured["body"]["tools"] == TOOLS


def test_stream_chat_tools_without_tool_call_returns_actionless_envelope() -> None:
    events = ['{"choices": [{"delta": {"content": "no tools here"}}]}']
    client = OpenAICompatClient(
        api_key="",
        model="m",
        base_url="http://localhost:11434/v1",
        stream_transport=lambda url, headers, body, timeout: iter(_sse(events)),
    )

    _chunks, envelope = _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))

    assert envelope == {"message": "no tools here"}


def test_stream_chat_tools_ignores_non_zero_indexes() -> None:
    events = [
        '{"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "done", "arguments": ""}}]}}]}',
        '{"choices": [{"delta": {"tool_calls": [{"index": 1, "function": {"name": "read_file", "arguments": "{}"}}]}}]}',
        '{"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "' + DONE_ARGS.replace('"', '\\"') + '"}}]}}]}',
    ]
    client = OpenAICompatClient(
        api_key="",
        model="m",
        base_url="http://localhost:11434/v1",
        stream_transport=lambda url, headers, body, timeout: iter(_sse(events)),
    )

    _chunks, envelope = _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))

    assert envelope["action"]["name"] == "done"


def test_stream_chat_tools_reports_invalid_sse() -> None:
    client = OpenAICompatClient(
        api_key="",
        model="m",
        base_url="http://localhost:11434/v1",
        stream_transport=lambda url, headers, body, timeout: iter([b"not sse\n"]),
    )

    with pytest.raises(ProviderError):
        _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))
```

- [ ] **Step 2: 实现**

`openai_compat.py` 三处新增:

**(a)** `OpenAICompatClient` 内、`chat_tools` 之后:

```python
    def stream_chat_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        temperature: float | None = None,
    ) -> Generator[str, None, dict | str]:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "required",
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        for delay in [1.0, 2.0, 4.0, None]:
            assembler = _ToolCallAssembler()
            try:
                stream = self.stream_transport(
                    f"{self.base_url}/chat/completions",
                    self._headers(),
                    body,
                    self.timeout,
                )
                yield from self._assemble_tool_stream(stream, assembler)
                return assembler.envelope()
            except HTTPError as exc:
                if delay is None or not _is_retryable_http(exc):
                    raise ProviderError(f"{self.provider_label} API request failed: {exc.code} {exc.reason}") from exc
                self.retry_sleep(delay)
            except URLError as exc:
                if delay is None:
                    raise ProviderError(f"{self.provider_label} API request failed: {exc.reason}") from exc
                self.retry_sleep(delay)
        raise RuntimeError("unreachable")

    def _assemble_tool_stream(self, chunks: Iterable[bytes], assembler: "_ToolCallAssembler") -> Iterator[str]:
        buffer = ""
        for chunk in chunks:
            try:
                buffer += chunk.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProviderError(f"{self.provider_label} API returned an invalid streaming response.") from exc
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                piece = self._tool_stream_piece(line, assembler)
                if piece is _StreamDone:
                    return
                if piece:
                    yield piece
        if buffer.strip():
            piece = self._tool_stream_piece(buffer, assembler)
            if piece is not _StreamDone and piece:
                yield piece

    def _tool_stream_piece(self, line: str, assembler: "_ToolCallAssembler") -> str | type[_StreamDone] | None:
        stripped = line.strip()
        if not stripped or stripped.startswith(":"):
            return None
        if not stripped.startswith("data:"):
            raise ProviderError(f"{self.provider_label} API returned an invalid streaming response.")
        payload = stripped[len("data:") :].strip()
        if payload == "[DONE]":
            return _StreamDone
        try:
            event = json.loads(payload)
            delta = event["choices"][0].get("delta") or {}
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError(f"{self.provider_label} API returned an invalid streaming response.") from exc
        if not isinstance(delta, dict):
            raise ProviderError(f"{self.provider_label} API returned an invalid streaming response.")
        return assembler.feed(delta)
```

**(b)** 模块级、`_envelope_from_tool_message` 之后:

```python
class _ToolCallAssembler:
    def __init__(self) -> None:
        self.content_parts: list[str] = []
        self.tool_name: str | None = None
        self.argument_parts: list[str] = []

    def feed(self, delta: dict) -> str | None:
        pieces: list[str] = []
        content = delta.get("content")
        if isinstance(content, str) and content:
            self.content_parts.append(content)
            pieces.append(content)
        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list):
            for fragment in tool_calls:
                if not isinstance(fragment, dict) or fragment.get("index", 0) != 0:
                    continue
                function = fragment.get("function")
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                if isinstance(name, str) and name and self.tool_name is None:
                    self.tool_name = name
                arguments = function.get("arguments")
                if isinstance(arguments, str) and arguments:
                    self.argument_parts.append(arguments)
                    pieces.append(arguments)
        return "".join(pieces) or None

    def envelope(self) -> dict | str:
        message_obj: dict[str, object] = {"content": "".join(self.content_parts)}
        if self.tool_name is not None:
            message_obj["tool_calls"] = [
                {"function": {"name": self.tool_name, "arguments": "".join(self.argument_parts)}}
            ]
        return _envelope_from_tool_message(message_obj)
```

**(c)** 顶部导入:`from collections.abc import Iterable, Iterator` 已有;补 `Generator`:改为 `from collections.abc import Generator, Iterable, Iterator`(以文件实际导入为准,缺什么补什么)。

- [ ] **Step 3: 验证 + 暂存 blob 验证后提交**

Run: `python3 -m py_compile src/agent/llm/openai_compat.py tests/test_openai_compat.py`

```bash
git add src/agent/llm/openai_compat.py tests/test_openai_compat.py
# 暂存 blob 验证(同前);通过后:
git -c core.autocrlf=input commit -m "feat: add streaming native tool calling with fragment assembly"
```

---

### Task 4: 配置键 native_tools

**Files:**
- Modify: `src/agent/config.py`
- Test: `tests/test_config.py`(末尾追加)

**Interfaces:**
- Produces: `AgentConfig.native_tools: bool = False`。Task 5/6 消费。

- [ ] **Step 1: 写失败测试**

`tests/test_config.py` 末尾追加:

```python
def test_native_tools_defaults_to_false() -> None:
    assert AgentConfig().native_tools is False


def test_native_tools_loads_from_project_config(tmp_path) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("native_tools = true\n", encoding="utf-8")

    config, diagnostics = load_config(tmp_path, home=tmp_path / "home")

    assert config.native_tools is True
    assert diagnostics.warnings == []


def test_native_tools_rejects_non_boolean(tmp_path) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('native_tools = "yes"\n', encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(tmp_path, home=tmp_path / "home")
```

- [ ] **Step 2: 实现**

`config.py` 五处(与 `max_consecutive_errors` 完全同模式):`KNOWN_KEYS` 加 `"native_tools"`;`AgentConfig` 加 `native_tools: bool = False`;`ConfigOverrides` 加 `native_tools: bool | None = None`;`_apply_overrides` values 字典加一行;`_validate_value` 布尔集合 `{"dry_run", "memory_auto_write", "web_search_enabled", "computer_read_enabled"}` 加 `"native_tools"`。

- [ ] **Step 3: 验证 + 暂存 blob 验证后提交**

```bash
python3 -m py_compile src/agent/config.py tests/test_config.py
git add src/agent/config.py tests/test_config.py
# 暂存 blob 验证;通过后:
git -c core.autocrlf=input commit -m "feat: add native_tools config key"
```

---

### Task 5: 循环集成

**Files:**
- Modify: `src/agent/core/loop.py`
- Create: `tests/core/test_loop_native.py`

**Interfaces:**
- Consumes: Task 1 `build_tool_schemas`/`native_tool_names`;Task 4 `config.native_tools`;客户端鸭子类型 `chat_tools`/`stream_chat_tools`。
- Produces: `use_native` 判定 `config.native_tools and callable(getattr(llm, "chat_tools", None))`;`_action_protocol_message(config, *, native=False)`;`_build_repair_message(..., native=False)`;`_model_response(..., native_tools_payload=None)`。

- [ ] **Step 1: 写失败测试**

创建 `tests/core/test_loop_native.py`,完整内容:

```python
from __future__ import annotations

from agent.config import AgentConfig
from agent.core.loop import run_once
from agent.llm.fake import FakeLLMClient


def _done_envelope(final: str = "native done") -> dict:
    return {
        "message": "Finishing.",
        "action": {"name": "done", "args": {"final": final, "changed_files": [], "next_steps": []}},
    }


def _read_missing_envelope() -> dict:
    return {"message": "Reading.", "action": {"name": "read_file", "args": {"path": "missing.txt"}}}


class ScriptedNativeLLM:
    """chat_tools 按脚本返回;记录每次调用的 messages 与 tools。"""

    def __init__(self, responses: list[dict | str]) -> None:
        self.responses = responses
        self.calls: list[dict] = []
        self._index = 0

    def chat(self, messages: list[dict], *, temperature: float | None = None) -> dict:
        raise AssertionError("JSON-protocol chat must not be used when native tools are active.")

    def chat_tools(self, messages: list[dict], tools: list[dict], *, temperature: float | None = None):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if self._index >= len(self.responses):
            raise AssertionError("ScriptedNativeLLM ran out of responses.")
        response = self.responses[self._index]
        self._index += 1
        return response


def test_native_run_uses_chat_tools_and_completes(tmp_path) -> None:
    llm = ScriptedNativeLLM([_done_envelope()])
    config = AgentConfig(native_tools=True)

    result = run_once("say done", llm, cwd=tmp_path, run_id="run_native", config=config)

    assert result.action.action.name == "done"
    assert result.observation.data == {"final": "native done"}
    tools = llm.calls[0]["tools"]
    tool_names = [tool["function"]["name"] for tool in tools]
    assert tool_names[0] == "done"
    assert "read_file" in tool_names
    system = llm.calls[0]["messages"][0]["content"]
    assert "Call exactly one tool" in system
    assert "JSON action object" not in system


def test_native_hides_web_search_tool_when_disabled(tmp_path) -> None:
    llm = ScriptedNativeLLM([_done_envelope()])
    config = AgentConfig(native_tools=True, web_search_enabled=False)

    run_once("say done", llm, cwd=tmp_path, run_id="run_native_ws", config=config)

    tool_names = [tool["function"]["name"] for tool in llm.calls[0]["tools"]]
    assert "web_search" not in tool_names


def test_native_actionless_response_routes_to_repair(tmp_path) -> None:
    llm = ScriptedNativeLLM([{"message": "just chatting"}, _done_envelope("recovered")])
    config = AgentConfig(native_tools=True)

    result = run_once("say done", llm, cwd=tmp_path, run_id="run_native_repair", config=config)

    assert result.action.action.name == "done"
    assert result.observation.data == {"final": "recovered"}
    repair = llm.calls[1]["messages"][-1]["content"]
    assert "Call exactly one tool" in repair


def test_native_error_recovery_still_works(tmp_path) -> None:
    llm = ScriptedNativeLLM([_read_missing_envelope(), _done_envelope("recovered from error")])
    config = AgentConfig(native_tools=True)

    result = run_once("read missing file", llm, cwd=tmp_path, run_id="run_native_recover", config=config)

    assert result.observations[0].status == "error"
    assert result.action.action.name == "done"
    feedback = next(
        message["content"]
        for message in llm.calls[1]["messages"]
        if "UNTRUSTED TOOL OBSERVATION" in message["content"]
    )
    assert "Error code: TOOL_FAILED" in feedback


def test_native_flag_falls_back_to_json_protocol_without_chat_tools(tmp_path) -> None:
    config = AgentConfig(native_tools=True)

    result = run_once("inspect project", FakeLLMClient(), cwd=tmp_path, run_id="run_native_fallback", config=config)

    assert result.action.action.name == "done"
    assert result.observation.status == "ok"
```

- [ ] **Step 2: 实现**

`loop.py` 六处:

**(a)** 导入区加 `from agent.core.tool_schemas import build_tool_schemas, native_tool_names`。

**(b)** `run_once` 内、`effective_config` 计算之后加:

```python
    use_native = effective_config.native_tools and callable(getattr(llm, "chat_tools", None))
    native_tools_payload = (
        build_tool_schemas(native_tool_names(web_search_enabled=effective_config.web_search_enabled))
        if use_native
        else None
    )
```

**(c)** `_build_messages(...)` 调用与定义各加 `native=use_native` 参数,透传给 `_action_protocol_message(config, native=native)`。

**(d)** `_action_protocol_message` 改签名为 `(config: AgentConfig, *, native: bool = False)`,函数体开头加 native 分支(现有 JSON 分支逐字保留):

```python
    if native:
        web_search_rule = (
            "For current web, news, latest-version, or internet lookup requests, use web_search before done. "
            if config.web_search_enabled
            else "Do not use web_search because web search is disabled in Settings. "
        )
        computer_read_rule = (
            "list_dir, read_file, and search_files may read explicit absolute computer paths or ~ paths. "
            if config.computer_read_enabled
            else "list_dir, read_file, and search_files are limited to the workspace unless computer file reading is enabled in Settings. "
        )
        return {
            "role": "system",
            "content": (
                "Call exactly one tool per turn and do not reply with plain text. "
                "Use list_dir, read_file, or search_files for file inspection; do not use run_command just to list or read files. "
                f"{web_search_rule}"
                f"{computer_read_rule}"
                "Finish with the done tool when the task is complete. "
                "When calling done, args.final is the user-facing answer: answer directly in the user's language, "
                "do not summarize your own behavior. Use the ask_user tool to ask a clarifying question. "
                + _mode_instruction(config.mode)
            ),
        }
```

**(e)** `_model_response` 改签名加 `native_tools_payload: list[dict] | None = None`,函数体开头加:

```python
    if native_tools_payload is not None:
        stream_chat_tools = getattr(llm, "stream_chat_tools", None)
        if stream_handler is None or stream_chat_tools is None:
            return llm.chat_tools(messages, native_tools_payload)
        _emit_event(event_handler, "model_stream_start", {})
        generator = stream_chat_tools(messages, native_tools_payload)
        while True:
            try:
                chunk = next(generator)
            except StopIteration as stop:
                return stop.value if stop.value is not None else ""
            text = str(chunk)
            stream_handler(text)
            _emit_event(event_handler, "model_stream_chunk", {"chunk_chars": len(text)})
```

`run_once` 内的调用点改为 `_model_response(llm, messages, event_handler=event_handler, stream_handler=stream_handler, native_tools_payload=native_tools_payload)`。

**(f)** `_build_repair_message` 改签名加 `native: bool = False`;正文中这两行:

```python
            "Return exactly one valid JSON action object with top-level keys "
            '"message" and "action". Do not include markdown fences or extra text.\n'
```

native 时替换为:

```python
            "Call exactly one tool. Do not reply with plain text.\n"
```

(用条件表达式实现,其余错误码/示例段共用;示例段 `Valid action args examples` 两种模式均保留——参数结构相同。)调用点传 `native=use_native`。`_trace_config` 返回字典加 `"native_tools": config.native_tools,`。

- [ ] **Step 3: 验证 + 暂存 blob 验证后提交**

```bash
python3 -m py_compile src/agent/core/loop.py tests/core/test_loop_native.py
git add src/agent/core/loop.py tests/core/test_loop_native.py
# 暂存 blob 验证;通过后:
git -c core.autocrlf=input commit -m "feat: route run loop through native tool calling when enabled"
```

---

### Task 6: CLI 与 Web

**Files:**
- Modify: `src/agent/cli.py`、`src/agent/llm/openai_compat.py`(smoke)、`src/agent/web/server.py`
- Test: `tests/test_cli.py`、`tests/test_web.py`(各末尾追加)

**Interfaces:**
- Produces: `smoke_provider_native(...)`(openai_compat 模块级);CLI `provider smoke <name> --native`;doctor/config show 的 `native_tools` 行;server 两处 payload 的 `native_tools` 键。

- [ ] **Step 1: openai_compat.py 增 smoke_provider_native**

`smoke_provider` 之后新增(注意从 core 导入 schema 构建,无循环依赖):

```python
def smoke_provider_native(
    *,
    provider_name: str,
    api_key: str,
    model: str,
    base_url: str,
    api_key_env: str,
    provider_label: str = "Provider",
    timeout: float = 60.0,
    transport: Transport | None = None,
) -> SmokeResult:
    from agent.core.tool_schemas import build_tool_schemas

    client = OpenAICompatClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        provider_label=provider_label,
        timeout=timeout,
        transport=transport,
    )
    raw_action = client.chat_tools(
        [
            {
                "role": "system",
                "content": "You are testing an agent provider connection. Call the done tool exactly once.",
            },
            {
                "role": "user",
                "content": 'Call the done tool with args {"final":"smoke ok","changed_files":[],"next_steps":[]}.',
            },
        ],
        build_tool_schemas(["done"]),
        temperature=0,
    )
    try:
        action = parse_model_action(
            raw_action,
            run_id="provider_smoke",
            action_index=1,
            created_at=datetime.now(timezone.utc),
        )
    except ActionParseError as exc:
        raise ProviderError(f"{provider_label} native smoke returned invalid action: {exc.message}") from exc
    if action.action.name != "done":
        raise ProviderError(f"{provider_label} native smoke expected done action, got {action.action.name}.")
    return SmokeResult(
        provider=provider_name,
        model=model,
        api_key_env=api_key_env,
        status="ok",
        action_name=action.action.name,
        final=str(action.action.args["final"]),
    )
```

测试追加到 `tests/test_openai_compat.py`:

```python
def test_smoke_provider_native_validates_done_tool_call() -> None:
    transport = RecordingTransport(_tools_response(_done_tool_call('{"final": "smoke ok", "changed_files": [], "next_steps": []}')))

    result = smoke_provider_native(
        provider_name="openai-compat",
        api_key="",
        model="llama3",
        base_url="http://localhost:11434/v1",
        api_key_env="OPENAI_API_KEY",
        provider_label="openai-compat",
        transport=transport,
    )

    assert result.status == "ok"
    assert result.final == "smoke ok"
    body = transport.calls[0]["body"]
    assert body["tool_choice"] == "required"
    assert [tool["function"]["name"] for tool in body["tools"]] == ["done"]
```

(文件头部导入补 `smoke_provider_native`。)

- [ ] **Step 2: CLI**

`cli.py`:导入行的 openai_compat 导入加 `smoke_provider_native`;`provider_smoke` 加参数 `native: bool = typer.Option(False, "--native", help="Smoke-test native tool calling.")`;两个分支中,`native` 为真时改调 `smoke_provider_native`(deepseek 分支传 `base_url=DEFAULT_DEEPSEEK_BASE_URL, provider_label="DeepSeek"`——需在 cli.py 的 deepseek 导入行补 `DEFAULT_DEEPSEEK_BASE_URL`;openai-compat 分支参数同现有 smoke 调用),异常类型两分支已分别捕获 `DeepSeekError`/`ProviderError`(同一类型,不变)。doctor 与 config show 各加一行 `console.print(f"native_tools: {config.native_tools}")`(位置:紧随 `config mode`/`mode` 行之后)。

测试追加到 `tests/test_cli.py`(monkeypatch 目标 `agent.cli.smoke_provider_native`,构造仿照本文件现有 openai-compat smoke 测试):

```python
def test_provider_smoke_native_flag_calls_native_smoke(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        'provider = "openai-compat"\nbase_url = "http://localhost:11434/v1"\nmodel = "llama3"\n',
        encoding="utf-8",
    )
    captured: dict = {}

    def fake_native_smoke(**kwargs):
        captured.update(kwargs)
        from types import SimpleNamespace

        return SimpleNamespace(
            provider="openai-compat", model=kwargs["model"], api_key_env=kwargs["api_key_env"],
            status="ok", action_name="done", final="smoke ok",
        )

    monkeypatch.setattr("agent.cli.smoke_provider_native", fake_native_smoke)
    runner = CliRunner()

    result = runner.invoke(app, ["provider", "smoke", "openai-compat", "--native", "--cwd", str(tmp_path)])

    assert result.exit_code == 0
    assert captured["provider_name"] == "openai-compat"
    assert "status: ok" in result.output
```

(runner/app/导入按 test_cli.py 现有约定对齐。)

- [ ] **Step 3: Web**

`server.py` 两处只读 payload(`build_health_payload` 与 `_build_settings_readiness`)各加 `"native_tools": bool(config["native_tools"]),`(紧随 `"api_key_env"` 键之后)。测试追加到 `tests/test_web.py`:在现有 health/config payload 测试的断言后加 `assert payload["native_tools"] is False` 式断言,或新增最小用例(按文件现有构造复制)。

- [ ] **Step 4: 验证 + 暂存 blob 验证后提交**

```bash
python3 -m py_compile src/agent/cli.py src/agent/llm/openai_compat.py src/agent/web/server.py tests/test_cli.py tests/test_openai_compat.py tests/test_web.py
git add src/agent/cli.py src/agent/llm/openai_compat.py src/agent/web/server.py tests/test_cli.py tests/test_openai_compat.py tests/test_web.py
# 暂存 blob 验证(六个文件全部提取+编译+tail 比对);通过后:
git -c core.autocrlf=input commit -m "feat: add native smoke flag and native_tools surfacing"
```

---

### Task 7: 文档与用户门禁

**Files:**
- Modify: `CHANGELOG.md`、`README.md`

- [ ] **Step 1: CHANGELOG**

`## Unreleased` 节追加:

```markdown
- 原生 function calling:`native_tools = true` 时 deepseek/openai-compat 走原生工具调用(含流式分片拼装),所有动作皆工具、每轮恰好一个;JSON 协议保留为 fallback,fake provider 自动回落。
```

- [ ] **Step 2: README**

"OpenAI-compatible providers (local models)" 小节的 toml 示例中追加一行注释配置:

```toml
# native_tools = true                    # use native tool calling (requires endpoint tool support)
```

并在该节末尾加一句:

```markdown
With `native_tools = true` the agent uses native function calling (one tool call per turn, `tool_choice: "required"`); endpoints without tool support should keep it `false`.
```

- [ ] **Step 3: 暂存 blob 验证后提交**

```bash
git add CHANGELOG.md README.md
# 暂存 blob 验证(提取+关键词 grep+tail 比对);通过后:
git -c core.autocrlf=input commit -m "docs: document native_tools"
```

- [ ] **Step 4: 用户门禁(用户机器执行)**

```
python -m pytest -q > pytest-output.txt 2>&1
python -m agent.cli doctor >> pytest-output.txt 2>&1
python -m agent.cli provider smoke deepseek --native >> pytest-output.txt 2>&1
```

随后在 `.agent/config.toml` 加 `native_tools = true`,再跑真实任务冒烟(验证 native 路径 + 错误恢复协同):

```
python -m agent.cli run "读取 does-not-exist.txt 的内容" --cwd . >> pytest-output.txt 2>&1
```

Expected: pytest 全绿;doctor 输出含 `native_tools: false`;`--native` 冒烟对真实 DeepSeek 端点返回 `status: ok / final: smoke ok`;开 `native_tools` 后的真实 run 中,模型经原生工具调用收到 TOOL_FAILED 反馈并自行收尾(completed: true)。冒烟通过后建议把 `native_tools = true` 留在配置里日常使用,遇问题随时关回。
