# Phase 3C Automation 验收记录

- 日期：2026-07-25
- 状态：3C Automation 已完成并通过完成门；Phase 3 与 Project vNext 核心仍未完成
- 设计：[`2026-07-25-phase3-automation-design.md`](../superpowers/specs/2026-07-25-phase3-automation-design.md)
- 计划：[`2026-07-25-phase3-automation.md`](../superpowers/plans/2026-07-25-phase3-automation.md)

## 完成边界

3C 只完成显式前台 local worker、固定间隔 schedule、幂等 attempt、取消/恢复与异常通知。
Web/React 管理面、系统服务、cron、retry 和无人值守高风险审批不在本切片。

Project vNext 核心仍未完成；后续仍需 Phase 3D–3I 和最终全链路缺陷清零。Phase 4–5
继续是需求触发项。

## 实现结果

- `.agent/automations/definitions.jsonl` 与 `attempts.jsonl` 保存 append-only revision/transition；
  cancel 使用单 attempt 原子 marker，store 和 worker 使用不同 OS 文件锁。
- add 默认 disabled；enable 以当前 UTC 为 anchor 并立即 due；每轮只 claim 最新到期 slot，幂等键为
  `automation_id + scheduled_for`，同一 automation 有未终结 attempt 时不再 claim。
- worker 复用 workspace secrets/config、Provider factory、MCP runtime、`WorkspaceRunLease`、
  `RunControl` 与 `run_once`；不提供 approval handler，高风险动作继续以 `APPROVAL_REQUIRED` 失败。
- attempt 采用 claimed → running → succeeded/failed/cancelled/timed_out 状态链；下次独占 worker
  把崩溃残留收口为 interrupted，所有异常终态同时作为 durable local notification。
- CLI 提供 add/list/history/enable/disable/worker/attempts/notifications/cancel；固定状态行直接写出并把
  task/error 规整为有界单行，不安装服务、Task Scheduler 或 cron。

## 自动化证据

- 最终 Automation/CLI 定向：`14 passed, 106 deselected in 4.03s`。
- Automation、CLI、RunControl、loop 与 shell 相关集：`277 passed in 23.28s`；`compileall` 与
  `git diff --check` 通过。
- 修复后工作树全量：`1130 passed in 112.78s`；封板文档树复跑：`1130 passed in 117.45s`。
- 最终代码提交 D 盘 detached worktree 全量：`1130 passed in 111.06s`。
- `agent release doctor --cwd <detached-worktree>`：`release readiness: complete`；detached Git
  状态无改动。

## 提交、wheel 与真实 CLI

- 最终代码提交：`46ee33994d49bdbb8ec7d055f95b47a5374040cc`。
- tree：`027fca9d5af460b0df275147c603758a01ffeee7`。
- wheel：`agent-2.1.0-py3-none-any.whl`，500,249 bytes，SHA-256
  `a8501f32b5246bee96fc0ae0adddf34b5c7c4ef912521db8e566e5cd6210dd51`；
  `core/automation.py`、`core/run_control.py`、`cli.py` 与 14 个 React runtime 文件均与 detached
  源码逐字节一致。
- wheel import 路径确认来自隔离 `wheel-site`。真实 CLI 完成 add → enable → worker 成功，第二次
  worker 为 `attempts: 0`；显式缺失 Skill 写 failed/notification 并退出 1；运行 attempt 接受 cancel
  marker，重启 worker 恢复为 cancelled；disable 后再次 worker 不 claim。

## 验收中发现并修复

1. 显式 `--skill` 缺失曾被 core 的通用 Skill 降级路径吞掉并错误记为成功；worker 现在执行前用生产
   loader 预检，失败写唯一终态和通知。
2. 超过 2000 字符的 Provider/MCP/runtime 异常曾在写失败记录时再次报错，使 attempt 留在 running；
   终态写入现在统一先脱敏、再带截断标记限制长度。
3. summary 路径只做单行校验，不能证明属于对应 run；现在 run id 固定为 `run_auto_<uuid>`，summary
   只能是 `.agent/runs/<run-id>/summary.md`。
4. 多行 task/error 会破坏 CLI 一条记录一行的审计格式；现复用既有有界文本 helper 规整输出，并有
   精确回归断言。

## 清理与状态

- `D:\CodexScratch\agent-phase3c-46ee339` 与早期
  `D:\CodexScratch\agent-phase3c-smoke-5863948` 的 worktree、wheel、cache、wheel-site 与真实 CLI
  workspace 已按核对后的绝对路径删除；Git worktree 只剩主工作树。
- 首次 pip 隔离构建短暂采用 C 盘临时目录
  `C:\Users\admin\AppData\Local\Temp\pip-ephem-wheel-cache-iuis5uxs`；pip 已自动清理且只读复核为
  不存在。最终有效构建先验证 `tempfile.gettempdir()` 位于 D 盘，再使用 D 盘 `TMPDIR/TMP/TEMP`。
- 两份用户原有的未跟踪 handoff 文档未修改、未暂存；没有 push、Ready 或 merge。
- 未新增依赖、数据库、Web/API 管理面、系统服务、cron、retry 或 approval bypass。

## 完成门

- [x] 定义 revision、enable/disable 与 latest due slot 正确
- [x] 并发/重复 claim 只有一个 attempt
- [x] worker 复用 run lifecycle、workspace lease、MCP/config/secrets 与安全链
- [x] cancel、timeout、failure、crash recovery 与 notification 只有一个终态
- [x] 畸形、超限、link/reparse、路径约束与原子发布失败安全
- [x] 目标、全量、真实 CLI、wheel 与提交后复验通过
- [x] D 盘 temp/worktree/worker lock/process 清理通过

下一切片是 3D Eval；本记录不构成 Phase 3 或 Project vNext 核心完成声明。
