# 设计：Provider 能力声明

- 日期：2026-07-22
- 状态：已实施（复审修订，全量门禁通过）
- 上位方向：[Project vNext 总方向](../../project-vnext-direction.md)（seam：Provider Interface）

## 背景

Provider 差异目前以两种特判形式散落在代码里：

1. **runtime 侧 getattr 探测**（`agent/core/loop.py`）：`use_native` 依赖
   `callable(getattr(llm, "chat_tools", None))`；`_model_response` 内再分别探测
   `stream_chat_tools` 与 `stream_chat`，不支持时**静默降级**为 JSON 协议或非流式。
   用户开启 `native_tools = true` 后配置未生效也无从得知。
2. **CLI 侧 provider 名字字面量**（`agent/cli.py`）：doctor 与 `config show` 用
   `provider == "openai-compat"` 决定是否显示 `base_url`/`api_key_env`；chat 用
   `provider in {"deepseek", "openai-compat"}` 决定是否开流；`provider smoke` 用
   同一集合作为准入并按名字分支到两段 smoke 调用；release doctor 无条件打印
   DeepSeek key 状态，即使当前 provider 不是 deepseek。

三个 Adapter 的本地方法能力：`FakeLLMClient` 只有 `chat`；`OpenAICompatClient` 与
其子类 `DeepSeekClient` 具备 `chat`、`stream_chat`、`chat_tools`、
`stream_chat_tools`。这些声明只描述 Adapter 可走的代码路径，不承诺远端 endpoint
或具体模型具备相同能力。auth 要求各不同：fake 无要求；deepseek 需要 API key（有
默认 base_url）；openai-compat 的 API key 可选，但必须显式配置 `base_url`。

测试通过向 loop 直接注入临时类（如 `ScriptedNativeLLM`）驱动 native 路径，此时
`config.provider` 仍是 `"fake"`。因此 runtime 的能力事实必须来自 **llm 实例**，
不能按 provider 名字查表。

## 目标

1. Provider Adapter 显式声明 streaming、native tools 能力；runtime 与
   CLI 不再写 provider 名字分支或散落的 getattr 探测。
2. 配置要求了 provider 不具备的能力时，保持现有降级行为，但发出明确警告
   （run event + doctor 静态检查），消除静默降级。
3. CLI/doctor 按注册表读取能力与 auth 要求，**不实例化 client**（openai-compat
   缺 `base_url` 时同样能显示诊断信息）。
4. 直接注入 loop 的测试替身与外部 client 零改动继续工作。
5. 行为兼容：除新增警告事件与新增/调整的诊断输出行外，现有 run 行为、config
   文件格式、run/session 数据均不变。

## 数据结构

### ProviderCapabilities（`agent/llm/base.py`）

frozen dataclass，两个布尔字段：

| 字段 | 含义 | 声明方的方法契约（契约测试强制） |
| --- | --- | --- |
| `streaming` | 支持流式响应 | `stream_chat` 可调用；与 `native_tools` 同真时 `stream_chat_tools` 也可调用 |
| `native_tools` | 支持原生 tool calling | `chat_tools` 可调用 |

方法契约只约束**显式声明**的 Adapter；探测派生（见下）是尽力而为的宽推断，
配合 `_model_response` 的结构性兜底保证部分实现的替身行为不变。

声明位置为类属性，实例经属性查找即可读取：

- `FakeLLMClient`：两项均为 False。
- `OpenAICompatClient`：两项均为 True。
- `DeepSeekClient`：继承 `OpenAICompatClient`，不重复声明。

`reasoning` 不在本轮声明：它依赖远端模型、thinking 模式与具体响应路径，当前也不
驱动 runtime 分支。没有模型级证据链时硬编码 True 只会制造失真的诊断结果。

`LLMClient` Protocol 保持不变（它本来就不含 `chat_tools`）；capabilities 是被
`resolve_capabilities` 识别的约定属性，不进 Protocol，避免破坏结构化类型的外部实现。

### ProviderSpec 与注册表（`agent/llm/factory.py`）

`PROVIDER_REGISTRY` 的值从裸 factory 升级为 frozen dataclass `ProviderSpec`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `factory` | `Callable[[AgentConfig], LLMClient]` | 现有构造逻辑不变 |
| `capabilities` | `ProviderCapabilities` | 直接引用对应类的声明，单一事实源 |
| `api_key_env` | `Callable[[AgentConfig], str] \| None` | deepseek 读 `config.deepseek_api_key_env`；openai-compat 读 `config.api_key_env`；fake 为 None。只表示读取位置 |
| `api_key_required` | `bool` | deepseek 为 True；fake/openai-compat 为 False，避免把本地兼容端点的可选 key 误判成必需 |
| `requires_base_url` | `bool` | 仅 openai-compat 为 True |
| `smoke` | `Callable \| None` | 现有两段 smoke 调用收敛为 factory.py 内两个闭包，统一签名 `smoke(config, native) -> SmokeResult`（CLI 已用 `ConfigOverrides(model=...)` 把 `--model` 并入 config，闭包读 `config.model`，不设第二个可能不一致的 model 参数）；fake 为 None |

`make_llm(config)` 改走 `spec.factory`，签名与返回类型不变，所有调用方无感知。

`config.py` 的 `Provider` 字面量集合与注册表键用契约测试锁定一致，防止两处漂移。

## resolve_capabilities 与 runtime 接线

`agent/llm/base.py` 新增：

```python
def resolve_capabilities(llm) -> ProviderCapabilities:
    declared = getattr(llm, "capabilities", None)
    if isinstance(declared, ProviderCapabilities):
        return declared
    return ProviderCapabilities(
        streaming=callable(getattr(llm, "stream_chat", None)),
        native_tools=callable(getattr(llm, "chat_tools", None)),
    )
```

派生的 `streaming` 只表示普通 `stream_chat` 路径；native 流是否可用仍由
`_model_response` 结构性检查 `stream_chat_tools`，缺失时回退 `chat_tools`。这是能力
**判定**的唯一探测点，服务测试替身与外部注入 client。

`run_once` 开始处解析一次：

- `use_native = effective_config.native_tools and caps.native_tools`（替换现有
  getattr 探测）。
- `_model_response` **保持不动**：它的两处 getattr 是结构性兜底而非能力判定
  （`stream_chat_tools` 为 None 回退 `chat_tools`、`stream_chat` 为 None 回退
  `chat`），对声明、派生与部分实现的替身行为天然一致。能力判定只发生在
  `run_once` 开头（`use_native` 与警告）。

## 能力不匹配警告

run 开始时只检测一种不匹配：`config.native_tools=true` 且
`caps.native_tools=false` 时发一次 `capability_warning` run event（复用现有
`_emit_event` 通道），payload 为 `{"run_id", "requested": "native_tools",
"fallback": "json-protocol"}`，行为仍按现状降级为 JSON 动作协议。

**不对 streaming 做 run 内警告**：streaming 没有 config 意图开关，
`stream_handler` 是调用方机会式传入的——`web/chat_runtime.py` 对包括 fake 在内
的所有 provider 恒传 no-op handler，若按 handler 存在性告警，fake 的每次
Workbench run 都会产生固定噪声。streaming 能力只在 doctor / `config show`
静态展示；CLI chat 用注册表能力决定是否开流。

`_chat_event_handler`（`run` 与 `chat` 共用）新增一个 elif 打印该事件；Workbench
的 event 消费方本轮不动。

**边界**：消除静默降级只对显式声明能力的注册 provider 成立；探测派生是宽推断，
`_model_response` 的结构性兜底继续对任何部分实现静默回退——这是行为兼容的
**有意保留**，实施时不要把兜底改成警告或报错。

## CLI/doctor 接线

| 位置 | 现状 | 改为 |
| --- | --- | --- |
| `_print_doctor`、`config show` | `if provider == "openai-compat"` 才显示 base_url/key | 按 `ProviderSpec` 驱动：`requires_base_url` 决定显示 `base_url`，`api_key_env`/`api_key_required` 决定显示 env、required 与 present 状态；新增 `provider adapter capabilities: ...` 一行；`config show` 与 doctor 一样先加载 workspace secrets；`native_tools=true` 但能力缺失时输出警告行（纯注册表查询，不实例化） |
| chat 开流判断 | `provider in {"deepseek", "openai-compat"}` | `PROVIDER_REGISTRY[config.provider].capabilities.streaming` |
| `provider smoke` | 名字集合准入 + 两个名字分支 | `spec.smoke is None` 时拒绝并提示；否则调用 `spec.smoke(config, native)` |
| `release doctor` | 无条件打印 deepseek key 状态 | 按当前 provider 的 spec 打印 auth 状态；`api_key_env` 为 None（fake）时**省略**相关行，不打印占位值——doctor 与 `config show` 同规则 |

doctor 中原有 `deepseek api key env/present` 两行改由 spec 驱动后，仅在当前
provider 需要该 key 时显示；这是有意的输出契约变化，相关 CLI 测试同步更新。

## 测试与验收

- **契约测试**（parametrize 遍历注册表）：每个注册 provider 实例化后（fake 直接构造，
  deepseek/openai-compat 用假 key/base_url 构造，不发网络请求），声明能力与方法
  存在性一致：`streaming ⇒ stream_chat 可调用`、`native_tools ⇒ chat_tools 可调用`、
  `streaming ∧ native_tools ⇒ stream_chat_tools 可调用`。声明撒谎直接红。
- 注册表键集合 == `config.py` 的 `Provider` 集合。
- `resolve_capabilities`：声明优先、探测派生两条路径各一例。
- loop：`native_tools=true` + 无 native 能力的 llm → JSON 降级且收到
  `capability_warning`；能力匹配时无该事件。
- 现有 native/streaming/MCP loop 测试与 CLI 测试全部保持通过；doctor/config show
  输出行变化处同步更新断言。
- 探测派生契约：仅 `stream_chat_tools` 的替身不被误报为支持普通 streaming；native
  流式仍由 `_model_response` 直接检查方法并保持现有行为。
- 验收标准：`cli.py` 中除注册表查询外不再出现 provider 名字字面量分支；
  `loop.py` 的能力**判定**（`use_native`、警告）只读 capabilities，散点探测仅存
  于 `resolve_capabilities` 与 `_model_response` 的结构性方法获取；smoke 收敛后
  `cli.py` 不再 import `DEFAULT_DEEPSEEK_BASE_URL` 与 `smoke_deepseek_provider`
  （`DeepSeekError` 因 run/chat 异常处理仍在使用，保留）；全量 pytest 绿；
  `git diff --check` 干净。

## 非目标

- 上下文窗口/token 预算声明（当前无消费者，budget 是字符制）。
- reasoning/vision 等模型级能力声明；在模型、模式与响应路径没有证据链前不硬编码。
- 模型选择、连接复用、重试/退避策略变化，以及新协议 Adapter。
- Workbench HTTP 能力暴露与 `web/settings.py` 的 provider 字面量（归前端 vNext
  切片，接入真实前端时一并处理）。
- 新 provider、marketplace、registry、远程来源。
- 不新增第三方依赖；不改变 secrets 格式与 redaction 行为；`config show` 只补齐与
  doctor 一致的 workspace secrets 读取；config 文件格式与 run/session 数据不迁移。

## 兼容与迁移

- 无 config 迁移：所有现有配置键语义不变。
- 无数据迁移：run/session/trace 结构仅多一种 event 名称，旧消费者忽略未知事件
  即可（现有 `_chat_event_handler` 的 elif 链天然忽略未知事件）。
- 输出契约变化仅限 doctor / `config show` / `release doctor` 的 provider 相关行，
  在实施 plan 中逐行列出并同步测试。
