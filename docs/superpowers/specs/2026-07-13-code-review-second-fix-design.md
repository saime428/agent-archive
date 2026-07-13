# 设计：代码审查第二刀——运行命令能力透明化

日期：2026-07-13
状态：已确认，计划已审查
依据：`docs/code-review-2026-07-12.md` 2.5
计划：`docs/superpowers/plans/2026-07-13-code-review-second-fix.md`

## 背景

`run_command` 会启动拥有 Agent 当前操作系统权限的本地进程。现有 argv 与工作区路径检查可以拦住部分明显越界输入，但不能限制进程内部继续访问文件、网络或子进程。

对抗审查还确认：单独禁止 `python -c` 不能形成可信隔离，因为默认保留的 `pytest` / `python -m pytest` 会执行项目代码，`rg` 等程序也可能提供启动其他进程的参数。继续扩展字符串黑名单只会增加摩擦，并制造“已经被限制在工作区”的错觉。

本轮不改变命令能力，只把真实能力在批准前说清楚。审批是用户确认 seam，不是进程沙箱。

## 目标

1. 所有需要审批的 `run_command` 使用一条明确、稳定的能力警告。
2. 英文原文进入 approval event、observation 与 trace，便于审计和测试。
3. CLI 在询问批准前显示该原因。
4. Workbench 在实时审批事件及兼容/历史摘要中显示固定中文映射。
5. README 明确说明：工作区路径检查和命令白名单都不构成完整进程隔离。

## 固定文案

核心英文原文：

```text
Run commands execute local processes with the agent's OS permissions; workspace path checks do not fully contain file, network, or subprocess access. Approval is required.
```

Workbench 中文映射：

```text
运行命令会以 Agent 当前的操作系统权限启动本地进程；工作区路径检查无法完整限制文件、网络或子进程访问。执行前需要你的批准。
```

测试按完整字符串锁定两者，避免安全含义被普通文案调整削弱。

## 设计

### 策略 seam

`policy/approvals.py::classify_action` 是原因产生的唯一 seam。`run_command` 在 `approval=always` 和 `risky-confirm` 两条需要审批的路径上均返回上述英文原文。

优先级保持不变：

- `sandbox=read-only` 仍直接拒绝；
- `approval=never` 仍直接拒绝 confirmation-required 动作；
- 非 `run_command` 动作继续使用现有通用审批原因。

`core/loop.py` 不翻译、不重写原因，只沿现有链路把 `decision.reason` 写入 approval event、无 handler 时的 observation 和 trace。

### 展示映射 seam

翻译只放在展示 adapter，不进入策略模块或 trace：

| 位置 | 改动 | 覆盖路径 |
| --- | --- | --- |
| `web/static/assets/render/chat.js::friendlyChatText` | 增加英文到中文的固定映射 | 浏览器展示 |
| `web/static/assets/render/chat.js::processDetail` | 对 `event.reason` 调用 `friendlyChatText` | 实时审批事件卡片 |
| `web/server.py::_friendly_observation_summary` | 增加相同映射 | 历史摘要与旧同步接口 |
| `cli.py::_chat_event_handler` | 原样打印 `event.reason` | CLI 审批前提示 |

Workbench 存在浏览器直接渲染实时事件和服务端返回兼容/历史摘要两条路径，因此 Python 与 JavaScript 各保留一条相同映射。这个最小重复是有意的：只改一处会让另一条路径泄漏英文；为一条文案新增跨语言 i18n 或生成模块则没有收益。聊天历史目前不持久化 SSE 事件列表，本轮不新增事件重放。映射规模明显增长时再单独设计集中管理。

CLI 保留英文原文，与 trace 的审计语义一致，不增加第二套终端本地化。

### 文档

README 在 `run_command` / allowlist 说明附近补充：

- 命令以 Agent 的操作系统权限启动本地进程；
- 路径检查不能完整限制进程后续的文件、网络或子进程访问；
- `allowed_commands` 是能力授权，approval 是执行确认，两者都不是 OS/容器沙箱；
- `pytest`、`python -m pytest` 和其他获准命令仍可能执行项目代码。

同时修正 Safety Model 中笼统的“文件访问受工作区限制”：该约束只适用于内置文件/文档工具及命令 argv 路径检查，不代表获准进程被限制在工作区内。

## 非目标

- 不禁止 `python -c`、`rg --pre`、pytest 或其他新命令形态。
- 不新增风险分级、第二次确认、配置项、错误码或事件类型。
- 不修改 `tools/shell.py`、`allowed_commands`、argv 路径检查或审批语义。
- 不新增 i18n 框架、doctor 检查或 OS/容器隔离。
- 不处理端点能力探测、真正并行 `tool_calls` 或其他审查项。

## 测试

- `tests/test_approvals.py`：锁定两种审批模式下 `run_command` 的精确原因；确认 read-only、never 以及其他动作语义不变。
- `tests/core/test_loop_core.py`：锁定 approval event、无 handler observation 和 trace 中的英文原因。
- `tests/test_cli.py`：确认 CLI 在批准问题前打印原因。
- `tests/test_ui.py`：锁定前后端中文映射和 `processDetail(event.reason)` 的使用。
- `tests/test_docs.py`：锁定 README 对“审批不等于隔离”的说明。

不新增测试文件，不为固定文案建立新抽象。

## 预计文件

- `src/agent/policy/approvals.py`
- `src/agent/cli.py`
- `src/agent/web/server.py`
- `src/agent/web/static/assets/render/chat.js`
- 上述对应测试
- `README.md`

## 验收

```powershell
python -m pytest tests/test_approvals.py tests/core/test_loop_core.py tests/test_cli.py tests/test_ui.py tests/test_docs.py -q
python -m pytest -q
node --check src/agent/web/static/assets/render/chat.js
python -m agent.cli doctor
git diff --check
```

真实浏览器验收一次 `run_command`：实时审批卡片同时显示中文能力警告与命令参数，批准后命令仍按原流程执行。兼容/历史摘要的中文映射由自动化测试覆盖，不虚构不存在的历史事件重放路径。
