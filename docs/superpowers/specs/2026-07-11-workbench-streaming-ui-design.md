# Workbench 流式输出与输入区精简设计

日期:2026-07-11
状态:已定稿
前置:2026-07-10 原生 function calling(已完成,`native_tools = true` 日常在用)

## 背景与问题

用户实测反馈三个问题:

1. **Web 聊天没有流式输出**。CLI `agent chat` 已流式,但 Web 端 `_run_chat_job` 调 `session.run_turn()` 时未传 `stream_handler`,SSE 只推生命周期事件,正文在 `final` 事件整段到达。
2. **输入框下方 8 个 chip 全是只读摆设**(provider、API key、联网、电脑文件、模式、沙箱、审批、工作过程),无一可点;真正常切的联网/电脑文件开关藏在设置面板。
3. **窗口最大化后布局错位**:用户消息贴最左、agent 回复居中。根源是 `.message-bubble.user` 的 `margin-inline: 0 auto`(auto 右边距把气泡推到容器最左),与 `.chat-thread > *` 的 760px 居中列冲突。

## 目标

1. Web 聊天流式渲染:模型思考(reasoning_content)、正文(content)、工具参数(arguments)分片实时推到浏览器,按类别渲染。
2. 输入区只留有用且可操作的控件:联网、电脑文件、原生工具三个可点开关 + 工作过程显示开关;其余 chip 移除(信息已在设置面板)。
3. 最大化窗口下用户消息右对齐、agent 回复左对齐,同一条 760px 居中列。

## 设计

### 1. 流式分片打标(openai_compat)

- `_ToolCallAssembler.feed(delta)` 增加 `reasoning_content` 处理(DeepSeek thinking 模型把思考放在 `delta.reasoning_content`,当前被丢弃);返回值从 `str | None` 改为 `list[tuple[str, str]]`(kind, text),kind ∈ `thinking` / `content` / `args`。
- `stream_chat_tools` 生成器 yield 类型从 `str` 改为 `tuple[str, str]`;return 信封不变(reasoning 不进信封,与非流式一致)。
- JSON 协议 `stream_chat` 不动。

### 2. 循环透传(loop.py)

- `_model_response` native 分支解包 `(kind, text)`:`stream_handler(text)` 契约不变(CLI 零改动感知,顺带能看到思考文本);`model_stream_chunk` 事件负载扩为 `{"kind", "text", "chunk_chars"}`。
- JSON 协议分支事件同样补 `"kind": "content", "text": text`,两条通道事件形状一致。

### 3. Web 后端(server.py)

- `_run_chat_job` 给 `run_turn` 传 `stream_handler=lambda _text: None`(激活流式路径;文本经 `model_stream_chunk` 事件 → `_append_chat_event` → SSE,复用现有通道,不加新端点)。
- `_validated_config_updates` 白名单增加 `native_tools`(布尔校验,与 `dry_run` 同模式)。此前"布尔键不在 Web 可写范围"的约束由本设计显式解除——三个开关都要在输入区直接切。

### 4. 前端

- `sse.js`:`CHAT_EVENT_NAMES` 增加 `model_stream_chunk`(`model_stream_start` 已在)。
- `chat.js` 实时事件处理:`kind === "content"` 追加进 agent 气泡正文;`thinking` / `args` 追加进"工作过程"折叠区;`final` 事件到达后以最终文本替换(现状行为),流式区内容保留在工作过程折叠区。
- 输入区(index.html `.input-actions`)重构:
  - 移除:provider、API key、模式、沙箱、审批 5 个只读 pill(信息在设置面板已有)。
  - 保留并升级为可点开关(button):联网、电脑文件、原生工具(新增)。点击 → `postJson("/api/config", {<单键>: !当前值})`,乐观更新样式,失败回滚并提示。
  - "工作过程" pill → 显示开关:控制实时 thinking/args 区展开/收起,状态存 localStorage,不写配置。
- 单键 POST 依赖服务端部分更新语义(`_validated_config_updates` 只处理出现的键,已满足);前端不再复用 `saveSettingsValues`(它会整表提交,误覆盖设置面板未保存的输入)。

### 5. 布局(app.css)

- `.chat-thread` 改为列内边距承担居中:`padding-inline: max(clamp(20px, 5vw, 40px), calc((100% - 760px) / 2))`,子元素去掉逐个居中。
- `.message-bubble.user`:`margin-inline: auto 0`(右对齐),删除错误的 `0 auto`。
- `.input-dock` 与消息列同宽同轴(max-width 760px 居中)。

## 测试与验收

- `tests/test_openai_compat.py`:现有流式用例改为解包 `(kind, text)`;新增 reasoning_content 分片用例(thinking 分片 yield、不进信封)。
- `tests/core/test_loop_native.py` 或新文件:脚本化流式客户端驱动 run_once,断言 `model_stream_chunk` 事件含 kind/text。
- `tests/test_web.py`:`native_tools` 写入接受布尔/拒绝非布尔;chat job 事件流包含 model_stream_chunk(fake 流式客户端注入)。
- 前端无自动化测试,走用户门禁手工冒烟。
- 用户门禁:pytest 全绿;启动 workbench 真实对话,确认思考/正文实时出现、三个开关点击后 `.agent/config.toml` 落盘、最大化窗口消息对齐。

## 范围外

SSE 分片合并/节流、markdown 增量渲染、前端框架迁移、审批流变更、CLI 输出格式变更、设置面板重构、`args` 分片的增量 JSON 解析(final 仍以 final 事件为准)。

## 风险与缓解

- **每分片一条 SSE 事件的开销**:本地回环 + DeepSeek 分片粒度实测可接受;若卡顿,范围外的节流再进。
- **移除 chip 引用导致 JS 报错**:`state.js` 的 els 与 `health.js` 渲染引用点逐一清理,计划列明清单。
- **乐观更新与配置落盘不一致**:失败回滚 + 每次 `refreshWorkbench` 拉真值。
