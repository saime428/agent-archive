# 设计:原生 function calling(第二期·子项目 2)

日期:2026-07-10
状态:设计已获用户批准(含流式;先出计划,暂不执行)
范围:`src/agent/core/tool_schemas.py`(新)、`src/agent/llm/openai_compat.py`、`src/agent/config.py`、`src/agent/core/loop.py`、`src/agent/cli.py`、`src/agent/web/server.py`(仅展示)、对应测试

## 背景与动机

当前模型以"JSON-in-text"返回动作:系统提示教格式、`parse_model_action` 校验、repair 循环纠错。OpenAI 兼容端点普遍支持原生 function calling——模型专门为此训练,格式错误率低一个量级,且省去系统提示里教格式的 token。本设计让 provider 走原生工具调用,现有 JSON 协议保留为 fallback(fake provider 与不支持工具的端点继续可用)。

## 核心决策

1. **所有动作皆工具**:`done`、`ask_user` 与全部 `SUPPORTED_TOOL_ACTIONS` 一样暴露为工具;请求带 `tool_choice: "required"`,每轮必须恰好调一个工具。模型的 `content` 字段映射为内部信封的 `message`。
2. **不猜测意图**:响应无 tool_call(或参数 JSON 非法)不视为 done,统一落入现有 repair 循环(native 模式下 repair 提示语改为"调用恰好一个工具")。
3. **多个 tool_calls 取第一个**,忽略其余(step/guided 模式提示本就不鼓励链式;文档注明)。
4. **含流式**:`stream_chat_tools` 做 SSE 工具调用分片拼装;`content` 与 `function.arguments` 分片都作为文本 chunk 逐段 yield 给 UI(与现状"流式显示原始 JSON 文本"体验一致),生成器 return 值为拼装完成的信封。
5. **显式开关**:新配置键 `native_tools: bool = false`,仅当 provider 客户端具备 `chat_tools` 能力时生效(fake provider 自动回落 JSON 协议)。不做端点能力自动探测——各家支持参差,显式优于猜测。
6. **单一校验路径不变**:客户端把原生响应规整为现有信封 dict `{"message": ..., "action": {"name": ..., "args": ...}}`,仍由 `parse_model_action` 统一校验;参数 JSON 非法时客户端返回原始字符串,走现有 `INVALID_JSON` repair 路径。

## 设计

### 1. 工具 Schema 导出(`core/tool_schemas.py`,新模块)

- `ACTION_DESCRIPTIONS: dict[str, str]` — 每个动作一句英文描述(计划中给全文)。
- `build_tool_schemas(action_names) -> list[dict]` — 对每个名字生成 `{"type": "function", "function": {"name", "description", "parameters": ARGS_MODELS[name].model_json_schema()}}`。pydantic `extra="forbid"` 自然产出 `additionalProperties: false`。
- `native_tool_names(config) -> list[str]` — `done`、`ask_user` 恒在;加 `SUPPORTED_TOOL_ACTIONS`,但 `web_search_enabled=False` 时剔除 `web_search`(附带收益:禁用的工具模型根本看不见)。

### 2. 客户端(`openai_compat.py`)

- `chat_tools(messages, tools, *, temperature=None) -> dict | str`:payload 增 `"tools": tools, "tool_choice": "required"`,非流式;响应经 `_envelope_from_tool_message(message_obj, provider_label)` 规整:
  - 有 `tool_calls`:取第一个,`json.loads(function.arguments)` 成功 → 信封 dict;失败 → 返回 `function.arguments` 原始字符串(交给 repair)。
  - 无 `tool_calls`:返回 `{"message": content}`(缺 `action` 字段,`parse_model_action` 报 `MISSING_REQUIRED_FIELD` → repair)。
- `stream_chat_tools(messages, tools, *, temperature=None) -> Generator[str, None, dict | str]`:SSE 逐行解析 delta:
  - `delta.content` 分片:累积并 yield;
  - `delta.tool_calls[i]`:按 `index` 累积 `id`/`function.name`(首片)与 `function.arguments`(逐片拼接),arguments 分片同样 yield(UI 可见);只拼装 index 0,其余 index 的分片忽略;
  - `[DONE]` 或流结束:用与非流式相同的 `_envelope_from_tool_message` 等价逻辑规整,作为生成器 return 值(调用方经 `StopIteration.value` 获取);
  - 传输错误与非法 SSE:沿用现有重试与 `ProviderError` 语义。
- 现有 `chat` / `stream_chat` 完全不动;DeepSeek 预设自动继承两个新方法。

### 3. 配置(`config.py`)

`native_tools: bool = False`:KNOWN_KEYS、AgentConfig、ConfigOverrides、`_apply_overrides`、`_validate_value` 布尔集合。deepseek 与 openai-compat 共用;fake 下无效果(客户端无 `chat_tools`)。

### 4. 循环集成(`loop.py`)

- `run_once` 计算 `use_native = effective_config.native_tools and hasattr(llm, "chat_tools")`,据此:
  - 系统提示:native 变体不教 JSON 格式,改为"每轮恰好调用一个工具;完成用 done,提问用 ask_user",模式指令与 web/computer 规则原样保留;
  - `_model_response`:native 分支——有 `stream_handler` 且客户端有 `stream_chat_tools` 时驱动生成器(chunk → stream_handler,`StopIteration.value` → 响应),否则 `chat_tools`;工具列表由 `build_tool_schemas(native_tool_names(config))` 每次 run 构建一次;
  - `_build_repair_message`:native 模式提示语改为工具调用措辞(参数化,非分叉复制);
  - `_trace_config` 增 `native_tools`。
- 错误恢复、连续错误预算、迭代提醒、观察回喂全部与协议无关,零改动。

### 5. CLI 与 Web(最小)

- `provider smoke <name> --native`:经 `chat_tools` 只带 `done` 工具冒烟,校验返回 done 信封;deepseek 与 openai-compat 皆可用。
- doctor / config show 输出 `native_tools` 一行。
- `server.py` 两处只读 payload 增 `native_tools` 键;设置写入白名单不动(布尔键不在 Web 可写范围,与现状一致)。

### 6. 测试与验收

- `tests/core/test_tool_schemas.py`:schema 形状、additionalProperties、web_search 过滤、done/ask_user 恒在。
- `tests/test_openai_compat.py` 追加:chat_tools payload(tools + tool_choice)、首个 tool_call 取用、参数非法返回原始串、无 tool_call 返回缺 action 信封;流式:跨分片拼装、content 与 arguments 分片皆 yield、return 值信封、[DONE]、非法 SSE 报错。
- `tests/core/test_loop_native.py`(新):脚本化 native 客户端驱动 run_once——正常工具序列、无 tool_call → repair → 纠正、native 下错误恢复仍有效、fake 客户端 + native_tools=true 回落 JSON 协议。
- CLI/Web 各按现有模式补最小用例。
- 用户门禁:`python -m pytest -q` 全绿;`agent doctor`;真实端点 `agent provider smoke deepseek --native`;再配 `.agent/config.toml` 开 `native_tools = true` 跑一次真实任务冒烟(读不存在文件的错误恢复场景,验证 native 路径 + 恢复循环协同)。

## 范围外

并行多工具调用(取第一个,不支持并行)、端点能力自动探测、fake provider 的原生模拟、Web 设置写入 UI、JSON 协议移除(永久保留为 fallback)、第三期命令白名单。

## 风险与缓解

- **端点不支持 `tool_choice: "required"`**:文档注明此类端点应保持 `native_tools = false`;错误会以 ProviderError 显式浮出,不静默。
- **流式分片形状差异**(各家 delta 结构小有出入):拼装器只依赖 `index`/`function.name`/`function.arguments`/`content` 四个字段,缺失字段一律容忍为跳过;真实端点冒烟是最终裁判。
- **schema 兼容性**(pydantic 产出的 anyOf/null 可选字段):DeepSeek 实测为准;门禁含真实冒烟。
