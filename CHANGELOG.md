# Changelog

## Unreleased

- 缺陷修复轮（多代理深度审查 + 逐条实证复现驱动，8/8 确认后修复）：run 收尾先持久化审计日志再做 best-effort 副作用，memory 候选存储写满或锁超时不再吞掉成功 run 的 `tool_calls.jsonl`/`summary.md`（降级为 summary 内警告行）；工具执行新增 `INTERNAL_ERROR` 兜底观察值，意外异常（如合法 `\ud800` 输入触发的 UnicodeEncodeError）不再穿透 run_once 丢失全部记录；run 日志改为临时文件 + 原子替换写入。CLI 共享 Console 关闭 rich markup，模型输出含 `[/x]` 等标记不再崩溃或被重新染色；显式 `--skill` 现在跑前预校验（对齐 automation 先例），拼错立即报错而不是静默忽略，run loop 对默认技能的防注入容错保持不变。OpenAI 兼容 Provider 修复重试路径：429/5xx 错误响应先读净关闭再抛出，keep-alive 连接不再被未读响应毒化（此前重试必抛 `ResponseNotReady`）；裸 socket/协议异常映射入既有可重试错误分类。Workbench 审批事件新增服务端权威 `expires_in_ms`，倒计时不再用任务开始时钟推算，归零不再禁用批准/拒绝按钮（以服务端裁决为准）；SSE 对未知 job 返回合成终止事件而非 400，服务重启后浏览器输入框不再永久锁死。MCP 发现调度死线覆盖 initialize + list_tools 两阶段合法预算，慢但合规的 Server 不再被误判超时。Workbench 终端子进程注入 `PYTHONIOENCODING=utf-8`，非 UTF-8 区域设置下 Python 子进程中文输出不再乱码。

- Project vNext 阶段 0–3 核心目标完成：最终矩阵在修复 Python checkout/wheel 换行不确定性后整套复跑，源码与隔离 wheel 各 1165 个 Python 测试、前端类型/规范/构建/Vitest/Playwright/视觉/性能、源码与 wheel 实服、对话/生成、CLI、后端/API、真实 DeepSeek 和可见浏览器路径全部通过；阶段 4–5 继续仅按真实需求触发。
- Phase 3E 编辑器与工作区搜索完成：桌面端懒加载 Monaco 单 editor/多 model，移动端使用共享状态的原生 textarea fallback；最多 20 个标签，保留独立 buffer/dirty/view state，关闭、离开与刷新均保护未保存内容。新增独立有界 `/api/search`，复用现有 search Tool、sandbox 与错误语义，支持文本/路径/glob/Unicode 并跳到命中行；保存继续只走显式确认和 snapshot。源码、wheel、detached、真实服务与可见浏览器复验通过，包体和依赖审计满足门槛。
- Phase 3D 稳定 Eval 完成：4 个内置 FakeLLM case 复用真实 run loop，覆盖直接完成、读文件、错误恢复和审批拒绝；记录完成/错误/Tool/耗时指标，生成有界原子本地报告，并以稳定 CLI 退出码作为离线门禁。验收同时补齐 Automation/Eval 本地状态忽略规则，并修复 Windows 下拒绝 POST 时未消费有界 body 导致的 10053 连接中止；源码、D 盘全量、detached、wheel 与污染配置真实 CLI 复验通过。
- Phase 3C 可审计 Automation 完成：新增显式前台固定间隔 worker、定义启停、latest-slot 幂等 claim、durable attempt/notification、取消与崩溃恢复；复用同一 Provider/MCP/run lifecycle、workspace lease 与安全链，且不提供自动审批。验收修复缺失 Skill 静默降级、超长异常卡住 running、summary 路径未绑定 run 和多行 CLI 审计四类问题；源码、detached 全量、wheel 与真实 CLI 通过。
- Phase 3B 可审计 Memory 生命周期完成：保留旧 JSONL，复用共享文件锁与原子发布；candidate accept/reject 只有一个终态，entry revise/delete/history 保留来源与修订链，模型检索和 Workbench 只读取当前 active 叶节点。新增真实 CLI 命令并修复长 UUID 状态行被 Rich 自动折行；源码、wheel 与真实命令验收通过。
- Phase 3A 可恢复任务生命周期完成：CLI、HTTP/SSE 与 React 共用取消、整轮超时和单 workspace lease；job/event 持久化支持服务重启后的 `interrupted` 终态，异常回合用用户新消息安全 resume 且不重放旧 Tool；受控命令取消会终止父子进程树。源码、wheel、真实服务与可见浏览器验收均已通过。
- Project vNext 完成定义已按个人生产工具与完整作品重新收口：阶段 0–3 是核心目标，阶段 4–5 改为需求触发项；最终门禁覆盖对话、生成、前端、后端/API、CLI、打包与真实浏览器，并要求修复后整套复跑。
- 修复异步新会话首次详情读取竞态：`ChatRuntime.start()` 现在只对尚未持久化的 session 在发布 ID 前走既有原子保存路径，避免 React 紧接着读取 `/api/chats/<id>` 时因 `session.json` 尚未生成而短暂返回 500。
- Frontend vNext 默认入口已切换。Phase 3I 旧壳退役也已完成：根 `/` 与 `/preview/` 复用受版本控制并随 Python wheel 发布的 React runtime；14 个旧静态文件、`/legacy/` 与只供旧壳使用的同步 `/api/chat/turn` 已删除，现行 async HTTP/SSE、安全与数据语义不变。Frontend Phase 3 已通过最终全链路缺陷清零，Phase 4–5 为需求触发项。
- Frontend vNext 阶段 2 核心功能等价：`/preview/` React 工作台从单页聊天扩展为真实工作台，覆盖 Files（浏览、预览、截断只读、snapshot-backed 编辑保存）、Runs（列表过滤、Review/Workflow/Failure/Patch Review/Recovery/Replay 只读详情、diff、二次确认恢复）、System（readiness、workspace risk、memory review 只读，config 白名单受控写，Tool 目录，资源详情跨视图跳转），并加入 10 秒安全刷新与 dirty 编辑保护。后端 HTTP/SSE schema、sandbox、snapshot、run store、config write 零改动；根 `/` 仍是旧静态 Workbench，不切换默认入口、不删除旧资源。不含 Monaco、真实 terminal、递归搜索、Git 工作区与生态管理生命周期。

- Frontend vNext 阶段 1：新增 `/preview/` React/Vite App Shell 与真实 Chat 纵切，覆盖三主题深浅模式、REST/SSE Adapter、工具与审批状态、历史重建、响应式会话轨道、单层状态 Canvas、reduced-motion 和 Lucide-only 门禁；静态服务安全解析目录 index、对可压缩资源协商 gzip，CSP 仅对 style 放宽 inline 支持并继续严格禁止 inline script。旧 `/` Workbench 与 HTTP/SSE Interface 不变。
- 扩展管理面收尾：config 加载时对未知 hook 名与永不触发的 blocking hook 发警告，新增 `agent hooks list`；`agent mcp show` 静态显示单 Server 的来源、状态与解析配置（不起进程）；顶层 `agent doctor` 聚合 MCP/Skills 一行式摘要；新增 `agent config set/unset` 受控项目 config 写命令，与 Workbench 共用 `config_write` 的验证与原子发布路径，拒绝 `sandbox=danger-full-access` 与 `approval=never`。Workbench 写接口、自动重连、marketplace、registry 与远程来源仍不在范围。
- Provider Adapter 能力声明：`ProviderCapabilities` 类级声明 + `ProviderSpec` 注册表取代 runtime getattr 散点探测与 CLI provider 名字分支；能力只描述本地 streaming/native-tools 路径，不冒充 endpoint/模型能力；auth 元数据区分必需与可选 key，`config show` 与 doctor 统一读取 workspace secrets；`native_tools = true` 而 Adapter 不支持时发 `capability_warning` 并照旧降级 JSON 协议；`provider smoke` 由注册表准入。不含 reasoning/context 等模型级声明、模型选择与 Workbench 能力暴露。
- 整体健康修复：Workbench Provider 状态与 registry 对齐，可选 API key 不再误报；服务只允许 loopback 绑定并拒绝异常 Host/跨源写入，请求线程可随服务退出；同会话 turn、重命名与删除互斥，项目配置和会话 JSON 通过现有原子发布原语写入；Office 文档读取器补充可安装 extra。
- 可管理的本地扩展生命周期：MCP 增加 managed fragment、启停状态与 `agent mcp list/validate/set/enable/disable/remove/doctor`，手写 `mcp.toml` 保持只读兼容；Skills 增加用户级 store 与 `agent skills validate/install/enable/disable/update/package/remove/doctor`，支持目录与 `.skill.zip` 两种本地来源。共享的用户存储原语（文件锁、canonical path、原子发布、事务记录）收敛到一处，崩溃后只能观察到完整旧状态或完整新状态；静态命令从不启动 Server，`doctor` 是唯一 live probe；不含 Marketplace、registry、远程来源、Workbench 写接口或自动重连。
- Skill 文档兼容 UTF-8 BOM：Windows 编辑器保存的 `SKILL.md` 不再被误报为缺少 frontmatter，与用户 MCP 配置读取保持同一容忍度。
- MCP Server 故障隔离：`ready` 之后单台 Server 的 request timeout、进程退出或 transport 失败只淘汰该 Server，健康 Server 与内置 Tool 继续可用；首次 discovery 仍为全有或全无，且不自动重放或重连。原生工具调用的空 `arguments` 现在等价于 `{}`，不再进入 repair 通道。

- MCP 故障隔离与兼容性：Runtime ready 后单个 stdio Server 的 timeout、EOF、退出或 transport/protocol 故障只淘汰该 Server，其他 MCP 与内置 Tool 继续可用；OpenAI-compatible 空白 `arguments` 归一化为 `{}`，非空畸形 JSON 仍走 repair。
- 本地 stdio MCP Tool：新增用户级配置、官方 SDK 生命周期与动态 Tool Catalog；CLI、Chat 和 Workbench 共用现有 schema 校验、Skill、policy、逐次审批、observation、脱敏与 trace，并在退出或失败时关闭 Server 进程。
- Workbench 编码任务验收修复：流式模型碎片按小批次写入 SSE，设置页可切换 `mode`，`code-dev` 明确优先最简正确改动与标准库。
- 命令白名单:新增 `allowed_commands` argv 前缀配置;首 token 忽略大小写与 `.exe`,后续 token 精确匹配;shell/network/dangerous 硬拒绝、审批与路径沙箱保持不变;CLI、审计日志和 Workbench 可只读查看生效值。
- 错误恢复:可恢复的工具错误(TOOL_FAILED/TIMEOUT/SANDBOX_VIOLATION/INVALID_ARGUMENT/POLICY_DENIED)回喂模型自我纠正,新增 `max_consecutive_errors` 配置(默认 3),连续错误耗尽预算才终止;写操作成功结果同样回喂;迭代预算剩 2 次时提醒模型收尾。
- 移除 run loop 中的中文关键词短路(`_direct_chat_answer` / `_direct_external_list_path`),所有输入统一走模型路径。
- Provider 泛化:新增 `openai-compat` provider(可配 `base_url` / `api_key_env`,api key 可空),DeepSeek 变为薄预设层,现有配置零破坏;可直接接入 Ollama/vLLM 等本地 OpenAI 兼容端点。
- 原生 function calling:`native_tools = true` 时 deepseek/openai-compat 走原生工具调用(含流式分片拼装),所有动作皆工具,`tool_choice: "auto"`(thinking 模型不支持 `"required"`),无工具调用的纯文本回复走 repair 通道;JSON 协议保留为 fallback,fake provider 自动回落。
- Workbench 流式输出:模型思考(reasoning_content)/正文/工具参数分片打标(`model_stream_chunk` 事件含 kind/text)实时渲染;输入区精简为联网/电脑文件/原生工具三个可点开关与工作过程显示开关(localStorage 记忆);`native_tools` 开放 Web 配置写入;修正最大化窗口下用户消息贴左、回复居中的对齐问题。

## 2.1.0 - 2026-07-08

- 安全硬化：保护 `.agent/` 内部状态写入，收敛 Workbench 动态 HTML 注入面，并清理过期 SSE 聊天任务。
- 工程整理：同步项目版本、建立变更日志、清理重复文档和过时路线图表格。
