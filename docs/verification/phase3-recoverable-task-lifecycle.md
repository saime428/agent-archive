# Phase 3A Lifecycle 验收记录

- 日期：2026-07-25
- 状态：3A Lifecycle 已完成并通过完成门；Phase 3 与 Project vNext 核心仍未完成
- 设计：[`2026-07-25-phase3-recoverable-task-lifecycle-design.md`](../superpowers/specs/2026-07-25-phase3-recoverable-task-lifecycle-design.md)
- 计划：[`2026-07-25-phase3-recoverable-task-lifecycle.md`](../superpowers/plans/2026-07-25-phase3-recoverable-task-lifecycle.md)

## 当前边界

3A Lifecycle 只负责任务 cancel、整轮 timeout、workspace lease、durable Run Event、服务中断终态
和不重放 Tool 的安全 resume。Memory、Automation、eval 和 Frontend 开发工作区不在本切片。

Project vNext 核心仍未完成；完成本切片后仍需 Phase 3B–3I 和最终全链路缺陷清零。Phase 4–5
继续是需求触发项，不进入当前完成门。

## 完成门

- [x] Run control 在所有 stop 路径正常 finalize
- [x] Windows/POSIX 子进程树 cancel/timeout 后无残留
- [x] CLI/Web workspace lease 跨进程生效
- [x] normal/cancelled/timed_out/interrupted/failed 各只有一个 durable terminal
- [x] resume 只使用新 message，不重放旧 Tool
- [x] CLI、HTTP/SSE、React、真实服务与可见浏览器通过
- [x] Python/前端全量、wheel、提交后重建与进程/端口/temp 清理通过

## 实现结果

- `RunControl` 统一 cancel/deadline 原因；`WorkspaceRunLease` 让 CLI、同步 HTTP 和异步 Web
  job 共用单 workspace OS 占用。
- loop 无论 normal、cancel、timeout 或异常都进入既有 finalize；Windows/POSIX
  `run_command` 终止整个受控进程树。
- `.agent/chat-jobs` 原子持久化 job metadata、递增事件、active pointer 与终态；服务重启把
  未完成 job 收口为 `interrupted`。
- HTTP 提供 start/cancel/resume 与 cursor SSE；CLI 支持整轮 timeout 和 Ctrl+C 当前回合取消。
- React 提供可访问的停止按钮、异常终态、刷新后同 job 恢复与新消息安全 resume；旧 Tool
  永不自动重放。

## 最终提交复验

- 代码提交：`6bf4301d3a0ad287a0b2366b514282ed76109cf4`。
- tree：`af0bc2a9bae2f7b68a76c5589457f999bb32e3e8`。
- D 盘 detached worktree Python：`1104 passed in 109.91s`。
- 前端：typecheck、lint、UI policy、production build 通过；Vitest `27 passed`；Playwright
  `43 passed`，1 个 30 秒性能录制用例按设计 skipped。
- served wrapper：`5 passed`，1 个 POSIX-only 用例在 Windows skipped。
- 源码实服：默认 React、审批中 cancel、Python 父子进程树终止、服务重启后 interrupted 与
  新消息 resume 共 `4 passed`。
- wheel：`agent-2.1.0-py3-none-any.whl`，488,434 bytes，SHA-256
  `e004528097d212db232419fb3dac5da45325d3ee1fd360eff18737f8c5047e94`；10 个本切片
  Python module 与 14 个 preview 文件路径/字节一致；wheel 实服同组 `4 passed`。
- `agent release doctor --cwd .`、`git diff --check` 通过。

## 可见浏览器

- 真实 Workbench 完成 approval 等待 → 停止 → cancelled 历史 → 刷新保留 → 新消息 resume →
  normal final；无重复 start。
- Runs 中取消运行显示 `error / attention`，Summary、Task Review 与 Replay 均明确
  `Run cancelled.`；被阻止的写入文件不存在。
- 两次可见验收的 console warning/error 均为空；浏览器标签、服务与 4173–4181 相关监听已清理。

## 复验中修复的缺陷

1. SSE 第二次断线后会永久关闭：改为带 cursor 的持续有界退避重连，durable terminal 才 settle。
2. active-job 刷新测试在 start 尚未写入 hash/sessionStorage 前 reload：增加真实就绪同步点，
   并行重复 10 次通过。
3. detached served 测试硬编码 worktree `.venv`：增加 `AGENT_TEST_PYTHON` 测试 seam，默认路径不变。
4. 生成 preview JS 的第三方 template literal 含纯空白行：仅在生成资产范围关闭
   `blank-at-eol` 检查，bundle 字节不改。

## 清理

- `D:\CodexScratch` 中本轮 `agent-phase3a-*` worktree、wheel、Playwright、workspace、home 与
  temp 已精确删除；FastCtx 无运行 job，相关端口无 LISTENING。
- 两份无关未跟踪 handoff 文档未读取、未修改、未暂存。

## 环境例外

14:06 HST 只读核查时，旧 `pytest-150` 已不存在；本轮没有删除它。现有
`C:\Users\admin\AppData\Local\Temp\pytest-of-admin\pytest-156`、`pytest-157`、`pytest-158`
各约 4.8 MB，修改时间为 12:08–12:25 HST，早于本轮复验，内容属于 DreamLoop 测试；另有
`pytest-current` 链接。本轮未创建、修改或删除这些 C 盘路径。

## 后续边界

Project vNext 核心仍未完成；下一切片是 3B Memory。Phase 4–5 继续是需求触发项，不进入当前
完成门。阶段 0–3 全部完成后，仍须执行用户要求的最终对话、生成、前端、后端/API、CLI、打包与
真实浏览器缺陷清零矩阵。
