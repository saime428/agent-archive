# 代码审查 5.5 首轮修复实现计划

> **For agentic workers:** 严格按 Task 顺序执行。每个行为任务先写失败测试，再做最小实现、focused verification 和独立提交；不要顺手处理范围外审查项。

**Goal:** 完成审查 5.5 的四项首轮修复，并附带多 `tool_calls` 可见丢弃护栏，使 native/JSON 协议、审批语义和 Workbench job 生命周期名实一致。

**Architecture:** 提示协议修改集中在 `core/loop.py`；`approval=never` 沿用既有 fail-closed 安全契约；Workbench 审批只增加单 pending 状态和 timeout 结果；多调用由 `llm/openai_compat.py` 标记并写入现有 trace。工具名称复用 `tool_schemas.native_tool_names`，只补必要的静态前端展示，不新增总控模块、配置层或依赖。

**Spec:** `docs/superpowers/specs/2026-07-12-code-review-first-fix-design.md`

## Global Constraints

- 实施顺序固定：native feedback/auto 文案 → `approval=never` → JSON 支持目录 → Workbench 审批超时 → 多调用 trace 告警。
- `approval=never` 对确认类动作 fail-closed，不调用 handler，不进入 shell；`read-only` deny 仍优先。
- project config 和 Workbench 仍不能写入 `approval=never`；Workbench 必须如实展示 global 值，并允许保存其他设置。
- 真正多工具执行、批量审批和通用审批状态机均不做；当前只支持一个 pending action。
- 不新增依赖、不改 CSS、不拆 `server.py`。
- 每个任务只 stage 明列文件；不得加入现有无关未跟踪文件。
- 每个任务提交前运行 focused tests 与 `git diff --check`。
- 全部任务完成后必须跑全量 pytest 和真实 Workbench 路径检查。

---

### Task 0：冻结已确认设计与计划

**Files:**
- Add: `docs/superpowers/specs/2026-07-12-code-review-first-fix-design.md`
- Add: `docs/superpowers/plans/2026-07-12-code-review-first-fix.md`

**步骤：**

- [ ] Step 1：确认 spec 状态为“已确认，待实施”，且互相引用路径正确。
- [ ] Step 2：运行 `git diff --cached --check`。
- [ ] Step 3：确认 cached diff 只有上述两个文档。
- [ ] Step 4：提交设计文档：

```powershell
git -c core.autocrlf=input commit -m "docs: plan first code review fixes"
```

Expected：实现开始前 index 干净，后续代码提交不会误带设计文档。

---

### Task 1：对齐 native observation feedback

**Files:**
- Modify: `src/agent/core/loop.py:351`
- Modify: `src/agent/core/loop.py:753`
- Modify: `src/agent/core/loop.py:946`
- Test: `tests/core/test_loop_native.py:78`
- Test: `tests/core/test_loop_modes.py:51`
- Verify existing: `tests/core/test_loop_core.py:653`

**先写失败测试：**

在 `test_native_error_recovery_still_works` 的 observation feedback 断言中增加：

```python
assert "Call exactly one tool" in feedback
assert "JSON action object" not in feedback
```

扩展 auto mode prompt 测试：

```python
assert "multiple sequential actions across turns" in system
assert "may use multiple tool calls" not in system
```

先运行：

```powershell
python -m pytest tests/core/test_loop_native.py::test_native_error_recovery_still_works -q
```

Expected：当前实现因 feedback 仍要求 JSON、auto 文案仍含歧义而失败。

**最小实现：**

1. `_build_observation_feedback_message` 增加 keyword-only `native: bool = False`。
2. 唯一调用点改为：

```python
messages.append(
    _build_observation_feedback_message(
        action,
        observation,
        context,
        native=use_native,
    )
)
```

3. 只切换 feedback 最后一段：

```python
next_action_instruction = (
    "Call exactly one tool. Continue with another allowed tool if needed, "
    "or call done if the task is complete."
    if native
    else (
        "Return exactly one valid JSON action object. Continue with another allowed action if needed, "
        "or return done with a concise final answer if the task is complete."
    )
)
```

4. `_mode_instruction("auto")` 仅把 `multiple tool calls` 改为 `multiple sequential actions across turns`。
5. observation JSON、untrusted 标记、错误 guidance 和截断逻辑不改；不抽取新 prompt helper。

**验证：**

- [ ] Step 1：运行失败测试并确认先红。
- [ ] Step 2：实现参数与条件文案。
- [ ] Step 3：运行：

```powershell
python -m pytest tests/core/test_loop_native.py tests/core/test_loop_core.py tests/core/test_loop_modes.py -q
git diff --check
```

- [ ] Step 4：仅提交本任务文件：

```powershell
git add -- src/agent/core/loop.py tests/core/test_loop_native.py tests/core/test_loop_modes.py
git -c core.autocrlf=input commit -m "fix: align native observation feedback"
```

Expected：native 多轮只收到单工具调用指令，auto 只允许跨轮顺序动作，JSON feedback 逐字保持既有语义。

---

### Task 2：让 `approval=never` 明确 fail-closed

**Files:**
- Modify: `src/agent/cli.py:139`
- Modify: `src/agent/cli.py:258`
- Modify: `src/agent/policy/approvals.py:38`
- Modify: `src/agent/web/static/assets/render/health.js:35`
- Test: `tests/test_approvals.py:44`
- Test: `tests/core/test_loop_core.py:1394`
- Test: `tests/test_cli.py`
- Test: `tests/test_ui.py:223`
- Verify existing: `tests/test_config.py:109`

**先写失败测试：**

1. 将 `test_run_command_requires_approval_when_approval_never` 重命名为 `test_run_command_is_denied_when_approval_never`，预期 `decision.status == "deny"` 和 reason 为 `Approval is disabled; confirmation-required actions are denied.`。
2. 新增 policy 用例：`AgentConfig(approval="never", sandbox="read-only")` 下 `write_file` 仍为 `deny`，且保留 read-only reason。
3. loop 用 `[sys.executable, "-c", "from pathlib import Path; Path('escaped.txt').write_text('x')"]` 作为动作并传入会抛错的 approval handler；断言 handler 未调用、observation 为 `POLICY_DENIED`、trace policy 为 `deny`，`escaped.txt` 不存在。
4. Workbench 静态测试断言只有 effective config 为 `never` 时才动态插入禁用的 `never (global)`；`buildSettingsPayload` 仅在值不是 `never` 时加入 approval。
5. 既有后端测试继续断言浏览器直接提交 `approval=never` 被拒绝。
6. CLI help 测试断言 `agent run --help` 与 `agent chat --help` 都说明 `never denies actions that would require confirmation`。

先运行：

```powershell
python -m pytest tests/test_approvals.py tests/core/test_loop_core.py tests/test_cli.py tests/test_ui.py -q
```

Expected：当前 policy 仍返回 `approval_required`，Workbench 也无法展示 global `never`，新增断言失败。

**最小实现：**

只修改确认类动作分支：

```python
if action_name in CONFIRMATION_REQUIRED_ACTIONS:
    if config.approval == "never":
        return PolicyDecision(
            "deny",
            "Approval is disabled; confirmation-required actions are denied.",
        )
    return PolicyDecision("approval_required", "Action requires approval before execution.")
```

不得移动或弱化以下既有分支：terminal allow、disabled web deny、`read-only` deny、`approval=always`、low-risk allow、unknown deny。不要修改 shell policy；`never` 下确认类命令不会到达 shell。

Workbench 只在 `health.js` 做两处原生改动：

1. `renderSettings` 仅在 effective config 为 `never` 时动态插入并选中禁用的 `never (global)`，配置变回其他值时移除该临时 option；
2. `buildSettingsPayload` 先构造现有 payload，仅当 select 值不是 `never` 时添加 `approval`。用户改选 `risky-confirm`/`always` 时仍正常写入更严格的 project override。

`run` 与 `chat` 的两个现有 Typer option help 直接改为 `Approval mode; never denies actions that would require confirmation.`，不抽取只使用两次的帮助常量。

**验证：**

- [ ] Step 1：写 policy 与 loop 失败测试。
- [ ] Step 2：实现一个 `never` 分支。
- [ ] Step 3：运行：

```powershell
python -m pytest tests/test_approvals.py tests/core/test_loop_core.py tests/test_config.py tests/test_cli.py tests/test_ui.py -q
node --check src/agent/web/static/assets/render/health.js
git diff --check
```

- [ ] Step 4：检查 diff 不含 `config.py`、shell policy 或浏览器后端降权规则修改。
- [ ] Step 5：仅提交本任务文件：

```powershell
git add -- src/agent/cli.py src/agent/policy/approvals.py src/agent/web/static/assets/render/health.js tests/test_approvals.py tests/core/test_loop_core.py tests/test_cli.py tests/test_ui.py
git -c core.autocrlf=input commit -m "fix: make approval never fail closed"
```

Expected：显式 `never` 永不询问并拒绝确认类动作；Workbench 如实显示 global 值，保存其他设置不回归。

---

### Task 3：让 JSON system prompt 列出完整支持动作

**Files:**
- Modify: `src/agent/core/loop.py:881`
- Test: `tests/core/test_loop_core.py:941`
- Test: `tests/core/test_tool_schemas.py:12`

**先写失败测试：**

扩展 `test_action_protocol_prompts_real_web_search_and_file_read_tools`，断言 system prompt 的 `Supported actions` 段包含：

```text
write_file
apply_patch
run_command
write_markdown_report
read_pdf
read_docx
read_xlsx
read_pptx
```

另加一个 `web_search_enabled=False` 用例：只截取 `Supported actions: ... .` 段并断言其中没有 `web_search`；不要对整段 system prompt 做否定断言，因为禁用说明仍会提到该名称。

在 `tests/core/test_tool_schemas.py` 增加执行集合不变量：

```python
assert set(native_tool_names(web_search_enabled=True)) == SUPPORTED_TOOL_ACTIONS | {"done", "ask_user"}
```

先运行：

```powershell
python -m pytest tests/core/test_loop_core.py::test_action_protocol_prompts_real_web_search_and_file_read_tools -q
```

Expected：当前手写列表缺少写入、命令和文档动作，测试失败。

**最小实现：**

删除硬编码动作字符串，复用已导入的名称来源：

```python
actions = ", ".join(
    native_tool_names(web_search_enabled=config.web_search_enabled)
)
```

将提示中的 `Use available actions such as ...` 改为 `Supported actions: {actions}.`。不修改 `tool_schemas.py`，不合并两份 description catalog。

**验证：**

- [ ] Step 1：写完整目录、web disabled 与执行集合不变量失败测试。
- [ ] Step 2：替换硬编码列表。
- [ ] Step 3：运行：

```powershell
python -m pytest tests/core/test_loop_core.py tests/core/test_tool_schemas.py -q
git diff --check
```

- [ ] Step 4：仅提交本任务文件：

```powershell
git add -- src/agent/core/loop.py tests/core/test_loop_core.py tests/core/test_tool_schemas.py
git -c core.autocrlf=input commit -m "fix: list all JSON protocol actions"
```

Expected：JSON/native 使用同一动作名称来源，名称集合与 loop 执行集合一致；禁用的 web 工具不会出现在支持动作列表中。

---

### Task 4：给 Workbench 审批等待增加超时

**Files:**
- Modify: `src/agent/core/loop.py:71`
- Modify: `src/agent/core/loop.py:657`
- Modify: `src/agent/web/server.py:38`
- Modify: `src/agent/web/server.py:42`
- Modify: `src/agent/web/server.py:957`
- Modify: `src/agent/web/server.py:1075`
- Modify: `src/agent/web/server.py:1121`
- Modify: `src/agent/web/static/assets/sse.js:4`
- Modify: `src/agent/web/static/assets/render/chat.js:539`
- Test: `tests/core/test_loop_core.py`
- Test: `tests/test_ui.py:1159`

**先写失败测试：**

1. core 用例让 approval handler 返回 `"timed_out"`：断言事件含 `approval_timed_out`、不含 `approval_denied`；observation code 仍为 `APPROVAL_DENIED`，message 与 `approval_outcome` 如实记录超时。
2. 直接创建但不启动的 chat job，调用审批 API，断言“没有 pending approval”；再在锁内设置 pending 与已过 deadline，断言过期批准同样被拒绝。测试在 `finally` 中从 `_CHAT_JOBS` 移除该 job。
3. 在异步用例中 monkeypatch `APPROVAL_WAIT_TIMEOUT_SECONDS = 0.0`，启动先请求 `write_file` 的 job，不提交决定。
4. 等待 `approval_required`、`approval_timed_out`、`final`；再轮询 `build_chat_events_payload(...)["done"]`，不要把 final 当作完成屏障。
5. 超时后调用审批 API 必须被拒绝；目标文件不存在，job 的 `done=True` 且 `completed_at` 非空。
6. 静态前端断言 SSE 注册 `approval_timed_out`，过程卡片将其显示为错误态“审批超时”，并把对应审批按钮标为 resolved。

Expected：常量尚不存在，当前无期限 wait 无法自行结束。

**最小实现：**

1. core 保持 bool handler 兼容，只增加一个内部 timeout 值：

```python
ApprovalHandler = Callable[[InternalAction], bool | Literal["timed_out"]]
```

在 `_tool_observation` 中，`True`/`False` 保持现有 granted/denied；`"timed_out"` 发出 `approval_timed_out`，返回 `APPROVAL_DENIED`，message 为 `Approval timed out; action was not executed.`，details 增加 `approval_outcome="timed_out"`。

2. server 常量与 job 增加：

```python
APPROVAL_WAIT_TIMEOUT_SECONDS = CHAT_JOB_TTL_SECONDS

approval_pending: bool = False
approval_deadline: float | None = None
```

`approval_decision` 的内部类型扩为 `bool | Literal["timed_out"] | None`。

3. `_append_chat_event` 在 `job.condition` 内处理 `approval_required` 时原子设置 pending 与 `time.monotonic() + APPROVAL_WAIT_TIMEOUT_SECONDS`，再追加事件。审批 API 必须同时检查 pending 与 deadline；接受决定时清除 pending/deadline，发现过期时还要写入 `"timed_out"` sentinel，再 notify waiter 并拒绝请求。

4. `handle_approval` 使用 monotonic deadline：

```python
with job.condition:
    while job.approval_decision is None and job.approval_pending and not job.done:
        deadline = job.approval_deadline
        remaining = (deadline - time.monotonic()) if deadline is not None else 0.0
        if remaining <= 0:
            job.approval_pending = False
            job.approval_deadline = None
            return "timed_out"
        job.condition.wait(remaining)
    decision = job.approval_decision
    job.approval_decision = None
    job.approval_deadline = None
    return "timed_out" if decision in {None, "timed_out"} else decision
```

5. SSE 事件名列表增加 `approval_timed_out`；过程卡的 resolved/status/title 与 `liveTurnText` 增加该值。不新增 CSS。

**验证：**

- [ ] Step 1：写 core outcome、提前批准、超时、过期批准和前端静态失败测试，确保没有真实 sleep。
- [ ] Step 2：实现最小 pending 状态、deadline loop 与 timeout 分支。
- [ ] Step 3：运行：

```powershell
python -m pytest tests/core/test_loop_core.py tests/test_ui.py -q
node --check src/agent/web/static/assets/sse.js
node --check src/agent/web/static/assets/render/chat.js
git diff --check
```

- [ ] Step 4：确认已有显式 approve/deny 用例仍通过，final 后继续轮询 done。
- [ ] Step 5：仅提交本任务文件：

```powershell
git add -- src/agent/core/loop.py src/agent/web/server.py src/agent/web/static/assets/sse.js src/agent/web/static/assets/render/chat.js tests/core/test_loop_core.py tests/test_ui.py
git -c core.autocrlf=input commit -m "fix: time out workbench approvals"
```

Expected：无人决策最多等待 300 秒并产生真实 timeout 记录；提前、重复和过期决定均拒绝，job cleanup TTL 不受影响。

---

### Task 5：记录被忽略的多 `tool_calls`

**Files:**
- Modify: `src/agent/core/loop.py:59`
- Modify: `src/agent/core/loop.py:172`
- Modify: `src/agent/core/loop.py:977`
- Modify: `src/agent/llm/openai_compat.py:511`
- Modify: `src/agent/llm/openai_compat.py:534`
- Modify: `src/agent/web/static/assets/render/diagnostics.js:49`
- Test: `tests/test_openai_compat.py:140`
- Test: `tests/test_openai_compat.py:246`
- Test: `tests/core/test_loop_native.py:108`
- Test: `tests/test_ui.py:399`

**先写失败测试：**

1. 同步多调用测试：第一个 action/message 不变，规整信封只含一次私有 `_agent_warning`。
2. 流式忽略测试：让 `index=1` 跨两个参数分片，最终只含一次 warning，index 0 action 不变。
3. 单调用测试：没有 `_agent_warning`，message 逐字不变。
4. 新增“第一个参数 JSON 非法且还有第二个调用”：返回值与现有单调用非法 raw string 逐字相同，repair 行为不变；该路径已经显式报 parse error，不增加第二套 warning 传输。
5. core 成功用例：native 路径提取并移除内部标记，`action.message`/原始 parse 行为不变，`tool_calls.jsonl` 的 `trace.warning` 保留固定文本。
6. UI 静态用例：运行详情优先展示 `trace.warning`，同时保留 observation summary。

先运行：

```powershell
python -m pytest tests/test_openai_compat.py tests/core/test_loop_native.py -q
```

Expected：当前实现继续静默忽略，告警断言失败。

**最小实现：**

1. 模块级常量：

```python
IGNORED_TOOL_CALLS_WARNING = (
    "[agent warning] Provider returned multiple tool calls; "
    "calls outside the current single-call path were ignored."
)
```

2. `_envelope_from_tool_message` 增加 keyword-only `ignored_extra_tool_calls: bool = False`。有效告警条件为该参数或 `len(tool_calls) > 1`。
3. 合法 dict 信封增加私有 `_agent_warning`；不修改 `message`。第一个调用参数非法时继续逐字返回现有 raw string。
4. `_ToolCallAssembler.__init__` 增加布尔状态；`feed` 遇到合法 dict 且 `index != 0` 时只置位并 continue，不保存名称/参数；`envelope` 把状态传给共用规整函数。
5. `TraceRecord` 增加末尾默认字段 `warning: str | None = None`。
6. `run_once` 仅在 `use_native` 且 raw response 为 dict 时，在解析 action 前复制并 pop 私有 key；清理后的 dict 继续走原 parser。
7. 成功与 blocking hook trace 传入本轮 warning；`_write_run_logs` 写入 `trace.warning`。parse-error 路径保持现状。
8. `renderToolCalls` 将 warning 与既有 summary 一起显示。警告不 yield 为 stream chunk，不新增 live SSE event。

不记录额外调用的名称、参数或 payload，不修改 action.message、工具执行语义或公开 action schema。

**验证：**

- [ ] Step 1：写同步、流式、非法参数与 trace 失败测试。
- [ ] Step 2：实现常量、私有参数和 assembler 布尔状态。
- [ ] Step 3：运行：

```powershell
python -m pytest tests/test_openai_compat.py tests/core/test_loop_native.py tests/test_ui.py -q
node --check src/agent/web/static/assets/render/diagnostics.js
git diff --check
```

- [ ] Step 4：仅提交本任务文件：

```powershell
git add -- src/agent/core/loop.py src/agent/llm/openai_compat.py src/agent/web/static/assets/render/diagnostics.js tests/test_openai_compat.py tests/core/test_loop_native.py tests/test_ui.py
git -c core.autocrlf=input commit -m "fix: trace ignored native tool calls"
```

Expected：额外调用仍不执行；成功解析的同步/流式响应有一次 agent-owned、重载后可见且无敏感参数的 trace 诊断，既有 repair 路径逐字不变。

---

### Task 6：交叉审查与最终门禁

**Files:**
- No code changes expected
- Review: Tasks 1-5 的全部提交

**自动门禁：**

- [ ] Step 1：运行 focused gate：

```powershell
python -m pytest tests/core/test_loop_native.py tests/core/test_loop_core.py tests/core/test_loop_modes.py tests/core/test_tool_schemas.py tests/test_approvals.py tests/test_cli.py tests/test_openai_compat.py tests/test_ui.py -q
```

- [ ] Step 2：运行全量门禁：

```powershell
python -m pytest -q
node --check src/agent/web/static/assets/render/health.js
node --check src/agent/web/static/assets/sse.js
node --check src/agent/web/static/assets/render/chat.js
node --check src/agent/web/static/assets/render/diagnostics.js
git diff --check
python -m agent.cli doctor
```

- [ ] Step 3：运行 `git status --short`，确认没有任务文件遗漏，且无关未跟踪文件未进入提交。

**交叉审查：**

- [ ] native observation feedback 不再包含 JSON 指令；auto 文案只允许跨轮顺序动作；JSON 路径仍包含 JSON 指令。
- [ ] `approval=never` 对确认类动作返回 deny，不调用 handler，不进入 shell；read-only reason 仍优先。
- [ ] run/chat 的 `--approval` help 明确说明 `never` 会拒绝需确认动作。
- [ ] Workbench 能展示 global `never` 并保存其他设置，浏览器仍不能写入 `never`。
- [ ] JSON action 列表来自 `native_tool_names`，文案为 Supported，集合与 loop 执行集合一致。
- [ ] approval pending/deadline 在同一 condition 下设置/消费/过期；endpoint 与 waiter 检查同一 deadline，提前、重复、超时后决定均拒绝。
- [ ] timeout 使用 monotonic deadline，事件与持久化 message 明确为超时，不伪装成用户拒绝；cleanup TTL 不变。
- [ ] 多调用 warning 每个成功模型响应最多一次，写入 `trace.warning`，action.message 不变且不记录额外调用参数。
- [ ] 没有新增依赖、配置键、CSS 或 speculative abstraction。

**真实路径检查：**

- [ ] Workbench 发起一次需审批写操作，显式批准后同一 turn 正常完成。
- [ ] global `approval=never` 下发起写操作：无审批卡、动作 fail-closed；切换联网设置仍保存成功。
- [ ] 自动化零秒 timeout 显示“审批超时”，已证明提前与过期批准被拒绝；人工不等待真实 300 秒。
- [ ] 若环境已有 DeepSeek key，运行一次 native 多轮错误恢复，确认 observation 后继续调用工具；没有 key 时记录为环境跳过，不伪造通过。
- [ ] 检查多调用 fixture 的运行详情与 `tool_calls.jsonl`：只有一个 action，`trace.warning` 重载后可见，message 不变且无额外参数。

Expected：全量测试全绿；真实 Workbench 审批无回归；五个修复均能从测试、事件或持久化 trace 中观察到。
