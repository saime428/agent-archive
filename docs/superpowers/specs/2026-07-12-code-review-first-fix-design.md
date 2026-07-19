# 设计：代码审查 5.5 首轮修复

日期：2026-07-12
状态：已确认，待实施
依据：`docs/code-review-2026-07-12.md` 5.5
计划：`docs/superpowers/plans/2026-07-12-code-review-first-fix.md`
主范围：5.5 的四项实现顺序
附带范围：2.4 多 `tool_calls` 的可见丢弃护栏

## 背景

代码审查 5.5 给出的“第一刀”不是一个大功能，而是四个直接影响日常使用的语义修复：

1. native observation 回喂继续要求原生工具调用；
2. `approval=never` 变成名实相符的无交互、fail-closed 模式；
3. JSON 协议提示列出完整支持动作；
4. Workbench 审批等待超时后默认拒绝。

这四项分别属于提示协议、审批策略、工具目录和 Web job 生命周期，应该在各自已有 seam 内修复，不新增总控模块。用户另行提出的多 `tool_calls` 告警成本低、没有执行语义变化，作为同批护栏交付；真正多工具执行继续后置。

## 目标

- native 与 JSON 两条协议都给模型一致、真实的下一步指令；
- `approval=never` 不再触发审批，确认类动作直接拒绝；
- Workbench 不再因无人审批永久占用后台线程；
- 多工具响应被截断时留下可审计诊断；
- 保持改动局部、无新依赖、无新配置层。

## 核心决策

### 1. `approval=never` 固定为无交互、fail-closed

沿用 `2026-06-06-agent-core-design.md` 的既有安全契约，不采用 auto-allow：

- `CONFIRMATION_REQUIRED_ACTIONS` 直接返回 `deny`，不调用 approval handler；
- `read-only` deny 仍先执行，保留更具体的原因；
- 未知动作仍 deny；
- `run_command` 不进入 shell，因此现有 `python -c` 高能力路径不会被零提示放行；
- project config 仍禁止设置 `approval=never`；
- CLI/global config 可以启用；Workbench 只读展示该值，不允许浏览器写入 `never`。

这使 `never` 与 `risky-confirm` 明确区分：前者永不询问并拒绝确认类动作，后者在有 handler 时允许用户决定。只需修正一个 policy 分支，不扩张到 2.5 shell 收紧。

### 2. 不新建统一诊断或提示框架

- 协议文案继续由 `loop.py` 现有构建函数负责；
- 工具名复用 `tool_schemas.native_tool_names`；
- 审批决策留在 `policy/approvals.py`；
- 审批超时留在 Web chat job 的 condition wait；
- 多调用检测留在实际丢弃调用的 provider adapter，告警写入现有 action trace 并由运行详情展示。

## 切片 1：修正 native observation 回喂

### 当前问题

`_action_protocol_message(native=True)` 与 native repair 已要求“Call exactly one tool”，但 `_build_observation_feedback_message` 无协议参数，工具执行后的下一轮仍要求 JSON action。日常 native 多轮因此收到互相矛盾的 system/user 指令。

### 设计

给 `_build_observation_feedback_message` 增加关键字参数：

```python
def _build_observation_feedback_message(
    action: InternalAction,
    observation: Observation,
    context: RunContext,
    *,
    native: bool = False,
) -> dict[str, str]:
```

唯一调用点传入 `native=use_native`。反馈正文、错误 guidance、untrusted 标记和 observation JSON 全部不动，只切换最后一句：

- native：`Call exactly one tool. Continue with another allowed tool if needed, or call done if the task is complete.`
- JSON：保留现有 `Return exactly one valid JSON action object...`。

同时把 auto mode 的 `may use multiple tool calls` 改为 `may use multiple sequential actions across turns`，避免同一 system prompt 一边要求单调用、一边鼓励并行调用。

不抽取新的 prompt builder；现有 repair 与 observation 文案用途不同，强行共用只会增加接口。

### 测试

- 扩展 `test_native_error_recovery_still_works`：feedback 含 `Call exactly one tool`，不含 `JSON action object`；
- 扩展 auto mode prompt 测试：含 `multiple sequential actions across turns`，不含 `may use multiple tool calls`；
- 现有 JSON observation feedback 测试继续断言 `Return exactly one valid JSON action object`。

## 切片 2：让 `approval=never` 明确 fail-closed

### 当前问题

`classify_action` 对 `never` 没有分支，确认类动作仍返回 `approval_required`。有 handler 时仍会弹审批，违反“never”与既有安全设计；无 handler 时虽 fail-closed，但原因仍声称可审批。

### 设计

保持现有决策顺序，只改 `CONFIRMATION_REQUIRED_ACTIONS` 分支：

```python
if action_name in CONFIRMATION_REQUIRED_ACTIONS:
    if config.approval == "never":
        return PolicyDecision(
            "deny",
            "Approval is disabled; confirmation-required actions are denied.",
        )
    return PolicyDecision("approval_required", "Action requires approval before execution.")
```

该分支位于 `read-only` deny、`approval=always` 和低风险动作处理之后，因此：

- `read-only + never + write_file` 仍 deny；
- `always` 仍要求所有非 terminal 动作审批；
- `never` 不调用 handler，也不进入确认类工具；
- low-risk 动作和 dry-run 顺序不变。

不改 `ApprovalMode`、配置文件格式或 project config 的降权保护。Workbench 仅在 effective config 真为 `never` 时动态插入禁用的 `never (global)` 选项，其他模式不显示这个不可选项；保存其他设置时，若该禁用值未被用户改为更严格模式，则 payload 省略 `approval`，后端继续拒绝浏览器写入 `never`。

`agent run` 与 `agent chat` 的既有 `--approval` help 直接补一句：`never denies actions that would require confirmation`。不新增文档页或帮助常量。

### 测试

- `tests/test_approvals.py`：把 `never` 的 run_command 预期改为显式 `deny`，并新增 `read-only + never + write_file` 保留 read-only reason；
- `tests/core/test_loop_core.py`：锁住 `never` 不调用 handler、返回 `POLICY_DENIED`、文件未写入和 trace reason；
- 使用 `python -c` 作为回归动作，证明确认类命令不会进入 shell；
- `tests/test_config.py` 中 project config 禁止 `never` 的测试保持不变。
- `tests/test_ui.py` 锁住全局 `never` 可展示、其他设置仍可保存、浏览器直接提交 `never` 仍被拒绝。
- `tests/test_cli.py` 锁住 run/chat help 对 `never` 的 fail-closed 说明。

## 切片 3：JSON system prompt 使用完整支持目录

### 当前问题

JSON 分支手写动作字符串，只包含读取、git 与 terminal 动作，漏掉写文件、补丁、命令和文档工具。实际 parser/loop 支持这些动作，但提示让模型以为不可用。

### 设计

删除 `_action_protocol_message` 内的手写动作列表，复用已经为 native schema 服务的真实名称来源：

```python
actions = ", ".join(
    native_tool_names(web_search_enabled=config.web_search_enabled)
)
```

提示改为明确的 `Supported actions: {actions}.`，避免在 read-only 或 skill allowlist 下误称每个动作都当前可用。`web_search_enabled=False` 时仍自动剔除 `web_search`。

不新建第三份 catalog，也不在本切片合并 `tool_catalog.py` 与 `tool_schemas.py` 的描述文本；本需求只需要真实动作名。

### 测试

- JSON system prompt 断言包含 `write_file`、`apply_patch`、`run_command`、`write_markdown_report` 和四类文档读取工具；
- web search 禁用时断言 `Supported actions` 行不包含 `web_search`，禁用提示本身仍可提到该名称；
- 增加不变量：`native_tool_names(web_search_enabled=True)` 等于 `SUPPORTED_TOOL_ACTIONS | {"done", "ask_user"}`，防止 parser/schema 与 loop 再次漂移。

## 切片 4：Workbench 审批等待超时默认拒绝

### 当前问题

chat job 的 `handle_approval` 使用无期限 `condition.wait()`。关闭页面或 SSE 断开不会结束 job，后台线程可能永久等待，`completed_at` 也永远无法设置。

### 设计

增加非配置常量 `APPROVAL_WAIT_TIMEOUT_SECONDS = CHAT_JOB_TTL_SECONDS`，并补足当前单待审批模型所需的最小状态：

1. `_ChatJob` 增加 `approval_pending: bool = False` 与 `approval_deadline: float | None = None`，现有 `approval_decision` 允许内部 sentinel `"timed_out"`；
2. `_append_chat_event` 在持有 `job.condition` 时，为 `approval_required` 原子设置 pending 与 monotonic deadline，再追加事件；
3. `build_chat_approval_payload` 仅在 pending 且尚未越过 deadline 时接受一次决定，并立即清除 pending/deadline；过期时写入 `"timed_out"` sentinel 并 notify waiter，再拒绝请求；提前或重复决定也拒绝；
4. handler 使用 job 上的 deadline 等待；超时在同一锁内清除 pending/deadline，返回内部结果 `"timed_out"`；
5. `ApprovalHandler` 保持兼容现有 bool handler，只扩为 `bool | Literal["timed_out"]`；
6. loop 对 `"timed_out"` 发出 `approval_timed_out`，继续使用非恢复性的 `APPROVAL_DENIED` code，但 message 固定为 `Approval timed out; action was not executed.`，details 写入 `approval_outcome=timed_out`；
7. job 最终仍在 finally 设置 `done`/`completed_at`，现有 TTL 清理不变。

Workbench SSE 列表和过程卡片增加 `approval_timed_out`，显示“审批超时”并禁用原审批按钮。显式拒绝仍只产生 `approval_denied`，不把超时伪装成用户决定。

### 测试

在异步 Workbench 审批测试旁增加以下用例：

- 新建但尚未 pending 的 job 拒绝提前批准；人为设置 pending 但 deadline 已过时也拒绝批准，锁住 endpoint 抢在 waiter 前取得锁的竞态；
- monkeypatch `APPROVAL_WAIT_TIMEOUT_SECONDS = 0` 后，事件包含 `approval_required`、`approval_timed_out` 和 terminal final，不含 `approval_denied`；
- 超时后再次提交批准被拒绝，目标文件不存在；
- 测试继续轮询 `build_chat_events_payload(...)["done"]` 后再断言 `done=True` 与 `completed_at`，不把 final event 当作完成屏障；
- 已有显式 approve/deny 测试继续通过；
- 静态前端测试锁住 SSE 注册、过程卡片文案与超时后按钮 resolved 状态。

## 附带护栏：多 `tool_calls` 可见丢弃

### 设计

单动作语义不变，只把静默丢弃变成 agent-owned 结构化诊断。`openai_compat.py` 定义固定文本：

```python
IGNORED_TOOL_CALLS_WARNING = (
    "[agent warning] Provider returned multiple tool calls; "
    "calls outside the current single-call path were ignored."
)
```

- 非流式：`len(tool_calls) > 1` 且第一个调用规整成功时，结果携带私有 `_agent_warning`；
- 流式：assembler 遇到 `index != 0` 只设置布尔状态，第一个调用规整成功后在 envelope 阶段携带一次；
- core 只在 native 路径提取并移除该私有标记，再按原值调用 `parse_model_action`；
- `TraceRecord` 增加可选 `warning`，成功解析的 action 写入 `tool_calls.jsonl` 的 `trace.warning`；
- 运行详情优先展示 `trace.warning`，因此重载后仍可见；
- 不修改 `action.message`，不记录额外调用名称、参数或 payload，也不新增 live SSE warning 事件。

若第一个调用本身无法解析，继续逐字返回现有 raw string 并进入可见 repair；该响应已不是“静默丢弃”，不再为它增加第二套 warning 传输协议。

### 测试

- 扩展现有同步“取第一个”测试，断言内部 warning 一次且第一个 action/message 不变；
- 扩展流式“忽略非零 index”测试，用多个参数分片证明只警告一次；
- 单调用路径断言无警告；
- 第一个调用非法时断言 raw string 与 repair 行为逐字不变；
- core 用例锁住成功路径的 `trace.warning`；
- UI 用例锁住运行详情渲染 warning，而不是模型 `action.message`。

## 实施顺序

严格按 5.5，再追加护栏：

1. native observation 与 auto 文案；
2. `approval=never` fail-closed 与 Workbench 如实展示；
3. JSON 完整支持目录与执行集合不变量；
4. Workbench 审批超时；
5. 多 `tool_calls` 结构化 trace 告警。

每个切片只修改归属模块与现有测试，完成后跑对应窄测试；全部完成后再跑全量门禁。

## 预计文件

- `src/agent/core/loop.py`
- `src/agent/cli.py`
- `src/agent/policy/approvals.py`
- `src/agent/llm/openai_compat.py`
- `src/agent/web/server.py`
- `src/agent/web/static/assets/render/health.js`
- `src/agent/web/static/assets/sse.js`
- `src/agent/web/static/assets/render/chat.js`
- `src/agent/web/static/assets/render/diagnostics.js`
- `tests/core/test_loop_native.py`
- `tests/core/test_loop_core.py`
- `tests/core/test_loop_modes.py`
- `tests/core/test_tool_schemas.py`
- `tests/test_approvals.py`
- `tests/test_cli.py`
- `tests/test_openai_compat.py`
- `tests/test_ui.py`

不预计修改 CSS、配置 schema 或新增文件。

## 验收

自动门禁：

```powershell
python -m pytest tests/core/test_loop_native.py tests/core/test_loop_core.py tests/core/test_loop_modes.py tests/core/test_tool_schemas.py tests/test_approvals.py tests/test_cli.py tests/test_openai_compat.py tests/test_ui.py -q
python -m pytest -q
node --check src/agent/web/static/assets/render/health.js
node --check src/agent/web/static/assets/sse.js
node --check src/agent/web/static/assets/render/chat.js
node --check src/agent/web/static/assets/render/diagnostics.js
git diff --check
```

真实路径检查：

- Workbench 显式批准一次写操作，确认既有审批流程不回归；
- 在 global `approval=never` 下打开 Workbench，确认设置显示该值且切换联网设置可保存；确认写操作 fail-closed 且不出现审批卡；
- 用零秒 timeout fixture 确认“审批超时”事件可见，提前与超时后的批准均被拒绝；
- 有 DeepSeek key 时运行一次 native 多轮错误恢复，确认 observation 后仍继续调用工具；
- 检查一次带多调用 fixture 的运行详情与 `tool_calls.jsonl`，确认只执行一个动作、`trace.warning` 重载后可见且无额外参数泄漏。

## 范围外

- 真正执行或排队多个 `tool_calls`；
- 批量审批、部分批准和并行动作回滚；
- 修改 sandbox、shell 硬拒绝或 project config 降权规则；
- 新增审批 timeout 配置；
- 合并两份工具描述 catalog；
- `server.py` 拆分或其他审查项；
- 2.5 `python -c` 收紧与 2.7 文档 optional extras。

## 风险与回退

- **`approval=never` 被误改回 auto-allow**：policy 与 loop 测试必须使用 `python -c` 锁住 fail-closed，Workbench 仅展示、不允许写入该值。
- **审批边界竞态**：pending/deadline 的设置、消费与超时清理都在 `job.condition` 下完成；endpoint 和 waiter 都检查同一个 deadline，测试分别覆盖提前与过期决定。
- **审批超时测试误等 300 秒**：测试只 monkeypatch `APPROVAL_WAIT_TIMEOUT_SECONDS` 为零，不使用真实 sleep，也不改变 job 清理 TTL。
- **工具目录再次漂移**：集合不变量在同一测试中比较 schema 名称与 loop 执行集合。
- **告警被模型伪造或 UI 隐藏**：仅 native adapter 可产生私有标记，core 移除后写入 `trace.warning`；模型 message 保持原样。
