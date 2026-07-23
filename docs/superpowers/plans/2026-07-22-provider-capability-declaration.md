# Provider 能力声明 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provider Adapter 显式声明 streaming/native_tools 本地方法能力，runtime 与 CLI 不再写 provider 名字分支或散点 getattr 探测；native_tools 配置不匹配时降级 + `capability_warning` 事件。reasoning 等模型级能力待有真实证据链后另做。

**Architecture:** `ProviderCapabilities`（类级声明）+ `resolve_capabilities`（实例读取，探测回退）供 runtime 用；`ProviderSpec` 注册表（capabilities + auth + smoke 闭包）供 CLI/doctor 按名字读，不实例化。`_model_response` 保持不动。

**Tech Stack:** Python 3.13 stdlib + 现有 pytest。无新依赖。

**Spec:** `docs/superpowers/specs/2026-07-22-provider-capability-declaration-design.md`

## Global Constraints

- 不新增第三方依赖；不改 config 文件格式；run/session 数据不迁移。
- 行为变化仅限：新增 `capability_warning` 事件（仅 native_tools 不匹配）、doctor / `config show` / `release doctor` 的 provider 相关输出行。
- 以下消息逐字保留：`Unsupported provider smoke target: {provider_name}`、`DeepSeek API key is required in {env}.`、`openai-compat smoke requires base_url in .agent/config.toml.`
- `_model_response`（`src/agent/core/loop.py:489`）不改动。
- 测试命令：`python -m pytest`（miniconda python 3.13）。提交前 `git diff --check`。
- 提交消息遵循仓库现有风格（`feat:`/`refactor:`/`test:`/`docs:` 前缀，无 attribution 尾注）。

## 复审修订（2026-07-23）

- 能力字段只描述 Adapter 的本地 streaming/native-tools 路径；删除未驱动行为且无法在
  Provider 级可靠声明的 `reasoning`。
- `resolve_capabilities().streaming` 只从 `stream_chat` 派生；native 流继续由
  `_model_response` 检查 `stream_chat_tools` 并回退。
- `ProviderSpec.api_key_required` 区分 DeepSeek 必需 key 与 openai-compat 可选 key。
- `config show` 在报告 key presence 前加载 workspace secrets，并新增必需/可选 key
  与 secrets 一致性测试。

---

### Task 1: ProviderCapabilities 声明与 resolve_capabilities

**Files:**
- Modify: `src/agent/llm/base.py`（现 21 行，追加）
- Modify: `src/agent/llm/fake.py`（类属性 + import）
- Modify: `src/agent/llm/openai_compat.py`（类属性 + import）
- Test: `tests/test_capabilities.py`（新建）

**Interfaces:**
- Consumes: 无（首个任务）。
- Produces: `agent.llm.base.ProviderCapabilities`（frozen dataclass，字段 `streaming: bool, native_tools: bool`）；`agent.llm.base.resolve_capabilities(llm: object) -> ProviderCapabilities`；类属性 `FakeLLMClient.capabilities`（两项 False）、`OpenAICompatClient.capabilities`（两项 True，`DeepSeekClient` 继承）。

- [x] **Step 1: 写失败测试**

新建 `tests/test_capabilities.py`：

```python
from __future__ import annotations

from agent.llm.base import ProviderCapabilities, resolve_capabilities
from agent.llm.deepseek import DeepSeekClient
from agent.llm.fake import FakeLLMClient
from agent.llm.openai_compat import OpenAICompatClient


def test_fake_declares_no_capabilities() -> None:
    assert FakeLLMClient.capabilities == ProviderCapabilities(streaming=False, native_tools=False)


def test_openai_compat_declares_adapter_paths() -> None:
    assert OpenAICompatClient.capabilities == ProviderCapabilities(streaming=True, native_tools=True)


def test_deepseek_inherits_openai_compat_capabilities() -> None:
    assert DeepSeekClient.capabilities is OpenAICompatClient.capabilities


def test_resolve_prefers_declared_capabilities() -> None:
    class Declared:
        capabilities = ProviderCapabilities(streaming=True, native_tools=False)

        def chat_tools(self, messages, tools):  # 声明撒谎也以声明为准
            return {}

    assert resolve_capabilities(Declared()) is Declared.capabilities


def test_resolve_derives_from_methods() -> None:
    class NativeOnly:
        def chat(self, messages):
            return {}

        def chat_tools(self, messages, tools):
            return {}

    caps = resolve_capabilities(NativeOnly())
    assert caps == ProviderCapabilities(streaming=False, native_tools=True)


def test_resolve_does_not_treat_native_stream_as_regular_stream() -> None:
    class NativeStreamOnly:
        def chat_tools(self, messages, tools):
            return {}

        def stream_chat_tools(self, messages, tools):
            yield "chunk"

    caps = resolve_capabilities(NativeStreamOnly())
    assert caps.streaming is False
    assert caps.native_tools is True


def test_resolve_ignores_non_capability_attribute() -> None:
    class WrongType:
        capabilities = "streaming"

        def stream_chat(self, messages):
            yield "chunk"

    caps = resolve_capabilities(WrongType())
    assert caps == ProviderCapabilities(streaming=True, native_tools=False)
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_capabilities.py -q`
Expected: FAIL，`ImportError: cannot import name 'ProviderCapabilities'`

- [x] **Step 3: 最小实现**

`src/agent/llm/base.py` 顶部 import 改为并追加（保留现有 `LLMClient` Protocol 不动）：

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderCapabilities:
    streaming: bool
    native_tools: bool


def resolve_capabilities(llm: object) -> ProviderCapabilities:
    declared = getattr(llm, "capabilities", None)
    if isinstance(declared, ProviderCapabilities):
        return declared
    return ProviderCapabilities(
        streaming=callable(getattr(llm, "stream_chat", None)),
        native_tools=callable(getattr(llm, "chat_tools", None)),
    )
```

`src/agent/llm/fake.py`：`class FakeLLMClient:` 体第一行加类属性，并加 import：

```python
from agent.llm.base import ProviderCapabilities


class FakeLLMClient:
    capabilities = ProviderCapabilities(streaming=False, native_tools=False)
```

`src/agent/llm/openai_compat.py`：`class OpenAICompatClient:` 体第一行加类属性，并在文件顶部 import 区加：

```python
from agent.llm.base import ProviderCapabilities


class OpenAICompatClient:
    capabilities = ProviderCapabilities(streaming=True, native_tools=True)
```

（`DeepSeekClient` 继承 `OpenAICompatClient`，不改 `deepseek.py`。）

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_capabilities.py -q`
Expected: 7 passed

- [x] **Step 5: 相邻回归**

Run: `python -m pytest tests/test_openai_compat.py tests/test_deepseek.py -q`
Expected: 全部 passed（类属性不影响现有行为）

- [x] **Step 6: Commit**

```bash
git add src/agent/llm/base.py src/agent/llm/fake.py src/agent/llm/openai_compat.py tests/test_capabilities.py
git commit -m "feat: declare provider capabilities with resolve fallback"
```

---

### Task 2: ProviderSpec 注册表与 smoke 闭包

**Files:**
- Modify: `src/agent/llm/factory.py`（整文件重写，见 Step 3）
- Modify: `tests/test_llm_factory.py`（扩展现有 factory 测试，不另建文件）

**Interfaces:**
- Consumes: Task 1 的 `ProviderCapabilities` 与三个类的 `capabilities` 属性。
- Produces: `agent.llm.factory.ProviderSpec`（frozen dataclass，字段 `factory: Callable[[AgentConfig], LLMClient]`、`capabilities: ProviderCapabilities`、`api_key_env: Callable[[AgentConfig], str] | None`、`api_key_required: bool`、`requires_base_url: bool`、`smoke: Callable[[AgentConfig, bool], SmokeResult] | None`）；`PROVIDER_REGISTRY: dict[str, ProviderSpec]`（键：`fake`/`deepseek`/`openai-compat`）；`make_llm(config)` 签名与返回不变。

- [x] **Step 1: 写失败测试**

修改 `tests/test_llm_factory.py`：

1. 顶部 import 区补齐（保留现有 import）：

```python
from agent.config import VALID_VALUES, AgentConfig
from agent.llm.openai_compat import OpenAICompatClient, ProviderError, SmokeResult
```

2. 现有 `test_provider_registry_contains_builtin_providers` 的断言从字面量集合升级为与 config 同步（更强，防两处漂移）：

```python
def test_provider_registry_contains_builtin_providers() -> None:
    assert set(PROVIDER_REGISTRY) == VALID_VALUES["provider"]
```

3. 现有 4 条 `make_llm` 测试保持不动（升级后必须继续通过）。文件末尾追加：

```python
def _smoke_result(provider: str) -> SmokeResult:
    return SmokeResult(
        provider=provider,
        model="m",
        api_key_env="E",
        status="ok",
        action_name="done",
        final="smoke ok",
    )


@pytest.mark.parametrize("name", sorted({"fake", "deepseek", "openai-compat"}))
def test_declared_capabilities_match_methods(name, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    config = AgentConfig(provider=name, base_url="http://localhost:9/v1")
    spec = PROVIDER_REGISTRY[name]
    client = spec.factory(config)
    caps = spec.capabilities
    assert caps is type(client).capabilities
    assert caps.native_tools == callable(getattr(client, "chat_tools", None))
    if caps.streaming:
        assert callable(getattr(client, "stream_chat", None))
        if caps.native_tools:
            assert callable(getattr(client, "stream_chat_tools", None))
    else:
        assert not callable(getattr(client, "stream_chat", None))


def test_fake_spec_has_no_auth_and_no_smoke() -> None:
    spec = PROVIDER_REGISTRY["fake"]
    assert spec.api_key_env is None
    assert spec.api_key_required is False
    assert spec.requires_base_url is False
    assert spec.smoke is None


def test_api_key_env_reads_provider_specific_config_field() -> None:
    config = AgentConfig(deepseek_api_key_env="DS_KEY", api_key_env="OA_KEY")
    assert PROVIDER_REGISTRY["deepseek"].api_key_env(config) == "DS_KEY"
    assert PROVIDER_REGISTRY["openai-compat"].api_key_env(config) == "OA_KEY"
    assert PROVIDER_REGISTRY["deepseek"].api_key_required is True
    assert PROVIDER_REGISTRY["openai-compat"].api_key_required is False
    assert PROVIDER_REGISTRY["openai-compat"].requires_base_url is True


def test_deepseek_smoke_closure_wires_config(monkeypatch) -> None:
    calls = {}

    def fake_smoke(**kwargs):
        calls.update(kwargs)
        return _smoke_result("deepseek")

    monkeypatch.setenv("DS_KEY", "secret")
    monkeypatch.setattr("agent.llm.factory.smoke_deepseek_provider", fake_smoke)
    config = AgentConfig(provider="deepseek", model="deepseek-v4-flash", deepseek_api_key_env="DS_KEY")

    result = PROVIDER_REGISTRY["deepseek"].smoke(config, False)

    assert result.status == "ok"
    assert calls == {"api_key": "secret", "model": "deepseek-v4-flash", "api_key_env": "DS_KEY"}


def test_deepseek_smoke_closure_missing_key_raises(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = AgentConfig(provider="deepseek")

    with pytest.raises(ProviderError) as excinfo:
        PROVIDER_REGISTRY["deepseek"].smoke(config, False)

    assert "DeepSeek API key is required in DEEPSEEK_API_KEY." in str(excinfo.value)


def test_deepseek_native_smoke_uses_default_base_url(monkeypatch) -> None:
    calls = {}

    def fake_native(**kwargs):
        calls.update(kwargs)
        return _smoke_result("deepseek")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    monkeypatch.setattr("agent.llm.factory.smoke_provider_native", fake_native)

    PROVIDER_REGISTRY["deepseek"].smoke(AgentConfig(provider="deepseek"), True)

    assert calls["provider_name"] == "deepseek"
    assert calls["base_url"] == "https://api.deepseek.com"
    assert calls["provider_label"] == "DeepSeek"


def test_openai_compat_smoke_closure_requires_base_url(monkeypatch) -> None:
    config = AgentConfig(provider="openai-compat")

    with pytest.raises(ProviderError) as excinfo:
        PROVIDER_REGISTRY["openai-compat"].smoke(config, False)

    assert "openai-compat smoke requires base_url in .agent/config.toml." in str(excinfo.value)


def test_openai_compat_smoke_closure_wires_config(monkeypatch) -> None:
    calls = {}

    def fake_smoke(**kwargs):
        calls.update(kwargs)
        return _smoke_result("openai-compat")

    monkeypatch.setenv("OPENAI_API_KEY", "oa-key")
    monkeypatch.setattr("agent.llm.factory.smoke_provider", fake_smoke)
    config = AgentConfig(provider="openai-compat", model="llama3", base_url="http://localhost:11434/v1")

    PROVIDER_REGISTRY["openai-compat"].smoke(config, False)

    assert calls == {
        "provider_name": "openai-compat",
        "api_key": "oa-key",
        "model": "llama3",
        "base_url": "http://localhost:11434/v1",
        "api_key_env": "OPENAI_API_KEY",
        "provider_label": "openai-compat",
    }
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_llm_factory.py -q`
Expected: 新增测试 FAIL（`AttributeError: 'function' object has no attribute 'factory'` 一类——注册表值还是裸 factory）；现有 4 条 `make_llm` 测试仍 PASS

- [x] **Step 3: 重写 factory.py**

`src/agent/llm/factory.py` 整文件替换为：

```python
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from agent.config import AgentConfig
from agent.llm.base import LLMClient, ProviderCapabilities
from agent.llm.deepseek import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DeepSeekClient,
    smoke_deepseek_provider,
)
from agent.llm.fake import FakeLLMClient
from agent.llm.openai_compat import (
    OpenAICompatClient,
    ProviderError,
    SmokeResult,
    smoke_provider,
    smoke_provider_native,
)


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


def _smoke_deepseek(config: AgentConfig, native: bool) -> SmokeResult:
    api_key = os.environ.get(config.deepseek_api_key_env, "")
    if not api_key:
        raise ProviderError(f"DeepSeek API key is required in {config.deepseek_api_key_env}.")
    if native:
        return smoke_provider_native(
            provider_name="deepseek",
            api_key=api_key,
            model=config.model,
            base_url=DEFAULT_DEEPSEEK_BASE_URL,
            api_key_env=config.deepseek_api_key_env,
            provider_label="DeepSeek",
        )
    return smoke_deepseek_provider(
        api_key=api_key,
        model=config.model,
        api_key_env=config.deepseek_api_key_env,
    )


def _smoke_openai_compat(config: AgentConfig, native: bool) -> SmokeResult:
    if not config.base_url.strip():
        raise ProviderError("openai-compat smoke requires base_url in .agent/config.toml.")
    api_key = os.environ.get(config.api_key_env, "")
    if native:
        return smoke_provider_native(
            provider_name="openai-compat",
            api_key=api_key,
            model=config.model,
            base_url=config.base_url,
            api_key_env=config.api_key_env,
            provider_label="openai-compat",
        )
    return smoke_provider(
        provider_name="openai-compat",
        api_key=api_key,
        model=config.model,
        base_url=config.base_url,
        api_key_env=config.api_key_env,
        provider_label="openai-compat",
    )


@dataclass(frozen=True)
class ProviderSpec:
    factory: Callable[[AgentConfig], LLMClient]
    capabilities: ProviderCapabilities
    api_key_env: Callable[[AgentConfig], str] | None
    api_key_required: bool
    requires_base_url: bool
    smoke: Callable[[AgentConfig, bool], SmokeResult] | None


PROVIDER_REGISTRY: dict[str, ProviderSpec] = {
    "fake": ProviderSpec(
        factory=lambda _config: FakeLLMClient(),
        capabilities=FakeLLMClient.capabilities,
        api_key_env=None,
        api_key_required=False,
        requires_base_url=False,
        smoke=None,
    ),
    "deepseek": ProviderSpec(
        factory=_make_deepseek,
        capabilities=DeepSeekClient.capabilities,
        api_key_env=lambda config: config.deepseek_api_key_env,
        api_key_required=True,
        requires_base_url=False,
        smoke=_smoke_deepseek,
    ),
    "openai-compat": ProviderSpec(
        factory=_make_openai_compat,
        capabilities=OpenAICompatClient.capabilities,
        api_key_env=lambda config: config.api_key_env,
        api_key_required=False,
        requires_base_url=True,
        smoke=_smoke_openai_compat,
    ),
}


def make_llm(config: AgentConfig):
    return PROVIDER_REGISTRY[config.provider].factory(config)
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_llm_factory.py tests/test_capabilities.py -q`
Expected: 全部 passed

- [x] **Step 5: 相邻回归（make_llm 消费方）**

Run: `python -m pytest tests/test_cli.py tests/test_web.py -q`
Expected: 全部 passed（`make_llm` 行为未变；CLI 尚未接线）

- [x] **Step 6: Commit**

```bash
git add src/agent/llm/factory.py tests/test_llm_factory.py
git commit -m "feat: provider registry with capability and smoke specs"
```

---

### Task 3: run_once 能力判定与 capability_warning

**Files:**
- Modify: `src/agent/core/loop.py`（import 行 + `run_once` 内两处；`_model_response` 不动）
- Test: `tests/core/test_loop_capabilities.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `resolve_capabilities`。
- Produces: `capability_warning` run event，record 形如 `{"event": "capability_warning", "run_id": <str>, "requested": "native_tools", "fallback": "json-protocol"}`（`_emit_event` 会把 event 名并入 record，Task 4 的 CLI 打印依赖这些键）。

- [x] **Step 1: 写失败测试**

新建 `tests/core/test_loop_capabilities.py`：

```python
from __future__ import annotations

from agent.config import AgentConfig
from agent.core.loop import run_once
from agent.llm.fake import FakeLLMClient


def _capability_events(events: list[dict]) -> list[dict]:
    return [event for event in events if event.get("event") == "capability_warning"]


def test_native_tools_mismatch_emits_single_warning_and_downgrades(tmp_path) -> None:
    events: list[dict] = []

    result = run_once(
        "finish",
        FakeLLMClient(),
        cwd=tmp_path,
        config=AgentConfig(native_tools=True),
        event_handler=events.append,
    )

    warnings = _capability_events(events)
    assert len(warnings) == 1
    assert warnings[0]["requested"] == "native_tools"
    assert warnings[0]["fallback"] == "json-protocol"
    assert warnings[0]["run_id"] == result.context.run_id
    assert result.observation.status == "ok"


def test_matched_capabilities_emit_no_warning(tmp_path) -> None:
    events: list[dict] = []

    run_once(
        "finish",
        FakeLLMClient(),
        cwd=tmp_path,
        config=AgentConfig(),
        event_handler=events.append,
    )

    assert _capability_events(events) == []


def test_capable_double_with_native_config_emits_no_warning(tmp_path) -> None:
    class NativeDouble:
        def chat(self, messages, *, temperature=None):
            return {}

        def chat_tools(self, messages, tools, *, temperature=None):
            return {
                "message": "",
                "action": {
                    "name": "done",
                    "args": {"final": "ok", "changed_files": [], "next_steps": []},
                },
            }

    events: list[dict] = []

    run_once(
        "finish",
        NativeDouble(),
        cwd=tmp_path,
        config=AgentConfig(native_tools=True),
        event_handler=events.append,
    )

    assert _capability_events(events) == []
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/core/test_loop_capabilities.py -q`
Expected: 第一条 FAIL（`len(warnings) == 1` 断言失败，收到 0 个事件）；后两条 PASS

- [x] **Step 3: 最小实现**

`src/agent/core/loop.py` 第 40 行 import 改为：

```python
from agent.llm.base import LLMClient, resolve_capabilities
```

`run_once` 内，把现有

```python
    use_native = effective_config.native_tools and callable(getattr(llm, "chat_tools", None))
```

替换为：

```python
    capabilities = resolve_capabilities(llm)
    use_native = effective_config.native_tools and capabilities.native_tools
    if effective_config.native_tools and not capabilities.native_tools:
        _emit_event(
            event_handler,
            "capability_warning",
            {
                "run_id": context.run_id,
                "requested": "native_tools",
                "fallback": "json-protocol",
            },
        )
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/core/test_loop_capabilities.py -q`
Expected: 3 passed

- [x] **Step 5: loop 全量回归（含 ScriptedNativeLLM/StreamingNativeLLM 派生路径）**

Run: `python -m pytest tests/core -q`
Expected: 全部 passed

- [x] **Step 6: Commit**

```bash
git add src/agent/core/loop.py tests/core/test_loop_capabilities.py
git commit -m "feat: emit capability warning on native tools downgrade"
```

---

### Task 4: CLI 按注册表接线

**Files:**
- Modify: `src/agent/cli.py`（imports、doctor、`config show`、`release doctor`、chat 开流、`provider smoke`、`_chat_event_handler`）
- Modify: `tests/test_cli.py`（monkeypatch 目标 ×5、doctor 断言、新增 3 条测试）

**Interfaces:**
- Consumes: Task 2 的 `PROVIDER_REGISTRY`/`ProviderSpec`；Task 3 的 `capability_warning` record 键。
- Produces: `_print_provider_capabilities(config) -> None`（cli.py 内部 helper，doctor / `config show` / `release doctor` 共用）。输出行契约：`provider adapter capabilities: streaming=<bool> native_tools=<bool>`、`base_url: ...`（仅 requires_base_url）、`api key env/required/present: ...`（仅 api_key_env 非 None）、`capability warning: native_tools enabled but provider lacks native tool calling`（仅不匹配时）。

- [x] **Step 1: 更新既有断言 + 写失败测试**

`tests/test_cli.py`：

1. `test_doctor_reports_python_and_cwd`（137-138 行）与 `test_config_doctor_reports_same_core_diagnostics`（163-164 行），两处相同修改：

```python
    # 删除:
    assert "deepseek api key env:" in result.output
    assert "deepseek api key present:" in result.output
    # 换成:
    assert "provider adapter capabilities: streaming=false native_tools=false" in result.output
    assert "deepseek api key env:" not in result.output
```

2. `test_release_doctor_reports_release_readiness`：`assert "model: deepseek-v4-flash" in result.output` 之后加：

```python
    assert "provider adapter capabilities: streaming=false native_tools=false" in result.output
    assert "deepseek api key present:" not in result.output
```

3. `test_config_show_outputs_defaults_for_requested_cwd`（1604 行）：

```python
    # 删除:
    assert "deepseek_api_key_env: DEEPSEEK_API_KEY" in result.output
    # 换成:
    assert "provider adapter capabilities: streaming=false native_tools=false" in result.output
```

4. 5 处 monkeypatch 目标（1025、1064、1084、1135、1163 行）从 `agent.cli.*` 改为 `agent.llm.factory.*`：

```python
    monkeypatch.setattr("agent.llm.factory.smoke_deepseek_provider", fake_smoke)      # ×3
    monkeypatch.setattr("agent.llm.factory.smoke_provider", fake_smoke)               # ×1
    monkeypatch.setattr("agent.llm.factory.smoke_provider_native", fake_native_smoke) # ×1
```

5. 文件末尾追加三条新测试（`app`、`CliRunner` 沿用文件既有 import）：

```python
def test_doctor_shows_auth_env_for_deepseek_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    workspace = tmp_path / "workspace"
    (workspace / ".agent").mkdir(parents=True)
    (workspace / ".agent" / "config.toml").write_text('provider = "deepseek"\n', encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["config", "doctor", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert "provider adapter capabilities: streaming=true native_tools=true" in result.output
    assert "api key env: DEEPSEEK_API_KEY" in result.output
    assert "api key required: true" in result.output
    assert "api key present: false" in result.output


def test_doctor_warns_on_native_tools_capability_mismatch(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".agent").mkdir(parents=True)
    (workspace / ".agent" / "config.toml").write_text("native_tools = true\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["config", "doctor", "--cwd", str(workspace)])

    assert result.exit_code == 0
    assert (
        "capability warning: native_tools enabled but provider lacks native tool calling"
        in result.output
    )


def test_run_prints_capability_warning_event(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".agent").mkdir(parents=True)
    (workspace / ".agent" / "config.toml").write_text("native_tools = true\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["run", "--cwd", str(workspace), "inspect project"])

    assert result.exit_code == 0
    assert "capability warning: native_tools unavailable; falling back to json-protocol" in result.output
```

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_cli.py -q`
Expected: FAIL（更新断言与三条新测试失败；smoke 测试因 monkeypatch 目标迁移暂时失败属预期——`agent.llm.factory` 中函数已存在，但 CLI 还没走注册表路径，行为断言未生效）

- [x] **Step 3: 实现 CLI 接线**

`src/agent/cli.py`：

1. imports（21、23 行）改为，并保留其余不动：

```python
from agent.llm.deepseek import DeepSeekError
from agent.llm.factory import PROVIDER_REGISTRY, make_llm as make_llm_client
from agent.llm.openai_compat import ProviderError
```

2. 在 `_print_doctor` 定义之前加 helper：

```python
def _print_provider_capabilities(config) -> None:
    spec = PROVIDER_REGISTRY[config.provider]
    caps = spec.capabilities
    console.print(
        "provider adapter capabilities: "
        f"streaming={str(caps.streaming).lower()} "
        f"native_tools={str(caps.native_tools).lower()}"
    )
    if spec.requires_base_url:
        console.print(f"base_url: {config.base_url}")
    if spec.api_key_env is not None:
        env_name = spec.api_key_env(config)
        console.print(f"api key env: {env_name}")
        console.print(f"api key required: {str(spec.api_key_required).lower()}")
        console.print(f"api key present: {str(bool(os.environ.get(env_name))).lower()}")
    if config.native_tools and not caps.native_tools:
        console.print("capability warning: native_tools enabled but provider lacks native tool calling")
```

3. `_print_doctor`（89-94 行）删除 deepseek 两行与 openai-compat 条件块，原位替换为：

```python
    _print_provider_capabilities(config)
```

4. `config_show`：解析 workspace 后先调用 `load_workspace_secrets(workspace)`；删除 `console.print(f"deepseek_api_key_env: {config.deepseek_api_key_env}")` 与其后的 `if config.provider == "openai-compat":` 条件块（449-453 行），原位替换为：

```python
    _print_provider_capabilities(config)
```

5. `release_doctor`：`console.print(f"deepseek api key present: ...")`（129 行）替换为：

```python
    _print_provider_capabilities(config)
```

6. chat 开流判断（398-399 行）改为：

```python
        stream_handler, stream_was_used = _make_chat_stream_handler(
            PROVIDER_REGISTRY[config.provider].capabilities.streaming
        )
```

7. `provider_smoke` 函数体（490-553 行）整体替换为（签名与 `console.print` 结果输出段 555 行起不动）：

```python
    spec = PROVIDER_REGISTRY.get(provider_name)
    if spec is None or spec.smoke is None:
        console.print(f"Unsupported provider smoke target: {provider_name}")
        raise typer.Exit(code=1)
    workspace = (cwd or Path.cwd()).resolve()
    load_workspace_secrets(workspace)
    try:
        config, diagnostics = load_config(workspace, overrides=ConfigOverrides(model=model))
    except ConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc

    try:
        result = spec.smoke(config, native)
    except ProviderError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
```

（`DeepSeekError` 是 `ProviderError` 的别名，单一 except 覆盖两者。）

8. `_chat_event_handler` 的 elif 链末尾（`approval_required` 分支之后）追加：

```python
    elif name == "capability_warning":
        console.print(
            f"capability warning: {event.get('requested')} unavailable; "
            f"falling back to {event.get('fallback')}"
        )
```

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_cli.py -q`
Expected: 全部 passed

- [x] **Step 5: 字面量清零验证**

Run: `grep -n "openai-compat\"\|\"deepseek\"" src/agent/cli.py`
Expected: 无输出（cli.py 不再有 provider 名字字面量分支）

- [x] **Step 6: Commit**

```bash
git add src/agent/cli.py tests/test_cli.py
git commit -m "refactor: drive cli provider paths from capability registry"
```

---

### Task 5: 收尾——文档同步与全量门禁

**Files:**
- Modify: `CHANGELOG.md`（Unreleased 顶部加一条）
- Modify: `docs/roadmap-progress.md`（next slice 段落）
- Modify: `docs/superpowers/specs/2026-07-22-provider-capability-declaration-design.md`（状态行）

**Interfaces:**
- Consumes: Task 1-4 全部完成。
- Produces: 无代码接口；文档与验收证据。

- [x] **Step 1: CHANGELOG**

`CHANGELOG.md` 的 `## Unreleased` 下第一条加：

```markdown
- Provider Adapter 能力声明：`ProviderCapabilities` 类级声明 + `ProviderSpec` 注册表取代 runtime getattr 散点探测与 CLI provider 名字分支；能力只描述本地 streaming/native-tools 路径，auth 元数据区分必需与可选 key，`config show` 与 doctor 统一读取 workspace secrets；`native_tools = true` 而 Adapter 不支持时发 `capability_warning` 并照旧降级 JSON 协议；`provider smoke` 由注册表准入。不含 reasoning/context 等模型级声明、模型选择与 Workbench 能力暴露。
```

- [x] **Step 2: roadmap-progress**

`docs/roadmap-progress.md` 中：

```markdown
Completed slice: Project vNext Phase 2 managed MCP and Skills lifecycle.

Next Project vNext slice: Provider capability declaration, then the remaining
Phase 2 management surface. Marketplace, registry, remote sources, Workbench
write interfaces, and automatic reconnect stay out of scope until a later
slice has its own spec.
```

替换为：

```markdown
Completed slice: Project vNext Phase 2 managed MCP and Skills lifecycle, then
provider capability declaration.

Next Project vNext slice: the remaining Phase 2 management surface. Marketplace,
registry, remote sources, Workbench write interfaces, and automatic reconnect
stay out of scope until a later slice has its own spec.
```

- [x] **Step 3: spec 状态**

spec 头部 `- 状态：已批准，待实施` 改为 `- 状态：已实施（全量门禁通过）`。

- [x] **Step 4: 全量门禁**

Run: `python -m pytest -q`
Expected: 全部 passed（基线 943 + 新增 ~18）

Run: `git diff --check`
Expected: 无输出

- [x] **Step 5: Commit**

```bash
git add CHANGELOG.md docs/roadmap-progress.md docs/superpowers/specs/2026-07-22-provider-capability-declaration-design.md
git commit -m "docs: close provider capability declaration slice"
```
