# stdio MCP + 动态 Tool 注册实现计划

> **执行口径：** 按 Task 顺序实施。每个行为 Task 先写失败测试，完成 focused verification 后独立提交；不要跨 Task 预先搭壳。

**Goal：** 让用户显式配置的本地 stdio MCP Tool 动态进入一次 run 的统一 Tool Catalog，并复用现有 Skill、policy、approval、observation、redaction 和 trace。

**Architecture：** 新增单个 `mcp_runtime.py` 隔离官方异步 SDK 与子进程；现有 `tool_catalog.py` 深化为每 run 唯一事实源；`run_once` 只在安全链末端区分内置 executor 与 MCP call。CLI/Workbench 组合根拥有 Runtime，核心只借用。

**Spec：** [stdio MCP + 动态 Tool 注册 + 现有安全链](../specs/2026-07-17-stdio-mcp-dynamic-tools-design.md)

## 全局约束

- 本期只做 stdio Tool；不做 HTTP transport、resources/prompts、Marketplace、管理 UI、自动安装、热重载或重连状态机。
- 复用现有 action、Observation、Run Event、approval、redaction 和持久化格式；不新增第二套执行链或 MCP 日志。
- 只新增 spec 已确认的 `McpToolRuntime` seam。生产 Runtime 与测试 Fake 是两个 Implementation；不建立通用插件基类、factory 层或 package scaffolding。
- MCP command 只来自用户级 `~/.agent/mcp.toml`；项目配置与仓库文件永远不能启动 Server。
- 所有 MCP Tool 固定 confirmation-required；annotations 不参与降权；read-only、dry-run、approval=never 的 `tools/call` 次数必须为 0。
- 不自动重试 call。queue timeout 只取消队列项；已开始 request 的 timeout 才关闭并标记 Server failed。
- async context 必须由同一个长驻 owner task enter/exit；禁止分别用 `asyncio.run()` 或多个 portal call 管生命周期。
- 不改 Provider Adapter、内置 executor、前端静态资产、主 `AgentConfig` 或 Workbench Settings 协议。
- 任何需要安装新依赖的临时环境优先放 `D:\CodexScratch`。若实际命令会向 C 盘写入，必须先询问用户并说明路径、预计空间、替代方案和清理方式。
- 自动化测试只用 `tmp_path`/临时 home；真实验收前不得自行创建或修改 C 盘的 `~/.agent/mcp.toml`。
- 保留当前工作区其他未跟踪文件；每个 Task 只 stage 列出的文件并运行 `git diff --check`。

---

### Task 1：把持久化 redaction 前移成实时 Observation seam

**Files：**

- Modify: `src/agent/core/redaction.py`
- Modify: `src/agent/core/loop.py`
- Test: `tests/test_redaction.py`
- Test: `tests/core/test_loop_core.py`
- Test: `tests/test_chat.py`

**最小改动：**

1. 在 `core/redaction.py` 增加一个接受 `Observation`、返回“脱敏副本 + replacement count”的 helper；复用现有 `redact_value`，不复制敏感键或模式表。
2. `run_once` 对所有归一化 Observation 先脱敏、再做 budget 截断；event、RunResult、memory candidate、模型 feedback 和持久化只接触脱敏副本。
3. 用与 observations 对齐的 replacement-count 列表把实时替换数传给 `_write_run_logs`；不修改 `agent-observation-v1` 协议，不把审计元数据塞进业务 data。
4. 持久化层把实时 count 与最后一次防御性 redaction count 相加，继续正确生成每条 `redaction` 元数据和 summary 的 `redaction_applied`。
5. 内部 action args 保留执行所需原值；既有 event/persistence 仍只输出脱敏副本。

**测试：**

- 敏感值在模型第二轮 messages、observation event、RunResult、Chat final 和 durable logs 中均不存在。
- budget 先前会把敏感 dict 压成字符串 excerpt 的场景，仍在结构丢失前完成脱敏。
- replacement count 不因第二次 redaction 变成 0。
- 普通路径、diff、token budget 数字不被误删。

- [ ] Step 1: 写实时泄漏的失败测试
- [ ] Step 2: 实现一个共享 helper 并接到所有 Observation 出口
- [ ] Step 3: 运行 `python -m pytest tests/test_redaction.py tests/core/test_loop_core.py tests/test_chat.py -q`
- [ ] Step 4: 运行 `git diff --check`
- [ ] Step 5: 仅提交本 Task 文件：`git commit -m "fix: redact observations before feedback"`

---

### Task 2：用户级 MCP 配置与安全命令解析

**Files：**

- Create: `src/agent/mcp_runtime.py`
- Create: `tests/test_mcp_runtime.py`

**最小改动：**

1. 用 stdlib `tomllib`、`dataclass`、`pathlib`、`re`、`hashlib` 实现 `~/.agent/mcp.toml` 只读解析；无文件返回空 Server tuple，且不启动线程/进程。
2. 实现 `McpServerConfig`、`McpToolTarget`、`McpToolDefinition`、`McpCallResult` 与 `McpRuntimeError`；不导入 approval、Run Event 或 run store。
3. 严格校验 Server ID、`command`、`args`、`pass_env`、`cwd=config|workspace`、8 Server 上限和未知字段。
4. 默认 cwd 为 `~/.agent`；只把完整 argv token `{workspace}` 替换为 workspace 绝对路径。
5. 裸 command 使用进程启动时的 PATH/PATHEXT 快照手工解析：忽略空/相对/workspace PATH，候选 `resolve()` 后再次拒绝 workspace symlink/junction 目标；不得调用会搜索 cwd 的 `shutil.which(command)`。
6. 显式绝对 command 只做存在性/文件校验，表示用户对该精确路径的信任；相对路径拒绝。
7. 提供稳定公开名 helper：`mcp__<server>__<normalized_tool>`，超长才加 8 位 SHA-256；冲突检查留给 catalog Task。

**测试：**

- 合法/缺省配置；未知字段、非法类型/ID/cwd/pass_env、Server 超限。
- 项目目录同名 MCP 文件不读取。
- workspace shadow executable、相对 PATH、symlink/junction 逃逸均不被裸命令解析。
- 绝对 workspace command 只有显式配置时接受。
- `{workspace}` 仅完整 token 展开，字符串内不插值。
- 名称规范化、长度和摘要稳定。

- [ ] Step 1: 写配置与 workspace shadow 失败测试
- [ ] Step 2: 实现纯 stdlib 配置/解析和值对象
- [ ] Step 3: 运行 `python -m pytest tests/test_mcp_runtime.py -q`
- [ ] Step 4: 运行 `git diff --check`
- [ ] Step 5: 仅提交本 Task 文件：`git commit -m "feat: validate stdio MCP configuration"`

---

### Task 3：官方 SDK discovery 与同 task 生命周期

**Files：**

- Modify: `pyproject.toml`
- Modify: `src/agent/mcp_runtime.py`
- Modify: `tests/test_mcp_runtime.py`
- Create: `tests/fixtures/mcp_stdio_server.py`

**最小改动：**

1. 增加 `mcp>=1.28.1,<2` 与项目直接使用的 `jsonschema>=4.20,<5`；不安装 `[cli]` extra，不新增 lockfile 工具。
2. 若当前 Python 环境缺依赖，先在 `D:\CodexScratch` 建临时 venv/cache 做安装与测试；不得默认改 C 盘解释器。
3. `McpStdioRuntime` 首次 `discover_tools()` 才创建一个 async loop thread；每台 Server 一个长驻 owner task 和命令队列，由同一 task enter/initialize/list/exit SDK context。
4. initialize 后检查 tools capability；分页 `tools/list` 到 `nextCursor` 为空，拒绝重复 cursor；全部 Server 成功后才原子发布 tuple。
5. notification handler 只把 Server 标记 dirty；下一次 discover 通过 owner queue 刷新，当前 run 快照不变。
6. 子进程使用已解析绝对 command、受控 cwd、SDK 安全默认环境 + 显式 `pass_env`；stdout 只给协议，stderr 持续 drain 到有界尾部。
7. `close()` 幂等：取消 owner、在 owner 自己的 `finally` 退出 contexts、完成所有 pending future、停止线程。任何 discovery 失败都关闭已启动 Server，不返回部分结果。
8. fixture 使用官方 SDK 提供最小 echo/list Server；不手写 JSON-RPC，不联网。

**测试：**

- 真实 initialize/capability/list/分页/dirty refresh/close。
- 无 tools capability、重复 cursor、初始化 timeout、Server 崩溃均明确失败且模型未被调用。
- context 在同一 owner task enter/exit；正常、异常、KeyboardInterrupt 模拟后无残留进程。
- `pass_env` 只包含显式值，SDK 默认环境保留，其他 workspace secret 不继承。
- Windows wrapper 由 SDK 启动并清理子进程树。

- [ ] Step 1: 在非 C 盘环境确认依赖可解析
- [ ] Step 2: 写真实 fixture discovery 失败测试
- [ ] Step 3: 实现 owner task、分页、dirty 与 close
- [ ] Step 4: 运行 `python -m pytest tests/test_mcp_runtime.py -q`
- [ ] Step 5: 运行 `python -m pytest -q` 验证依赖升级未破坏全仓
- [ ] Step 6: 运行 `git diff --check`
- [ ] Step 7: 仅提交本 Task 文件：`git commit -m "feat: discover stdio MCP tools"`

---

### Task 4：MCP call、结果规整、timeout 与精确脱敏

**Files：**

- Modify: `src/agent/mcp_runtime.py`
- Modify: `tests/test_mcp_runtime.py`
- Modify: `tests/fixtures/mcp_stdio_server.py`

**最小改动：**

1. 实现同步 `call_tool(target, arguments)`，只接受 discovery route table 中的 target；同 Server 走 owner queue 串行，不同 Server owner 可并发。
2. queue wait 和 request timeout 分开：queue 超时标记 command canceled，owner 必须丢弃；request 已开始后超时才关闭 session 并标 failed。
3. `isError`、timeout、transport/protocol/process failure 分别规整成 `tool_error|timeout|failed`，不把 SDK 类型抛给 core；当前 Runtime 不自动重启/重放。
4. 规整 text、structured content、resource metadata、embedded text；image/audio/blob 只留 MIME/大小/`omitted=true`，丢弃 `_meta` 与 base64。
5. 在 Adapter 内先把所有非空 `pass_env` 值递归替换为 `[REDACTED]`，再返回有界 summary/data/diagnostic；diagnostic 最大 4 KiB。
6. failed Server 在当前 run 后续调用中快速失败且调用计数不增加；新 run 的 discovery 明确要求重启。`isError=true` 不污染健康 session。

**测试：**

- success、`isError`、结构化内容、资源、未知 block、二进制省略。
- pass_env 值出现在 text、nested structured data、stderr/error 时均不泄漏。
- queue timeout 调用计数 0 且不杀正在执行的请求；request timeout 关闭 Server。
- 同 Server 串行、不同 Server 可推进；close 时 pending/active future 都结束。
- transport failure 不重试，failed Server 快速失败，业务 `isError` 后仍可再次调用。

- [ ] Step 1: 写结果/timeout/secret 失败测试
- [ ] Step 2: 实现最小 call 与结果规整
- [ ] Step 3: 运行 `python -m pytest tests/test_mcp_runtime.py -q`
- [ ] Step 4: 运行 `git diff --check`
- [ ] Step 5: 仅提交本 Task 文件：`git commit -m "feat: call stdio MCP tools safely"`

---

### Task 5：统一 Tool Catalog、动态参数校验与 policy 分类

**Files：**

- Modify: `src/agent/core/tool_catalog.py`
- Modify: `src/agent/core/tool_schemas.py`
- Modify: `src/agent/core/actions.py`
- Modify: `src/agent/policy/approvals.py`
- Test: `tests/core/test_tool_schemas.py`
- Test: `tests/core/test_actions_parse.py`
- Test: `tests/test_approvals.py`
- Test: `tests/test_web.py`

**最小改动：**

1. 在现有 `tool_catalog.py` 增加冻结的 `ToolDefinition`/`ToolCatalog`，并把已有 description、risk、dry-run 信息收口到这里；`approvals.py` 改为消费 resolved risk，未知仍拒绝。
2. 保留内置 Pydantic validator；MCP 使用预编译 Draft 2020-12 validator。input/output schema 必须是 object，拒绝未知 dialect 与非 fragment `$ref`/`$dynamicRef`，不安装远程 retrieval。
3. 校验每 Tool 64 KiB、总 schema 512 KiB、总 MCP Tool 64、公开名/规范化冲突及内置冲突；description 只做 1,000 字符有标记截断。
4. `parse_model_action(..., tool_catalog=None)` 默认仍走内置定义；传 catalog 时统一 resolve/validate。用 `TYPE_CHECKING` + 函数内局部默认 import 避免 `actions ↔ tool_catalog` runtime cycle；`tool_catalog.py` 不再反向导入 approvals。
5. `tool_schemas.py` 从 catalog 派生 native payload，同时保留 Provider smoke 仍在使用的 `build_tool_schemas(["done"])` 位置参数契约，以及 `native_tool_names`/`ACTION_DESCRIPTIONS` 的兼容导出；spec 禁止为此修改 Provider。
6. 保留 `list_tool_infos()`；`agent tools list` 与 `/api/tools` 仍只展示内置 Tool，不为展示启动 Server。

**测试：**

- 纯内置名称/schema/risk/dry-run/web_search 过滤与当前行为一致。
- 动态名称、合法 args、缺字段/多字段/类型错误、未知 Tool。
- input/output schema dialect/ref/预算、名称冲突全部 fail closed，validator 不联网。
- MCP risk 永远 confirmation-required；read-only/never 拒绝，annotations 无法降权。
- 静态 CLI/Web Tool 列表不触发 discovery。

- [ ] Step 1: 写 catalog/schema/policy 失败测试
- [ ] Step 2: 深化现有 catalog，删除重复事实源
- [ ] Step 3: 接 actions/tool_schemas/approvals，保持默认参数兼容
- [ ] Step 4: 运行 `python -m pytest tests/core/test_tool_schemas.py tests/core/test_actions_parse.py tests/test_approvals.py tests/test_web.py -q`
- [ ] Step 5: 运行 `git diff --check`
- [ ] Step 6: 仅提交本 Task 文件：`git commit -m "refactor: unify runtime tool catalog"`

---

### Task 6：run loop 动态注册与现有安全链接线

**Files：**

- Modify: `src/agent/core/loop.py`
- Modify: `src/agent/builtin_skills/code-dev/SKILL.md`
- Create: `tests/core/test_loop_mcp.py`
- Test: `tests/core/test_loop_core.py`
- Test: `tests/core/test_loop_native.py`
- Test: `tests/test_skills.py`

**最小改动：**

1. `run_once(..., mcp_runtime=None)` 开始时取 MCP snapshot，与内置定义合并后冻结一次 catalog；未注入时不读配置、不启动线程。
2. native payload 与 JSON-in-text 协议消息都从同一 catalog 派生；JSON fallback 包含有界 MCP description/input schema 与“不可信元数据”规则。
3. action parse、`SUPPORTED_TOOL_ACTIONS` 判断、policy、trace 都改为消费同一个 resolved definition；内置 executor 分派保持原代码。
4. `_tool_observation` 保持现有顺序：policy → Skill → dry-run → approval；最后仅按 `source` 选择内置 executor 或 `mcp_runtime.call_tool()`。
5. MCP Result 映射现有 Observation/ErrorCode；成功 data 写 `source/server_id/remote_tool`，错误进入现有 recovery/error budget。
6. Skill 支持精确公开名和保留项 `mcp:*`；默认 `code-dev` 加 wildcard，`doc-research` 不加；空 allowlist 保持现有“不限制”语义。
7. TraceRecord 增 `tool_source/server_id/remote_name`，配置只记录 Server ID/协商版本；不记录 command、args、cwd、pass_env 或 stderr。

**测试：**

- Fake Runtime：native 与 JSON fallback 都选择同一 MCP Tool。
- 参数错误发生在 hook/policy/approval/call 前；拒绝、dry-run、never、read-only、Skill deny、approval timeout 的 call count 均为 0。
- 批准后恰好调用一次；事件顺序和 before/after hook 不变。
- exact allow、`mcp:*`、空 allowlist、doc-research deny。
- success/`isError`/queue timeout/request timeout/transport failure 映射、恢复循环和 failed fast。
- observation 实时脱敏、预算、feedback、trace 均无 secret；内置 Tool 回归全绿。

- [ ] Step 1: 用最小 Fake Runtime 写端到端失败测试
- [ ] Step 2: 接 catalog 到 JSON/native/parse/policy
- [ ] Step 3: 只在执行链末端接 MCP Result
- [ ] Step 4: 接 Skill wildcard 与 trace 元数据
- [ ] Step 5: 运行 `python -m pytest tests/core/test_loop_mcp.py tests/core/test_loop_core.py tests/core/test_loop_native.py tests/test_skills.py -q`
- [ ] Step 6: 运行 `git diff --check`
- [ ] Step 7: 仅提交本 Task 文件：`git commit -m "feat: register MCP tools in the agent loop"`

---

### Task 7：CLI、ChatSession 与 Workbench 生命周期所有权

**Files：**

- Modify: `src/agent/core/chat.py`
- Modify: `src/agent/cli.py`
- Modify: `src/agent/web/chat_runtime.py`
- Modify: `src/agent/web/chats.py`
- Modify: `src/agent/web/server.py`
- Test: `tests/test_chat.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_web.py`

**最小改动：**

1. `ChatSession` 增可选借用 `mcp_runtime`，`run_turn` 原样传给 `run_once`；ConversationState/session JSON 不保存 Runtime 或 MCP 配置。
2. `agent run` 每次命令创建一次，唯一 `finally` 关闭；`agent chat` 在 REPL 外创建并跨 turn 复用，`/exit`、EOF、Ctrl+C、异常都关闭一次。
3. `serve_workbench` 创建并拥有一个 Runtime，注入 `ChatRuntime` 和兼容 `/api/chat/turn` 路径；即使 handler 创建或 HTTP bind 失败也必须 close。正常 finally 固定先 `server_close()`，再关闭 Runtime。
4. `ChatRuntime` 只借用，公共方法仍是 `start/poll/decide`；不增加公开 close，不改变 SSE/approval/HTTP payload。
5. 无 MCP 配置时 Runtime 保持惰性，不创建 async thread；配置/initialize 失败在模型调用前变成现有 CLI 错误或 Workbench job `error` 终态。

**测试：**

- CLI run 成功/Provider 异常/run 异常/Ctrl+C 各 close 一次。
- CLI chat 多 turn 只启动一次，所有退出路径 close。
- Workbench 多 job 与 `/api/chat/turn` 共用 Runtime；handler URL/payload characterization 不变。
- Workbench 正常、KeyboardInterrupt、handler/bind 失败都 close；active/pending MCP future 全部结束，无 worker 永久等待、无遗留进程，且关闭顺序可断言。
- ChatRuntime 公共 Interface 测试仍只允许 `start/poll/decide`。

- [ ] Step 1: 写 ownership/close 失败测试
- [ ] Step 2: 接 ChatSession 与 CLI 组合根
- [ ] Step 3: 接 Workbench 两条 chat 路径
- [ ] Step 4: 运行 `python -m pytest tests/test_chat.py tests/test_cli.py tests/test_web.py -q`
- [ ] Step 5: 运行 `git diff --check`
- [ ] Step 6: 仅提交本 Task 文件：`git commit -m "feat: own MCP lifecycle at app boundaries"`

---

### Task 8：用户文档、状态与最终验收

**Files：**

- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap-progress.md`
- Modify: `docs/superpowers/specs/2026-07-17-stdio-mcp-dynamic-tools-design.md`
- Test: `tests/test_docs.py`

**最小改动：**

1. README 给出 `~/.agent/mcp.toml` 的 `command/args/pass_env/cwd` 示例、`{workspace}` 语义和公开名称规则。
2. 明确两次信任：全局配置授权启动拥有 OS 权限的进程；每次 Tool call 仍需 approval。read-only/dry-run/never 可能 discovery，但不发 `tools/call`。
3. 明确 secret 只走 `pass_env`，不能放 command/args；项目配置不加载；`cwd=workspace` 的 import/config 风险；`agent tools list` 只列内置 Tool。
4. CHANGELOG/roadmap 只记录实际完成项；最终才把 spec 状态改为“已实施”，未通过真实门禁前保持“已批准，实施中”。
5. 不增加 MCP UI、doctor 命令或未来功能占位。

**自动门禁：**

```powershell
python -m pytest tests/test_mcp_runtime.py tests/core/test_loop_mcp.py -q
python -m pytest -q
git diff --check
python -m agent.cli doctor
python -m agent.cli release doctor --cwd .
```

**真实门禁：**

1. 本地 fixture 真实完成 SDK initialize → 分页 list → call → close，无网络、无残留进程。
2. 真实 Provider 分别跑 `native_tools=true` 与 JSON fallback，各完成一次 MCP Tool approval/call/result。
3. 真实 Workbench 跑“选择 MCP Tool → approval → 流式 observation → trace”，关闭后确认进程树消失。
4. 若第 2、3 步需要创建/修改 Windows 用户目录的 `~/.agent/mcp.toml`，先停下询问用户：说明 `C:\Users\admin\.agent\mcp.toml`、预计不足 2 KiB、可用 `D:\CodexScratch\agent-mcp-acceptance\home` 临时 home 替代（但不能证明默认用户路径）、验收后恢复或删除；未获许可不得写。

- [ ] Step 1: 写 README 安全契约失败测试
- [ ] Step 2: 更新 README/CHANGELOG/roadmap，spec 暂标“实施中”
- [ ] Step 3: 跑 focused 与全量自动门禁
- [ ] Step 4: 先取得真实 C 盘配置许可，再做 Provider/Workbench 门禁
- [ ] Step 5: 门禁全部通过后把 spec/roadmap 改为完成并再跑 `git diff --check`
- [ ] Step 6: 仅提交本 Task 文件：`git commit -m "docs: document stdio MCP tools"`

Expected：MCP 与内置 Tool 共用一个 catalog 和安全链；默认配置无进程副作用；危险路径 fail closed；自动与真实 CLI/Workbench 路径都有证据；本期范围外能力没有空壳。
