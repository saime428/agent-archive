# 设计:OpenAI 兼容 provider 泛化(第二期·子项目 1)

日期:2026-07-10
状态:已获用户批准(方案 B:改名泛化 + 预设)
范围:`src/agent/llm/`、`src/agent/config.py`、`src/agent/cli.py`、`src/agent/web/server.py`(仅 provider 校验与展示)、对应测试

## 背景与动机

`DeepSeekClient` 实现的就是标准 OpenAI Chat Completions 协议(`/chat/completions`、SSE 流式、Bearer 认证),DeepSeek 特有的只有默认 base_url/model 和命名。把它泛化为 `OpenAICompatClient` 后,Ollama、vLLM、LM Studio 等本地端点和 Moonshot、Qwen 等云服务全部零成本可用——对一个"本地优先、日志不出机器"的 agent,本地模型支持是产品叙事的关键拼图。用户当前未安装 Ollama:本地端点作为配置能力交付,验证靠 DeepSeek 真实端点(兼容性回归)+ 离线 mock。

## 设计

### 1. 模块结构

新建 `src/agent/llm/openai_compat.py`,现有 `deepseek.py` 客户端代码整体迁入并泛化:

- `ProviderError(RuntimeError)` — 通用错误类。
- `OpenAICompatClient` — 由 `DeepSeekClient` 更名而来,构造参数新增 `provider_label: str = "Provider"`(用于错误消息前缀,如 `f"{label} API request failed: ..."`)。**api key 允许为空**:为空时请求不携带 `Authorization` 头(Ollama/vLLM 本地端点无需认证);`base_url`、`model` 必填非空,否则抛 `ProviderError`。
- `SmokeResult`(由 `DeepSeekSmokeResult` 更名,字段不变)与 `smoke_provider(...)`(由 `smoke_deepseek_provider` 泛化,新增 `provider_name: str` 与 `provider_label: str` 参数,api key 允许为空)。
- 传输层(`_ReusableHTTPTransport`)、重试(`_retry_transient`)、SSE 解析、`_normalize_smoke_action` 原样迁入,错误消息改用 `provider_label` 前缀。

`deepseek.py` 瘦身为预设层,保持全部现有导入路径与行为:

- `DEFAULT_DEEPSEEK_BASE_URL` / `DEFAULT_DEEPSEEK_MODEL` 常量保留。
- `DeepSeekError = ProviderError`(别名)。
- `DeepSeekClient(OpenAICompatClient)` — 传入 DeepSeek 默认值与 `provider_label="DeepSeek"`,并在构造时强制非空 api key(保持现有 "DeepSeek API key is required." 消息)。
- `DeepSeekSmokeResult = SmokeResult`(别名);`smoke_deepseek_provider(...)` 变为调用 `smoke_provider` 的薄包装,签名与返回值不变。

**兼容性验收标准:`tests/test_deepseek.py` 一字不改仍全绿。**

### 2. 配置

`config.py`:

- 新增键 `base_url: str = ""`(允许空;openai-compat 必需性在 factory 校验)。
- 新增键 `api_key_env: str = "OPENAI_API_KEY"`(openai-compat 用;`deepseek_api_key_env` 保留,deepseek provider 继续用它)。
- `Provider` Literal 与 `VALID_VALUES["provider"]` 加 `"openai-compat"`。
- 两个新键进入 `KNOWN_KEYS`、`AgentConfig`、`ConfigOverrides`、`_apply_overrides`、`_validate_value`(`base_url` 校验为字符串——允许空串;`api_key_env` 校验为非空字符串)。

`base_url` 为空时不在配置加载阶段报错——doctor 等命令不应因未完成的配置崩溃;`make_llm` 构造时才抛带指引的 `ProviderError`("openai-compat provider requires base_url in .agent/config.toml")。

### 3. Factory

`factory.py` 注册表加:

```python
"openai-compat": _make_openai_compat,
```

`_make_openai_compat`:`base_url` 为空则抛 `ProviderError`;从 `os.environ.get(config.api_key_env, "")` 读 key(允许空);构造 `OpenAICompatClient(api_key=..., model=config.model, base_url=config.base_url, provider_label="openai-compat")`。

### 4. CLI 与 Web

`cli.py`:

- `provider smoke` 命令泛化:接受 `deepseek`(现有路径不变,含"缺 key 即退出"检查)与 `openai-compat`(用 `config.base_url`/`config.api_key_env`,key 可空,`base_url` 空则报错退出);其余 provider 名仍报 "Unsupported provider smoke target"。
- 流式判断 `config.provider == "deepseek"`(cli.py:316)改为 `config.provider in {"deepseek", "openai-compat"}`。
- doctor / config show 输出:provider 为 openai-compat 时补印 `base_url` 与 `api_key_env`、key 是否存在;deepseek 行为不变。

`web/server.py`(最小改动):

- 第 557-558 行 provider 白名单 `{"fake", "deepseek"}` 加 `"openai-compat"`,错误消息同步。
- 第 252-299 行配置展示 payload 补充 `base_url`、`api_key_env` 字段(只读展示);第 271-284 行的提示文案对 openai-compat 给出等价提示(base_url 未配 / key 缺失)。

`core/summary.py:151` 保持不变(deepseek 键仍存在)。

### 5. 测试与验收

新增 `tests/test_openai_compat.py`:

- 空 api key → 请求头无 `Authorization`;非空 → 有。
- `base_url`/`model` 空 → `ProviderError`。
- 错误消息含 `provider_label` 前缀。
- `smoke_provider` 各分支(复用 test_deepseek 的 transport stub 模式)。

`tests/test_llm_factory.py` 追加:openai-compat 入口构造成功(带 base_url)、缺 base_url 抛 `ProviderError`、key 可空。
`tests/test_config.py` 追加:两个新键的默认值/加载/校验、provider="openai-compat" 合法。
`tests/test_cli.py` / `tests/test_web.py` 按现有模式追加 smoke 泛化与 server 白名单用例(最小数量)。

验收:

- `python -m pytest -q` 全绿(含未改动的 `test_deepseek.py`)。
- `python -m agent.cli doctor` 正常。
- 用户机器冒烟:`python -m agent.cli provider smoke deepseek` 仍通过(真实端点回归)。

验证协议沿用第一期:沙箱 py_compile + 静态审查,pytest 在用户机器统一门禁。

## 范围外

原生 function calling(子项目 2)、配置模型重构([provider.*] 表)、移除 `deepseek_api_key_env`、Web 设置对新键的写入 UI、`_mode_max_iterations`、shell.py、repair 通道。

## 后续

子项目 2:provider 声明 `supports_native_tools`,支持则把 `ARGS_MODELS` 转 JSON Schema 走原生 function calling,否则回落现有 JSON 协议。
