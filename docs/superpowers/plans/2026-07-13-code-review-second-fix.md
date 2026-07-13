# 计划：代码审查第二刀——运行命令能力透明化

日期：2026-07-13
状态：已审查，待执行
设计：`docs/superpowers/specs/2026-07-13-code-review-second-fix-design.md`

## 实施约束

- 不改变 `run_command`、`allowed_commands`、argv 路径检查或审批结果。
- 核心与 trace 保留固定英文；只有 Workbench 展示 adapter 映射中文。
- 不新增事件持久化、i18n 模块、配置、依赖或 CSS。
- 聊天历史不重放 SSE 事件；“历史中文”仅指服务端返回的 observation summary。

固定英文契约：

```text
Run commands execute local processes with the agent's OS permissions; workspace path checks do not fully contain file, network, or subprocess access. Approval is required.
```

固定中文映射：

```text
运行命令会以 Agent 当前的操作系统权限启动本地进程；工作区路径检查无法完整限制文件、网络或子进程访问。执行前需要你的批准。
```

执行 Task 1 前运行 `git rev-parse HEAD` 并记录为 `<implementation-base>`。后续只按各 Task 的精确文件列表暂存；现有无关未跟踪文件不得加入提交。

## Task 1：在策略 seam 产生唯一能力原因

**Files:**

- Modify: `src/agent/policy/approvals.py`
- Test: `tests/test_approvals.py`
- Test: `tests/core/test_loop_core.py`

**先写失败测试：**

1. `risky-confirm` 下的 `run_command` 返回 `approval_required` 和固定英文。
2. `approval=always` 下的 `run_command` 返回同一英文。
3. `write_file` 及 `approval=always` 下的 `list_dir` 仍返回通用原因。
4. 既有 `approval=never` 与 `sandbox=read-only` 精确拒绝原因保持不变。
5. 扩展 `test_run_once_blocks_run_command_without_approval`：无 handler 时 observation message 与持久化 `trace.policy_reason` 都是固定英文。
6. 新增一个 handler 拒绝的 `run_command` 用例：命令尝试创建 marker，断言 `approval_required` event 携带固定英文且 marker 不存在。

先运行：

```powershell
python -m pytest tests/test_approvals.py tests/core/test_loop_core.py -q
```

Expected：新增的 `run_command` 原因断言失败，现有拒绝与通用原因断言通过。

**最小实现：**

在 `classify_action` 内根据 `action_name` 计算一个局部 `approval_reason`：`run_command` 使用固定能力警告，其他动作使用现有通用原因。`approval=always` 与 confirmation-required 的最终返回复用该局部值。

不得调整现有分支顺序：terminal allow、disabled web deny、read-only deny、always approval、low-risk allow、never deny、unknown deny。`core/loop.py` 已透传 `decision.reason`，本任务只加测试，不改 loop。

**验证与提交：**

```powershell
python -m pytest tests/test_approvals.py tests/core/test_loop_core.py -q
git diff --check
git add -- src/agent/policy/approvals.py tests/test_approvals.py tests/core/test_loop_core.py
git diff --cached --check
git commit -m "fix: disclose run command capabilities"
```

## Task 2：在现有展示 adapter 显示警告

**Files:**

- Modify: `src/agent/cli.py`
- Modify: `src/agent/web/server.py`
- Modify: `src/agent/web/static/assets/render/chat.js`
- Modify: `README.md`
- Test: `tests/test_cli.py`
- Test: `tests/test_ui.py`
- Test: `tests/test_docs.py`

**先写失败测试：**

1. CLI chat 用 FakeLLM 请求一个无副作用的 `python -c "print(...)"`，以警告首句定位并断言它出现在 `approve? [y/N]` 之前，批准后 turn 正常完成；完整字符串由 policy 测试锁定，避免 Rich 自动换行造成脆弱断言。
2. 新增 legacy/no-handler 的 `run_command` 用例：命令尝试创建 marker，返回 payload 与随后 `build_chat_payload` 重载出的 `last_observation_summary` 均为固定中文，且 marker 不存在；已有通用摘要用例保持不变。
3. 现有异步审批测试增加 `reason` 字段断言，证明 server 未丢弃 core event 字段。
4. Workbench 静态契约锁定英文/中文映射，并锁定 `processDetail` 先调用 `friendlyChatText(event.reason)` 再拼接 elapsed。
5. README 契约同时锁定 allowlist 段和 Safety Model：allowlist/approval 不是进程隔离，获准命令可访问文件、网络及子进程，pytest 会执行项目代码。

先运行：

```powershell
python -m pytest tests/test_cli.py tests/test_ui.py tests/test_docs.py -q
```

Expected：CLI 尚不打印 reason，两个映射与 README 契约不存在。

**最小实现：**

1. `cli.py::_chat_event_handler` 在 `approval_required` 活动行之后，仅当 `event.reason` 非空时原样打印它；审批 handler 的 action、args 与 prompt 不变。
2. `web/server.py::_friendly_observation_summary` 在现有字典增加一条固定映射。
3. `chat.js::friendlyChatText` 增加同一映射；`processDetail` 的 reason 分支先得到映射后的局部文本，再沿用现有 elapsed 拼接。
4. README 修改命令 allowlist 段，并把 Safety Model 的笼统工作区约束收窄到内置文件/文档工具和 argv 路径检查。

不得把中文写入 policy、event 或 trace；不得增加历史事件重放、共享翻译模块、CSS 或 doctor 输出。

**验证与提交：**

```powershell
python -m pytest tests/test_cli.py tests/test_ui.py tests/test_docs.py -q
node --check src/agent/web/static/assets/render/chat.js
git diff --check
git add -- src/agent/cli.py src/agent/web/server.py src/agent/web/static/assets/render/chat.js README.md tests/test_cli.py tests/test_ui.py tests/test_docs.py
git diff --cached --check
git commit -m "fix: surface run command capability warning"
```

## Task 3：交叉审查与最终门禁

**自动门禁：**

```powershell
python -m pytest tests/test_approvals.py tests/core/test_loop_core.py tests/test_cli.py tests/test_ui.py tests/test_docs.py -q
python -m pytest -q
node --check src/agent/web/static/assets/render/chat.js
python -m agent.cli doctor
git diff --check
git diff --check <implementation-base>..HEAD
git diff --name-only <implementation-base>..HEAD
git status --short
```

**交叉审查：**

- `run_command` 在 `risky-confirm`/`always` 下使用固定警告；never/read-only 仍按原原因拒绝。
- 非命令动作的审批文案和行为未改变。
- no-handler observation、approval event 与 trace 保存同一英文原文。
- CLI 在 prompt 前显示英文；Workbench 实时卡片与兼容/历史摘要显示中文。
- README 不再暗示获准进程被工作区路径检查完整包含。
- diff 不含 `core/loop.py`、`tools/shell.py`、配置、CSS、依赖或事件持久化改动。

**真实 Workbench：**

使用已配置的 DeepSeek 发起一次无副作用的 `python -c "print('capability-warning-smoke')"`：

1. 审批仍处于 pending 时检查卡片同时显示中文能力警告与 argv；
2. 批准后同一 turn 正常完成；
3. 检查对应 `tool_calls.jsonl` 的 `trace.policy_reason` 仍为英文；
4. 没有可用 provider key 时明确记录环境阻塞，不把静态测试冒充浏览器验收。

Expected：行为与命令能力不变，只新增批准前可见警告；自动化与真实展示覆盖各自存在的路径。

## Plan 反向审查记录

按 correctness、readability、architecture、security、performance 五轴复查后，修正了三处漏洞：

- 用 marker 断言替代“看起来没有执行”，覆盖 core 拒绝与 legacy/no-handler 两条路径。
- 历史摘要测试穿过 `build_chat_turn_payload`、会话保存和 `build_chat_payload` 重载，不把私有 mapper 单测冒充端到端覆盖。
- CLI 只用首句判断输出顺序，完整安全文案仍由 policy 精确测试，避免终端宽度导致假失败。
- 最终审查以执行前记录的 implementation base 检查两个已提交差异，避免提交后空 diff 造成假审查。
- spec 状态与计划链接同步更新，不留下“待写计划”的过期元数据。

最终结论：无阻塞项。计划保持两个小型实现提交；没有新抽象、依赖、持久化或安全能力变更。
