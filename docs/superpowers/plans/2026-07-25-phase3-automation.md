# Phase 3C 可审计 Automation 实施计划

- 日期：2026-07-25
- 状态：计划已审查；待实施
- 设计：[Phase 3C 可审计 Automation](../specs/2026-07-25-phase3-automation-design.md)

## 固定边界

- 只修改 RunControl cancel probe、Automation core/store/worker、CLI、直接测试与文档。
- 不新增依赖、数据库、Web route/UI、系统服务、Task Scheduler、approval bypass 或 config schema。
- 所有临时 workspace、并发 helper、wheel 与 detached worktree 放在 `D:\CodexScratch`；两份未跟踪
  handoff 不修改、不暂存。

## Task 1：文档与红灯

提交 spec、plan、verification 骨架和 docs 契约。新增 `tests/test_automation.py` 与 CLI 红测，覆盖：

- add 默认 disabled，enable 立即 due，latest-slot 计算与重复/并发 claim；
- definition revision、disable、attempt transition、cancel marker、崩溃恢复与异常通知；
- corrupt/duplicate slot/link/超限/atomic failure；
- worker 成功、workspace busy、无人值守审批拒绝、流式取消和 runtime close；
- CLI add/list/history/enable/worker/attempts/notifications/cancel。

## Task 2：RunControl 外部 cancel seam

给既有 `RunControl` 增加可选 `cancel_probe`；`stop_reason()` 先检查进程内 Event，再调用 probe，true 时
复用 `request_cancel()`。probe 异常不得误批准或执行 Tool，由 Automation 提供安全的 bounded probe。
原有 CLI/Web 行为与构造方式不变。

## Task 3：最小 AutomationStore

新增 `src/agent/core/automation.py`：

- dataclass、严格 record validation、current revision/state 计算；
- definitions/attempts 全量有界 JSONL 原子发布；
- add/enable/disable/history、due slot、claim、running/terminal、cancel marker、recovery；
- 独立 worker lock 与共享 root store lock；
- 异常终态 record 兼作 notification event。

只扫描两个有界本地日志；不建立 repository/interface/factory 层。

## Task 4：AutomationWorker

同一 Module 内增加 worker composition：执行时读取 secrets/config，复用 LLM factory、MCP runtime、
`WorkspaceRunLease`、`RunControl.with_timeout()` 与 `run_once`。不传 approval handler；所有退出路径关闭
runtime 并只写一个终态。`run_once()` 与 `run_forever()` 共用执行 helper。

## Task 5：CLI

注册 `automation` Typer 子命令，输出稳定单行、非 Rich 折行；worker 安装临时 SIGINT/SIGTERM stop
handler 并在 finally 恢复。`--once` 无 due 返回 0，有任一异常终态返回 1。

## Task 6：验证、审查与提交

按 RunControl、Automation core、CLI/docs 分拆精确提交；执行目标测试、相关 runtime/lease/loop 测试和
全量 Python。五轴审查确认：单 slot 单 attempt、单 terminal、无 approval bypass、无 worker/store lock
互锁、cancel 可到达运行核心、所有日志有界脱敏。

## Task 7：提交后真实路径

从最终代码提交创建 D 盘 detached worktree：

- 重跑目标与全量 Python；
- 真实 CLI add → enable → worker `--once` → attempts/history；重复 worker 不重跑；
- 构造失败/取消并验证 notifications、disable 后无新 claim；
- 构建 wheel，比较 Automation/RunControl/CLI 与 React runtime 路径和逐字节内容，并从 wheel 重跑 CLI；
- `release doctor`、`git diff --check`、worktree/temp/process/lock owner 清理。

最后更新 verification、方向与 roadmap，只声明 3C 完成，下一步为 3D Eval。

## 完成门

- 定义/attempt/cancel/恢复原子、并发和幂等测试通过；
- 同一 runtime、安全链和 workspace lease 得到真实证据，无审批自动批准；
- 全量、真实 CLI、wheel、提交后复验和清理通过；
- Project vNext 核心仍保持未完成。
