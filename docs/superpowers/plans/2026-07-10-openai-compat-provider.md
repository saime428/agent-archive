# OpenAI 兼容 provider 泛化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DeepSeek 客户端泛化为可配 `base_url` 的 OpenAI 兼容客户端,DeepSeek 变成薄预设层,零破坏现有配置与测试。

**Architecture:** 新模块 `llm/openai_compat.py` 承载通用客户端(`OpenAICompatClient`/`ProviderError`/`smoke_provider`);`deepseek.py` 变预设层(子类 + 别名 + 薄包装);config/factory/CLI/web 各加一个 `openai-compat` 入口。

**Tech Stack:** Python 3.11+, stdlib http.client, pytest。无新依赖。

**Spec:** `docs/superpowers/specs/2026-07-10-openai-compat-provider-design.md`

## Global Constraints

- `tests/test_deepseek.py` 一字不改,最终必须全绿——这是兼容性验收标准。
- 新配置键名固定:`base_url`(默认 `""`)、`api_key_env`(默认 `"OPENAI_API_KEY"`);provider 新合法值固定为 `"openai-compat"`。
- api key 为空时请求不携带 `Authorization` 头;`base_url` 必需性只在 factory/CLI 使用时校验,不在配置加载时校验。
- 错误消息前缀用 `provider_label`;DeepSeek 预设的所有现有错误消息文本保持逐字不变。
- 不碰:core/loop.py、shell.py、repair 通道、`_mode_max_iterations`、`core/summary.py`。
- 验证协议:沙箱 `python3 -m py_compile` + 静态审查;pytest 在用户机器统一门禁。
- git 一律 `-c core.autocrlf=input`;只 stage 任务列出的文件。

---

### Task 1: 通用客户端模块 openai_compat.py

**Files:**
- Create: `src/agent/llm/openai_compat.py`
- Create: `tests/test_openai_compat.py`

**Interfaces:**
- Produces: `ProviderError(RuntimeError)`;`OpenAICompatClient(*, api_key, model, base_url, provider_label="Provider", timeout=60.0, transport=None, stream_transport=None, retry_sleep=None)`;`SmokeResult`(字段同 DeepSeekSmokeResult);`smoke_provider(*, provider_name, api_key, model, base_url, api_key_env, provider_label="Provider", timeout=60.0, transport=None)`。Task 2/4/5 消费。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_openai_compat.py`,完整内容:

```python
from __future__ import annotations

import json

import pytest

from agent.llm.openai_compat import OpenAICompatClient, ProviderError, smoke_provider


class RecordingTransport:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.calls: list[dict] = []

    def __call__(self, url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        self.calls.append({"url": url, "headers": dict(headers), "body": json.loads(body.decode("utf-8"))})
        return self.response


def _chat_response(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


def _done_content() -> str:
    return json.dumps(
        {
            "message": "Done.",
            "action": {"name": "done", "args": {"final": "ok", "changed_files": [], "next_steps": []}},
        }
    )


def test_empty_api_key_sends_no_authorization_header() -> None:
    transport = RecordingTransport(_chat_response(_done_content()))
    client = OpenAICompatClient(api_key="", model="llama3", base_url="http://localhost:11434/v1", transport=transport)

    client.chat([{"role": "user", "content": "hi"}])

    assert "Authorization" not in transport.calls[0]["headers"]
    assert transport.calls[0]["url"] == "http://localhost:11434/v1/chat/completions"


def test_non_empty_api_key_sends_bearer_header() -> None:
    transport = RecordingTransport(_chat_response(_done_content()))
    client = OpenAICompatClient(api_key="sk-x", model="m", base_url="https://api.example.com", transport=transport)

    client.chat([{"role": "user", "content": "hi"}])

    assert transport.calls[0]["headers"]["Authorization"] == "Bearer sk-x"


def test_missing_base_url_rejected() -> None:
    with pytest.raises(ProviderError):
        OpenAICompatClient(api_key="", model="m", base_url=" ")


def test_missing_model_rejected() -> None:
    with pytest.raises(ProviderError):
        OpenAICompatClient(api_key="", model=" ", base_url="http://localhost:11434/v1")


def test_error_message_uses_provider_label() -> None:
    def failing_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        from urllib.error import URLError

        raise URLError("connection refused")

    client = OpenAICompatClient(
        api_key="",
        model="m",
        base_url="http://localhost:11434/v1",
        provider_label="openai-compat",
        transport=failing_transport,
        retry_sleep=lambda _delay: None,
    )

    with pytest.raises(ProviderError) as excinfo:
        client.chat([{"role": "user", "content": "hi"}])

    assert "openai-compat API request failed" in str(excinfo.value)


def test_smoke_provider_returns_result_with_provider_name() -> None:
    transport = RecordingTransport(_chat_response(_done_content()))

    result = smoke_provider(
        provider_name="openai-compat",
        api_key="",
        model="llama3",
        base_url="http://localhost:11434/v1",
        api_key_env="OPENAI_API_KEY",
        provider_label="openai-compat",
        transport=transport,
    )

    assert result.provider == "openai-compat"
    assert result.status == "ok"
    assert result.action_name == "done"
```

- [ ] **Step 2: 验证失败(沙箱替代:确认模块不存在)**

Run: `python3 -c "import ast, pathlib; ast.parse(pathlib.Path('tests/test_openai_compat.py').read_text())" && ls src/agent/llm/openai_compat.py`
Expected: ast.parse 通过,ls 报 No such file

- [ ] **Step 3: 迁移实现**

复制 `src/agent/llm/deepseek.py` 为 `src/agent/llm/openai_compat.py`,然后施加以下精确变换:

1. 删除 `DEFAULT_DEEPSEEK_BASE_URL` / `DEFAULT_DEEPSEEK_MODEL` 两常量。
2. 全文件重命名:`DeepSeekError` → `ProviderError`;`DeepSeekClient` → `OpenAICompatClient`;`DeepSeekSmokeResult` → `SmokeResult`;`smoke_deepseek_provider` → `smoke_provider`。
3. `OpenAICompatClient.__init__` 替换为:

```python
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        provider_label: str = "Provider",
        timeout: float = 60.0,
        transport: Transport | None = None,
        stream_transport: StreamTransport | None = None,
        retry_sleep: RetrySleep | None = None,
    ) -> None:
        if not model.strip():
            raise ProviderError(f"{provider_label} model is required.")
        if not base_url.strip():
            raise ProviderError(f"{provider_label} base_url is required.")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.provider_label = provider_label
        self.timeout = timeout
        reusable_transport = _ReusableHTTPTransport()
        self.transport = transport or reusable_transport.request_bytes
        self.stream_transport = stream_transport or reusable_transport.stream_bytes
        self.retry_sleep = retry_sleep or time.sleep
```

(注意:不再校验 api_key 非空——预设层负责。)

4. `chat` 与 `stream_chat` 中的 headers 构造统一替换为调用新增私有方法:

```python
    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Connection": "keep-alive",
        }
        if self.api_key.strip():
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
```

两处 `headers = {...}` 字面量改为 `headers = self._headers()`。

5. 错误消息前缀:`chat`/`stream_chat` 中全部 `f"DeepSeek API request failed: ..."`(chat 两处 + stream_chat 两处,共四处)改为 `f"{self.provider_label} API request failed: ..."`。模块级解析函数(`_parse_chat_response`、`_parse_streaming_chat_response`、`_parse_sse_line`)接收新增参数 `provider_label: str`,其内部 `"DeepSeek API returned..."` 消息全部改为 `f"{provider_label} API returned..."`;调用点相应传 `self.provider_label`。`_parse_chat_response` 中 `"DeepSeek model content must be..."` 改为 `f"{provider_label} model content must be..."`。
6. `smoke_provider` 签名与首段替换为:

```python
def smoke_provider(
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
    client = OpenAICompatClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        provider_label=provider_label,
        timeout=timeout,
        transport=transport,
    )
```

函数尾部 `provider="deepseek"` 改为 `provider=provider_name`;两处 `f"DeepSeek smoke ..."` 错误消息改为 `f"{provider_label} smoke ..."`。
7. 其余代码(传输层、重试、SSE、`_normalize_smoke_action`、`_looks_like_action_envelope`、`_is_retryable_http`、`_StreamDone`)原样保留。

- [ ] **Step 4: 验证**

Run: `python3 -m py_compile src/agent/llm/openai_compat.py tests/test_openai_compat.py && grep -n "DeepSeek\|deepseek" src/agent/llm/openai_compat.py`
Expected: py_compile 通过;grep 无输出(模块内不残留 DeepSeek 字样)

- [ ] **Step 5: Commit**

```bash
git add src/agent/llm/openai_compat.py tests/test_openai_compat.py
git commit -m "feat: add generic openai-compatible provider client"
```

---

### Task 2: deepseek.py 瘦身为预设层

**Files:**
- Modify: `src/agent/llm/deepseek.py`(整文件重写)
- Test: 无新测试——验收即 `tests/test_deepseek.py` 不改仍绿(用户门禁)

**Interfaces:**
- Consumes: Task 1 全部导出。
- Produces(保持不变的现有接口): `DEFAULT_DEEPSEEK_BASE_URL`、`DEFAULT_DEEPSEEK_MODEL`、`DeepSeekError`、`DeepSeekClient`、`DeepSeekSmokeResult`、`smoke_deepseek_provider`、以及 `Transport`/`StreamTransport`/`RetrySleep` 类型别名(cli/server/tests 从本模块导入)。

- [ ] **Step 1: 重写 deepseek.py**

整文件替换为:

```python
from __future__ import annotations

from agent.llm.openai_compat import (
    OpenAICompatClient,
    ProviderError,
    RetrySleep,
    SmokeResult,
    StreamTransport,
    Transport,
    smoke_provider,
)

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"

DeepSeekError = ProviderError
DeepSeekSmokeResult = SmokeResult


class DeepSeekClient(OpenAICompatClient):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_DEEPSEEK_MODEL,
        base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
        timeout: float = 60.0,
        transport: Transport | None = None,
        stream_transport: StreamTransport | None = None,
        retry_sleep: RetrySleep | None = None,
    ) -> None:
        if not api_key.strip():
            raise DeepSeekError("DeepSeek API key is required.")
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            provider_label="DeepSeek",
            timeout=timeout,
            transport=transport,
            stream_transport=stream_transport,
            retry_sleep=retry_sleep,
        )


def smoke_deepseek_provider(
    *,
    api_key: str,
    model: str = DEFAULT_DEEPSEEK_MODEL,
    api_key_env: str = "DEEPSEEK_API_KEY",
    base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
    timeout: float = 60.0,
    transport: Transport | None = None,
) -> DeepSeekSmokeResult:
    if not api_key.strip():
        raise DeepSeekError("DeepSeek API key is required.")
    return smoke_provider(
        provider_name="deepseek",
        api_key=api_key,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        provider_label="DeepSeek",
        timeout=timeout,
        transport=transport,
    )
```

注意:原 `DeepSeekClient.__init__` 还校验 model 非空并报 `"DeepSeek model is required."`——泛化后该消息变为 `"DeepSeek model is required."`(provider_label="DeepSeek" 时文本一致),逐字对照 `tests/test_deepseek.py` 的消息断言确认无漂移。原 `smoke_deepseek_provider` 不做空 key 前置校验时由 `DeepSeekClient` 构造抛错——现在 smoke 走 `OpenAICompatClient`(允许空 key),因此薄包装里显式补上空 key 校验,保持 `test_deepseek_smoke_rejects_missing_api_key_without_network` 语义。

- [ ] **Step 2: 验证**

Run: `python3 -m py_compile src/agent/llm/deepseek.py && python3 -c "import ast,pathlib; tree=ast.parse(pathlib.Path('src/agent/llm/deepseek.py').read_text()); print(sorted(n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.ClassDef))))"`
Expected: py_compile 通过;输出含 DeepSeekClient、smoke_deepseek_provider

对照检查:`grep -n "from agent.llm.deepseek import" src tests -r` 列出的每个导入符号(`DeepSeekClient`、`DeepSeekError`、`smoke_deepseek_provider`、类型别名等)都仍可从新 deepseek.py 导入。

- [ ] **Step 3: Commit**

```bash
git add src/agent/llm/deepseek.py
git commit -m "refactor: turn deepseek module into openai-compat preset"
```

---

### Task 3: 配置新键与 provider 值

**Files:**
- Modify: `src/agent/config.py`
- Test: `tests/test_config.py`(末尾追加)

**Interfaces:**
- Produces: `AgentConfig.base_url: str = ""`、`AgentConfig.api_key_env: str = "OPENAI_API_KEY"`、provider 合法值 `"openai-compat"`。Task 4/5/6 消费。

- [ ] **Step 1: 写失败测试**

`tests/test_config.py` 末尾追加:

```python
def test_base_url_and_api_key_env_defaults() -> None:
    config = AgentConfig()

    assert config.base_url == ""
    assert config.api_key_env == "OPENAI_API_KEY"


def test_openai_compat_provider_is_valid(tmp_path) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        'provider = "openai-compat"\nbase_url = "http://localhost:11434/v1"\n',
        encoding="utf-8",
    )

    config, diagnostics = load_config(tmp_path, home=tmp_path / "home")

    assert config.provider == "openai-compat"
    assert config.base_url == "http://localhost:11434/v1"
    assert diagnostics.warnings == []


def test_base_url_rejects_non_string(tmp_path) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("base_url = 3\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(tmp_path, home=tmp_path / "home")


def test_api_key_env_rejects_empty_string(tmp_path) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('api_key_env = " "\n', encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(tmp_path, home=tmp_path / "home")
```

- [ ] **Step 2: 实现**

`config.py` 六处:

1. `Provider = Literal["fake", "deepseek", "openai-compat"]`;
2. `VALID_VALUES["provider"]` 集合加 `"openai-compat"`;
3. `KNOWN_KEYS` 加 `"base_url"`、`"api_key_env"`;
4. `AgentConfig` 加 `base_url: str = ""` 与 `api_key_env: str = "OPENAI_API_KEY"`;`ConfigOverrides` 加对应 `| None = None` 字段;
5. `_apply_overrides` 的 values 字典加两行;
6. `_validate_value`:`"api_key_env"` 并入现有 `{"model", "deepseek_api_key_env"}` 非空字符串分支;`base_url` 单独分支——`isinstance(value, str)` 即可(允许空串),否则 `expected string`。

- [ ] **Step 3: 验证**

Run: `python3 -m py_compile src/agent/config.py tests/test_config.py`
Expected: 通过

- [ ] **Step 4: Commit**

```bash
git add src/agent/config.py tests/test_config.py
git commit -m "feat: add base_url and api_key_env config keys with openai-compat provider"
```

---

### Task 4: Factory 入口

**Files:**
- Modify: `src/agent/llm/factory.py`(整文件小,直接给出终态)
- Test: `tests/test_llm_factory.py`(末尾追加)

**Interfaces:**
- Consumes: Task 1 `OpenAICompatClient`/`ProviderError`;Task 3 config 键。
- Produces: `make_llm(config)` 对 provider="openai-compat" 可用。

- [ ] **Step 1: 写失败测试**

`tests/test_llm_factory.py` 末尾追加(按该文件现有导入风格补 `pytest`、`ProviderError`、`OpenAICompatClient` 导入):

```python
def test_make_llm_builds_openai_compat_client(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    config = AgentConfig(provider="openai-compat", model="llama3", base_url="http://localhost:11434/v1")

    client = make_llm(config)

    assert isinstance(client, OpenAICompatClient)
    assert client.base_url == "http://localhost:11434/v1"
    assert client.api_key == ""


def test_make_llm_openai_compat_requires_base_url() -> None:
    config = AgentConfig(provider="openai-compat", model="llama3")

    with pytest.raises(ProviderError):
        make_llm(config)
```

- [ ] **Step 2: 实现**

`factory.py` 整文件终态:

```python
from __future__ import annotations

import os
from collections.abc import Callable

from agent.config import AgentConfig
from agent.llm.base import LLMClient
from agent.llm.deepseek import DeepSeekClient
from agent.llm.fake import FakeLLMClient
from agent.llm.openai_compat import OpenAICompatClient, ProviderError


def _make_deepseek(config: AgentConfig) -> DeepSeekClient:
    api_key = os.environ.get(config.deepseek_api_key_env, "")
    return DeepSeekClient(api_key=api_key, model=config.model)


def _make_openai_compat(config: AgentConfig) -> OpenAICompatClient:
    if not config.base_url.strip():
        raise ProviderError("openai-compat provider requires base_url in .agent/config.toml.")
    api_key = os.environ.get(config.api_key_env, "")
    return OpenAICompatClient(
        api_key=api_key,
        model=config.model,
        base_url=config.base_url,
        provider_label="openai-compat",
    )


PROVIDER_REGISTRY: dict[str, Callable[[AgentConfig], LLMClient]] = {
    "fake": lambda _config: FakeLLMClient(),
    "deepseek": _make_deepseek,
    "openai-compat": _make_openai_compat,
}


def make_llm(config: AgentConfig):
    return PROVIDER_REGISTRY[config.provider](config)
```

- [ ] **Step 3: 验证**

Run: `python3 -m py_compile src/agent/llm/factory.py tests/test_llm_factory.py`
Expected: 通过

- [ ] **Step 4: Commit**

```bash
git add src/agent/llm/factory.py tests/test_llm_factory.py
git commit -m "feat: wire openai-compat provider into llm factory"
```

---

### Task 5: CLI 泛化

**Files:**
- Modify: `src/agent/cli.py`
- Test: `tests/test_cli.py`(末尾追加)

**Interfaces:**
- Consumes: Task 1 `smoke_provider`/`ProviderError`;Task 3 config 键。

- [ ] **Step 1: 写失败测试**

`tests/test_cli.py` 末尾追加(该文件已有 CliRunner/monkeypatch 模式,对照现有 smoke 测试的写法;transport 注入不可行时用 monkeypatch 替换 `agent.cli.smoke_provider`):

```python
def test_provider_smoke_openai_compat_requires_base_url(tmp_path) -> None:
    result = runner.invoke(app, ["provider", "smoke", "openai-compat", "--cwd", str(tmp_path)])

    assert result.exit_code == 1
    assert "base_url" in result.output


def test_provider_smoke_openai_compat_calls_generic_smoke(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / ".agent"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        'provider = "openai-compat"\nbase_url = "http://localhost:11434/v1"\nmodel = "llama3"\n',
        encoding="utf-8",
    )
    captured: dict = {}

    def fake_smoke(**kwargs):
        captured.update(kwargs)
        from agent.llm.openai_compat import SmokeResult

        return SmokeResult(
            provider="openai-compat",
            model=kwargs["model"],
            api_key_env=kwargs["api_key_env"],
            status="ok",
            action_name="done",
            final="smoke ok",
        )

    monkeypatch.setattr("agent.cli.smoke_provider", fake_smoke)

    result = runner.invoke(app, ["provider", "smoke", "openai-compat", "--cwd", str(tmp_path)])

    assert result.exit_code == 0
    assert captured["base_url"] == "http://localhost:11434/v1"
    assert captured["provider_name"] == "openai-compat"
    assert "status: ok" in result.output
```

(若 `tests/test_cli.py` 的 runner/app 命名不同,按现有命名对齐;断言语义不变。)

- [ ] **Step 2: 实现**

`cli.py` 三处:

1. 导入区加 `from agent.llm.openai_compat import ProviderError, smoke_provider`。
2. `provider_smoke` 命令体改为分派:

```python
    if provider_name not in {"deepseek", "openai-compat"}:
        console.print(f"Unsupported provider smoke target: {provider_name}")
        raise typer.Exit(code=1)
```

deepseek 分支保持现有逻辑逐字不变;新增 openai-compat 分支:

```python
    if provider_name == "openai-compat":
        if not config.base_url.strip():
            console.print("openai-compat smoke requires base_url in .agent/config.toml.")
            raise typer.Exit(code=1)
        api_key = os.environ.get(config.api_key_env, "")
        try:
            result = smoke_provider(
                provider_name="openai-compat",
                api_key=api_key,
                model=config.model,
                base_url=config.base_url,
                api_key_env=config.api_key_env,
                provider_label="openai-compat",
            )
        except ProviderError as exc:
            console.print(str(exc))
            raise typer.Exit(code=1) from exc
```

两分支共用现有的结果打印段(result 字段名一致)。
3. 流式判断(现 cli.py:316 附近)`config.provider == "deepseek"` 改为 `config.provider in {"deepseek", "openai-compat"}`;doctor 与 config show 的输出段,在 provider 为 openai-compat 时补印:

```python
    if config.provider == "openai-compat":
        console.print(f"base_url: {config.base_url}")
        console.print(f"api_key_env: {config.api_key_env}")
        console.print(f"api key present: {str(bool(os.environ.get(config.api_key_env))).lower()}")
```

(插在现有 deepseek 打印行之后;deepseek 行不动。)

- [ ] **Step 3: 验证**

Run: `python3 -m py_compile src/agent/cli.py tests/test_cli.py`
Expected: 通过

- [ ] **Step 4: Commit**

```bash
git add src/agent/cli.py tests/test_cli.py
git commit -m "feat: generalize provider smoke and doctor output for openai-compat"
```

---

### Task 6: Web 层白名单与展示

**Files:**
- Modify: `src/agent/web/server.py`
- Test: `tests/test_web.py`(末尾追加)

**Interfaces:**
- Consumes: Task 3 config 键。

- [ ] **Step 1: 写失败测试**

`tests/test_web.py` 末尾追加(对照该文件现有 config POST 测试的构造方式):

```python
def test_config_update_accepts_openai_compat_provider(tmp_path) -> None:
    # 按 test_web.py 现有 config 更新用例的请求构造方式,POST provider="openai-compat"
    # 断言不再返回 "provider must be fake or deepseek." 错误,更新成功。
    ...
```

实现者注意:此测试骨架需按 `tests/test_web.py` 现有工具函数落实为可执行代码——读文件里最近的 config 更新测试,复制其构造,替换 provider 值,断言成功;禁止留 `...`。

- [ ] **Step 2: 实现**

`server.py` 两处:

1. 第 557-558 行:

```python
            if value not in {"fake", "deepseek", "openai-compat"}:
                raise ValueError("provider must be fake, deepseek, or openai-compat.")
```

2. 配置展示 payload(第 252-262 与 296-299 附近):在两处 payload 字典中补 `"base_url": str(config["base_url"])` 与 `"api_key_env": str(config["api_key_env"])`;第 271-284 的提示函数对 provider == "openai-compat" 增加分支:base_url 为空提示"请在 .agent/config.toml 设置 base_url",key 缺失时提示等价文案(与 deepseek 分支同样式)。

- [ ] **Step 3: 验证**

Run: `python3 -m py_compile src/agent/web/server.py tests/test_web.py`
Expected: 通过

- [ ] **Step 4: Commit**

```bash
git add src/agent/web/server.py tests/test_web.py
git commit -m "feat: accept openai-compat provider in workbench config"
```

---

### Task 7: 收尾文档与用户门禁

**Files:**
- Modify: `CHANGELOG.md`、`README.md`

- [ ] **Step 1: CHANGELOG**

`## Unreleased` 节(第一期已建)追加一条:

```markdown
- Provider 泛化:新增 `openai-compat` provider(可配 `base_url` / `api_key_env`,api key 可空),DeepSeek 变为薄预设层,现有配置零破坏;可直接接入 Ollama/vLLM 等本地 OpenAI 兼容端点。
```

- [ ] **Step 2: README**

在 README 配置/provider 相关小节(参考 `## Quickstart` 中 provider 配置示例附近)追加最小示例:

```markdown
### OpenAI-compatible providers (local models)

```toml
# .agent/config.toml
provider = "openai-compat"
base_url = "http://localhost:11434/v1"   # e.g. Ollama
model = "llama3"
# api_key_env = "OPENAI_API_KEY"         # optional; empty key sends no Authorization header
```
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs: document openai-compat provider"
```

- [ ] **Step 4: 用户门禁(用户机器执行)**

```
python -m pytest -q > pytest-output.txt 2>&1
python -m agent.cli doctor >> pytest-output.txt 2>&1
python -m agent.cli provider smoke deepseek >> pytest-output.txt 2>&1
```

Expected: pytest 全绿(含未改动的 test_deepseek.py);doctor 正常;真实 DeepSeek 端点 smoke 通过(经预设层走新通用客户端的端到端回归)。
