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
- 不自动重试 call。queue timeout 与 request start 用原子状态转换判定；只有 cancel 胜出才能声称未调用，已开始 request 的 timeout 必须关闭并标记 Server failed。
- async context 必须由同一个长驻 owner task enter/exit；禁止分别用 `asyncio.run()` 或多个 portal call 管生命周期。
- 首期不采集 Server stderr，使用 `os.devnull`；不增加跨平台 pipe/drain 实现。SDK 1.28.1 的 stdio 与 shared-session/root 协议校验日志都不得把原始异常或消息送入 console、event 或持久化；过滤必须限定 owner thread + SDK 来源并可恢复，不能全局吞应用日志。
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
3. `_event_action_payload` 的 `message/args` 也走现有 `redact_value`，覆盖 `action_parsed/tool_start/approval_*` 结构化 event。既有 `model_stream_chunk` 是原始 Provider 预览，本 Task 不增加跨 chunk 缓冲，也不宣称其已脱敏。
4. 用与 observations 对齐的 replacement-count 列表把实时替换数传给 `_write_run_logs`；不修改 `agent-observation-v1` 协议，不把审计元数据塞进业务 data。
5. 持久化层把实时 count 与最后一次防御性 redaction count 相加，继续正确生成每条 `redaction` 元数据和 summary 的 `redaction_applied`。
6. 内部 action args 保留执行所需原值；结构化 event/persistence 只输出脱敏副本。

**测试：**

- 敏感值在模型第二轮 messages、observation event、RunResult、Chat final 和 durable logs 中均不存在。
- 敏感值在 `action_parsed/tool_start/approval_required/approval_granted/approval_denied` 的 message/args 中均不存在；`model_stream_chunk` 的既有原始预览行为单独做 characterization，不混入此断言。
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

1. 用 stdlib `tomllib`、`dataclass`、`pathlib`、`re`、`hashlib` 实现可显式调用的用户级 `~/.agent/mcp.toml` 只读 parser；无文件返回空 Server tuple。Module import 和未来 Runtime constructor 都不得自动读取配置或启动线程/进程。
2. 实现 `McpServerConfig`、`McpToolTarget`、`McpToolDefinition`、`McpCallResult`（含 `redaction_replacements`）与 `McpRuntimeError`；不导入 approval、Run Event 或 run store。
3. 严格校验 Server ID、`command`、`args`、`pass_env`、`cwd=config|workspace`、8 Server 上限和未知字段；`PATH`/`PATHEXT` 是 Runtime 保留项，禁止出现在 `pass_env`，Windows 比较大小写不敏感；配置文件或其父目录 real path 落入 workspace 时拒绝，覆盖 symlink/junction 重定向。
4. 默认 cwd 为 `~/.agent`；只把完整 argv token `{workspace}` 替换为 workspace 绝对路径。
5. 裸 command 使用进程启动时的 PATH/PATHEXT 快照手工解析：忽略空项和相对项；每个 PATH 目录先 canonicalize，并用文件身份统一普通、`\\?\`、UNC、symlink/junction 等别名，real path 落入 workspace 的 alias 整项丢弃。快照只保留不含平台 PATH 分隔符的 canonical absolute directories；启用 Server 时若结果为空则 fail closed，不能把空 PATH 交给子进程重新解释成 cwd。候选 executable `resolve()` 后再次拒绝 workspace 目标。Windows 只保留原生 `.exe/.com`，拒绝会经命令解释器处理或不能直接 `CreateProcess` 的 `.cmd/.bat/.ps1`；脚本型 Server 必须显式配置可信解释器 executable，并把脚本路径作为 argv。不得调用会搜索 cwd 的 `shutil.which(command)`。同时返回由相同 canonical 目录与规范化扩展组成的子进程 PATH/PATHEXT 快照，后续不得重新混入原始 PATH。
6. 显式绝对 command 只做存在性/文件校验，表示用户对该精确路径的信任；相对路径拒绝。
7. 提供稳定公开名 helper：`mcp__<server>__<normalized_tool>`，超长才加 8 位 SHA-256；冲突检查留给 catalog Task。

**测试：**

- 合法/缺省配置；未知字段、非法类型/ID/cwd/pass_env、含大小写变体的保留 PATH/PATHEXT、Server 超限。
- 项目目录同名 MCP 文件不读取；用户配置文件或父目录 symlink/junction 指向 workspace 时拒绝。
- workspace shadow executable、相对 PATH、目录或 executable symlink/junction 逃逸均不被裸命令解析。
- 净化后的子进程 PATH/PATHEXT 不含 workspace、workspace venv、`node_modules/.bin` 或 real path 指向 workspace 的外部目录 alias，顺序稳定、非空且每项均为不含 PATH 分隔符的 canonical absolute path。
- 绝对 workspace command 只有显式配置时接受。
- Windows 的裸命令与显式绝对 command 都拒绝 `.cmd/.bat/.ps1`；不以 `shell=True` 绕过，脚本需显式解释器。
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

1. 增加 `mcp>=1.28.1,<2` 与 `jsonschema>=4.20,<5`；不安装 `[cli]` extra，不新增 lockfile 工具。`jsonschema` 在本 Task 已用于 discovery 边界的 schema 安全检查和 snapshot-bound validator，不是未使用依赖。
2. 在 `D:\CodexScratch` 建一次性 venv/cache，执行 `pip install -e .` 与 `pip check` 确认依赖可解析；不得默认改 C 盘解释器，验证后清理临时环境。
3. `McpStdioRuntime` constructor 只保存 workspace/config path。首次 `discover_tools()` 才读取并冻结配置、创建一个 async loop thread；每台 Server 一个长驻 owner task 和命令队列，由同一 task enter/initialize/list/exit SDK context。
4. 用一个 stdlib lock/condition 保护 `new → starting → ready/failed → closing/closed`；`ready` 保存 last-good snapshot 和可选有界 refresh error。并发首次 discovery single-flight，只创建一套 loop/owner/进程。discover 与 close 竞争时不得发布 ready。
5. initialize 后检查 tools capability；分页 `tools/list` 到 `nextCursor` 为空，拒绝重复 cursor；对 input/output schema 做 object、dialect、非 fragment ref 与单 Tool 大小安全检查，并预编译 input validator 及绑定 Target 的 output validator；全部 Server 成功后才原子发布 tuple。
6. notification handler 只把 Server 标记 dirty；下一次 discover 通过 owner queue 刷新，当前 run 快照不变。
7. 子进程使用已解析绝对 command、受控 cwd、SDK 安全默认环境，加入允许的 `pass_env` 后最后显式覆盖 Task 2 净化后的 PATH/PATHEXT；禁止重新混入原始 PATH。stdout 只给协议，Server stderr 传给 Runtime 自己打开/关闭的 `os.devnull` 文本句柄。
8. 在任何 SDK 数据离开 Adapter 前做 pass_env 精确处理：description/version/error 替换，Tool name 或 schema 命中则 discovery fail closed；声明但不存在的 pass_env 在启动前失败。owner thread 进入 SDK context 前把同一个窄 `logging.Filter` 实例装到 root logger 与 `mcp.client.stdio` logger，只有同时匹配 owner thread ID 和 MCP package source path/明确 logger 的 record 才抑制或改写，并清空 `args/exc_info/stack_info`；这覆盖畸形 stdout及 `mcp.shared.session` root logging 的无效 ServerRequest/ServerNotification。其他 record 原样通过，owner `finally` 即使初始化/关闭失败也移除 filter。
9. `close()` 幂等：取消 owner、在 owner 自己的 `finally` 退出 contexts、完成所有 pending future、停止线程。首次 discovery 任一失败都关闭已启动 Server且不返回部分结果；ready 后 refresh 的 transport/protocol/timeout 也关闭，但仅 Runtime-owned per-Tool object/dialect/ref/64 KiB 安全检查失败时保留 last-good session/旧 Target、不发布 S2，并让触发刷新及后续新 run 在模型调用前看到有界 refresh error。只有后续通知后的成功刷新或进程重启清除该错误；Catalog-owned 总预算/名称冲突不回写 Runtime 状态。
10. fixture 使用官方 SDK 提供最小 echo/list Server；不手写 JSON-RPC，不联网。

**测试：**

- 真实 initialize/capability/list/分页/dirty refresh/close。
- 无 tools capability、重复 cursor、初始化 timeout、Server 崩溃均明确失败且模型未被调用。
- 两线程并发首次 discovery 只启动一套 Server；discover/close 竞争不发布 ready、所有调用者结束。
- 首次 metadata 校验失败关闭；ready 后 refresh 的 Runtime-owned per-Tool 安全检查失败保留健康 session，S2 不发布、新 run fail closed、已开始的 S1 run 仍可调用；refresh transport failure 关闭，Catalog-owned 总预算/名称冲突单独失败。
- context 在同一 owner task enter/exit；正常、异常、KeyboardInterrupt 模拟后无残留进程。
- `pass_env` 只包含显式值，SDK 默认环境保留，其他 workspace secret 不继承；缺失变量时进程调用数 0，错误只含变量名。
- 默认 config cwd fixture 在 initialize 阶段调用 helper 时只命中净化 PATH 中的可信 canonical 目录；workspace venv、`node_modules/.bin`、指向 workspace 的外部目录 alias 与仓库 shadow 调用数均为 0；`cwd=workspace` 的启动前风险保持已声明 characterization。
- initialize/list 的 description/version/error 回显 secret 时替换；Tool name/input/output schema 回显时 fail closed，原值不离开 Adapter。
- 非 object、未知 dialect、非 fragment `$ref`/`$dynamicRef` 和单 Tool schema 超限在快照发布前失败，validator 不发起网络或文件 retrieval。
- 高流量 stderr 不阻塞且不进入 `capsys`；畸形 stdout，以及带 secret 的无效 ServerRequest/ServerNotification，都不把 ValidationError、instance 或 SDK 原始 payload 写进 `caplog`/console。owner thread 的应用日志、其他线程日志仍可见，close 后 logging filter 不残留。
- Windows wrapper 由 SDK 启动并清理子进程树。

- [ ] Step 1: 在 D 盘一次性 venv 执行 editable install 与 `pip check`
- [ ] Step 2: 写真实 fixture discovery 失败测试
- [ ] Step 3: 实现 lazy config、single-flight owner、分页、精确脱敏、日志抑制与 close
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
2. 每条 command 的状态由同一把锁保护：`queued` 只能原子转为 `running` 或 `canceled`，`running` 再转为 `finished`。queue timeout 只有把 `queued` 原子改成 `canceled` 才返回未调用；owner 只有把 `queued` 原子改成 `running` 才能发 request。timeout 发现已 `running` 时按 request timeout 关闭 session 并标 failed。
3. `isError`、timeout、transport/protocol/process failure 分别规整成 `tool_error|timeout|failed`，不把 SDK 类型抛给 core；当前 Runtime 不自动重启/重放。
4. 使用官方 `ClientSession.send_request` 与 typed `CallToolRequest`/`CallToolResult` 发起调用，不手写 JSON-RPC，并绕开 `ClientSession.call_tool()` 的可变 session output-schema cache。结果只用 Target 随发现快照绑定的预编译 output validator 校验；不匹配时只保留 stage、JSON path、validator keyword 等有界诊断，不 stringify exception/instance/schema fragment，再映射为 `failed` 并关闭 Server，原始 structured data 不离开 Adapter。
5. 规整 text、structured content、resource metadata、embedded text；image/audio/blob 只留 MIME/大小/`omitted=true`，丢弃 `_meta` 与 base64。
6. 在 Adapter 内对所有返回值和异常做最长值优先的 pass_env 精确替换，再返回有界 summary/data/diagnostic；diagnostic 最大 4 KiB，`McpCallResult.redaction_replacements` 记录精确替换次数供共享审计累加。
7. failed Server 在当前 run 后续调用中快速失败且调用计数不增加；新 run 的 discovery 明确要求重启。`isError=true` 不污染健康 session。

**测试：**

- success、`isError`、结构化内容、资源、未知 block、二进制省略。
- pass_env 值出现在 text、nested structured data、SDK error 时均不泄漏，replacement count 准确。
- barrier 精确控制 cancel-vs-start 边界：cancel 胜出调用计数 0；running 胜出按 request timeout 关闭 Server，绝不报告未调用后再产生请求。
- 同 Server 串行、不同 Server 可推进；close 时 pending/active future 都结束。
- transport failure 不重试，failed Server 快速失败，业务 `isError` 后仍可再次调用。
- output schema/结果结构错误调用数恰好 1、Server failed，原始 structured data 与 secret 不进入 result/exception/log。
- Run A 冻结 S1、Run B dirty refresh 到随后因外部 `$ref` 被拒绝的 S2 时，A 仍按 S1 validator 校验且 retrieval 次数为 0；SDK session cache 变化不影响旧 Target。

- [ ] Step 1: 写结果/output validation/timeout 线性化/secret 失败测试
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
- Test: `tests/test_cli.py`
- Test: `tests/test_ui.py`

**最小改动：**

1. 在现有 `tool_catalog.py` 增加冻结的 `ToolDefinition`/`ToolCatalog`，把 name、schema、risk、dry-run 收口到这里；`approvals.py` 改为消费 resolved definition，未知仍拒绝。
2. 保留内置 Pydantic validator；MCP input 使用 Runtime 已安全检查并预编译的 Draft 2020-12 validator。Catalog 防御性确认定义完整，并负责跨 Tool 的总 schema/model payload 预算；output validator 仍只属于 Target 的冻结 contract，不复制到 core。
3. 校验 MCP Tool 总数 64、总 schema 512 KiB、最终模型可见 MCP payload 128 KiB、公开名/规范化冲突及内置冲突；description 只做 1,000 字符有标记截断。单 Tool object/dialect/ref/64 KiB 安全检查只属于 Task 3 Runtime 边界。
4. `parse_model_action(..., tool_catalog=None)` 默认仍走内置定义；传 catalog 时统一 resolve/validate。用 `TYPE_CHECKING` + 函数内局部默认 import 避免 `actions ↔ tool_catalog` runtime cycle；`tool_catalog.py` 不再反向导入 approvals。
5. `classify_action(action, config, definition=None)` 保留现有两参数调用；默认从纯内置 catalog resolve。传入 MCP definition 时 approval reason 固定包含公开名、Server ID、原始 Tool 名和 OS 权限警告，event/trace 后续直接复用该 reason。
6. `tool_schemas.py` 从 catalog 派生 native payload，同时保留 Provider smoke 仍在使用的 `build_tool_schemas(["done"])` 位置参数契约，以及 `native_tool_names`/`ACTION_DESCRIPTIONS` 的兼容导出；spec 禁止为此修改 Provider。
7. 不强行合并当前两套含义不同的文案：`ACTION_DESCRIPTIONS` 继续作为模型侧兼容基线，`TOOL_DESCRIPTIONS` 继续作为 CLI/Web inventory copy。本切片只去重风险/schema 等行为事实，避免无 MCP 时偷偷改变提示或 UI 文案。
8. 保留 `list_tool_infos()`；`agent tools list` 与 `/api/tools` 仍只展示内置 Tool，不为展示启动 Server。`DRY_RUN_SKIPPED_TOOLS` 继续作为从纯内置 catalog 派生的兼容导出，Task 5 不破坏当前 loop import；Task 6 可停止运行时依赖但继续保留导出。

**测试：**

- 纯内置名称/schema/risk/dry-run/web_search 过滤与当前行为一致。
- 无 MCP 时 native schema 的 description 逐项保持当前 `ACTION_DESCRIPTIONS`，CLI/Web inventory description 保持当前 `TOOL_DESCRIPTIONS`。
- 动态名称、合法 args、缺字段/多字段/类型错误、未知 Tool。
- 缺失或不完整的 Runtime validator contract、跨 Tool 总 schema 预算、128 KiB model payload 和名称冲突全部 fail closed；单 Tool dialect/ref/大小由 Task 3 的 Runtime 测试覆盖，不在 Catalog 复制实现。
- MCP risk 永远 confirmation-required；reason 含完整身份与 OS 权限警告，read-only/never 拒绝，annotations 无法降权。
- 静态 CLI/Web Tool 列表不触发 discovery。

- [ ] Step 1: 写 catalog/schema/policy 失败测试
- [ ] Step 2: 深化现有 catalog，删除重复事实源
- [ ] Step 3: 接 actions/tool_schemas/approvals，保持 parse/classify/description 默认契约兼容
- [ ] Step 4: 运行 `python -m pytest tests/core/test_tool_schemas.py tests/core/test_actions_parse.py tests/test_approvals.py tests/test_cli.py::test_tools_list_outputs_v01_tools_and_policy_categories tests/test_ui.py::test_build_tools_payload_reuses_policy_categories -q`
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
2. native payload 与 JSON-in-text 协议消息都从同一 catalog 派生；JSON fallback 包含有界 MCP description/input schema 与“不可信元数据”规则。两条路径在模型调用前都验证 catalog 的 128 KiB MCP model payload 上限。
3. action parse、policy、trace 与执行判断都改为消费同一个 resolved definition；内置 executor 分派保持原代码。保留从纯内置 catalog 派生的 `SUPPORTED_TOOL_ACTIONS` 兼容导出，现有直接导入测试和库调用者不在本 Task 被破坏。
4. `_tool_observation` 保持现有顺序：policy → Skill → dry-run → approval；最后仅按 `source` 选择内置 executor 或 `mcp_runtime.call_tool()`。
5. MCP Result 映射现有 Observation/ErrorCode；成功 data 写 `source/server_id/remote_tool`，错误进入现有 recovery/error budget；`McpCallResult.redaction_replacements` 合并进 Task 1 的实时 Observation count。
6. Skill 支持精确公开名和保留项 `mcp:*`；默认 `code-dev` 加 wildcard，`doc-research` 不加；空 allowlist 保持现有“不限制”语义。
7. TraceRecord 增 `tool_source/server_id/remote_name`，配置只记录 Server ID/精确脱敏后的协商版本；approval event 与 trace 复用 catalog policy reason，不记录 MCP Server 启动 command/argv、cwd、pass_env 或 stderr。

**测试：**

- Fake Runtime：native 与 JSON fallback 都选择同一 MCP Tool。
- 128 KiB model payload 边界内两种模式可用，超限时模型调用数 0。
- 参数错误发生在 hook/policy/approval/call 前；拒绝、dry-run、never、read-only、Skill deny、approval timeout 的 call count 均为 0。
- 批准后恰好调用一次；approval reason 在 event/trace 中包含公开名、Server ID、原始 Tool 名和 OS 权限告警，事件顺序和 before/after hook 不变。
- exact allow、`mcp:*`、空 allowlist、doc-research deny。
- success/`isError`/queue timeout/request timeout/transport/output validation failure 映射、恢复循环和 failed fast。
- observation 实时脱敏、Adapter replacement count、预算、feedback、trace 均无 secret；`tool_calls.jsonl` 明确存在 `tool_source/server_id/remote_name`，现有 `action.action.args` 继续保存 Tool 调用参数的脱敏副本，但不出现 MCP Server 启动 command/argv/cwd/pass_env/stderr；内置 Tool 回归全绿。

- [ ] Step 1: 用最小 Fake Runtime 写端到端失败测试
- [ ] Step 2: 接 catalog 到 JSON/native/parse/policy
- [ ] Step 3: 只在执行链末端接 MCP Result
- [ ] Step 4: 接 Skill wildcard 与 trace 元数据
- [ ] Step 5: 运行 `python -m pytest tests/core/test_loop_mcp.py tests/core/test_loop_core.py tests/core/test_loop_native.py tests/core/test_tool_schemas.py tests/test_skills.py -q`
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
2. `agent run` 每次命令创建一次，唯一 `finally` 关闭；`agent chat` 在 REPL 外创建并跨 turn 复用，`/exit`、EOF、Ctrl+C、异常都关闭一次。config/discovery `McpRuntimeError` 映射为现有无 traceback CLI 退出 1。
3. `serve_workbench` 创建并拥有一个 Runtime，注入 `ChatRuntime` 和兼容 `/api/chat/turn` 路径；所有权覆盖 handler 创建、HTTP bind、browser timer 和 serve。关闭使用嵌套 `try/finally`：先尝试 `server_close()`，即使它失败也必须关闭 Runtime。
4. `ChatRuntime` 只借用，公共方法仍是 `start/poll/decide`；不增加公开 close。SSE event type 与 HTTP payload shape 保持不变，action/approval 既有字段只按 Task 1/5 契约做值脱敏和 reason 补全。
5. 无 MCP 配置时 Runtime 保持惰性，不创建 async thread；配置在首次 discover 才读取。配置/initialize 失败在模型调用前变成现有 CLI 错误或 Workbench job `error` 终态；同步 `/api/chat/turn` 的 config stage 返回 JSON 400，initialize/discovery 返回 JSON 502。
6. `_start_workbench` 的端口重试保持现状，但每次失败的 `serve_workbench` 必须完成 Runtime close 后才返回 OSError 并尝试下一端口。

**测试：**

- CLI run 成功/Provider 异常/run 异常/Ctrl+C 各 close 一次。
- CLI chat 多 turn 只启动一次，所有退出路径 close。
- CLI/Workbench config/discovery error 均在模型调用前返回，消息不含 SDK 类型、secret 或 traceback。
- Workbench 多 job 与 `/api/chat/turn` 共用 Runtime；后者的 config 400、discovery 502 与现有 JSON error shape 有 characterization，handler URL/payload 其余行为不变。
- Workbench 正常、KeyboardInterrupt、handler/bind/server_close 失败都 close；active/pending MCP future 全部结束、无 MCP 子进程，且关闭顺序可断言。明确不要求本 Task 取消任意 Provider 调用或 approval wait worker。
- 前一端口 bind 失败的 Runtime 已 close，CLI 才尝试下一端口。
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
- Modify: `docs/project-vnext-direction.md`
- Modify: `docs/roadmap-progress.md`
- Modify: `docs/superpowers/specs/2026-07-17-stdio-mcp-dynamic-tools-design.md`
- Test: `tests/test_docs.py`

**最小改动：**

1. README 给出 `~/.agent/mcp.toml` 的 `command/args/pass_env/cwd` 示例、`{workspace}` 语义和公开名称规则。
2. 明确两次信任：全局配置授权启动拥有 OS 权限的进程；每次 Tool call 仍需 approval。read-only/dry-run/never 可能 discovery，但不发 `tools/call`。
3. 明确 secret 只走 `pass_env`，不能放 command/args；项目配置不加载；`cwd=workspace` 的 import/config 风险；`agent tools list` 只列内置 Tool。
4. CHANGELOG/roadmap 只记录实际完成项；最终同步更新 `project-vnext-direction.md` 当前基线的“尚无 MCP runtime”和默认下一步，不让总方向继续把已完成切片写成待办。
5. 最终才把 spec 状态改为“已实施”，未通过真实门禁前保持“已批准，实施中”；在 spec 末尾追加简短证据表，记录命令、Provider/model、结果和 PID/进程树清理，不另建报告文件。
6. 不增加 MCP UI、doctor 命令或未来功能占位。

**自动门禁：**

```powershell
python -m pytest tests/test_mcp_runtime.py tests/core/test_loop_mcp.py -q
python -m pytest -q
git diff --check
python -m agent.cli doctor
python -m agent.cli release doctor --cwd .
```

另在 `D:\CodexScratch` 的一次性干净 venv/cache 执行 `pip install -e .`、`pip check` 和无 MCP 配置的 `python -m agent.cli doctor`，完成后清理；当前已安装依赖的解释器不能替代这条门禁。

**真实门禁：**

1. 本地 fixture 真实完成 SDK initialize → 分页 list → call → close，无网络、无残留进程。
2. 预检真实 Provider endpoint/model/key、联网和可能费用；需要产生费用或使用用户凭据时先取得用户确认。
3. `agent run` 在 `native_tools=true` 下完成一次 MCP approval/call/result，退出后确认 fixture PID/子进程树消失。
4. `agent chat` 在 JSON fallback 下完成至少两 turn，确认同一 Server 被复用，随后 `/exit` 并确认进程树消失。
5. 真实 Workbench 跑“选择 MCP Tool → approval → 流式 observation → trace”，关闭后确认进程树消失。
6. 第 1、3、4、5 步默认使用 `D:\CodexScratch\agent-mcp-acceptance\home` 临时 home，验收后清理。只有确实需要证明默认 Windows 用户路径时才申请创建/修改 `C:\Users\admin\.agent\mcp.toml`：说明预计不足 2 KiB、具体内容、D 盘替代方案和恢复/删除方式；未获许可不得写。

- [ ] Step 1: 写 README 安全契约失败测试
- [ ] Step 2: 更新 README/CHANGELOG/roadmap，spec 暂标“实施中”
- [ ] Step 3: 跑 focused、全量和 D 盘干净安装门禁
- [ ] Step 4: 默认用 D 盘临时 home 做 CLI run/chat 与 Workbench 真实门禁；Provider 费用或 C 盘默认路径另行获权
- [ ] Step 5: 门禁全部通过后补 spec 证据表，并把 spec/roadmap/project vNext 改为完成
- [ ] Step 6: 再跑 `git diff --check`，仅提交本 Task 文件：`git commit -m "docs: document stdio MCP tools"`

Expected：MCP 与内置 Tool 共用一个 catalog 和安全链；默认配置无进程副作用；危险路径 fail closed；自动与真实 CLI/Workbench 路径都有证据；本期范围外能力没有空壳。
