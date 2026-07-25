# Phase 3A Lifecycle 验收记录

- 日期：2026-07-25
- 状态：实施中；尚未通过完成门
- 设计：[`2026-07-25-phase3-recoverable-task-lifecycle-design.md`](../superpowers/specs/2026-07-25-phase3-recoverable-task-lifecycle-design.md)
- 计划：[`2026-07-25-phase3-recoverable-task-lifecycle.md`](../superpowers/plans/2026-07-25-phase3-recoverable-task-lifecycle.md)

## 当前边界

3A Lifecycle 只负责任务 cancel、整轮 timeout、workspace lease、durable Run Event、服务中断终态
和不重放 Tool 的安全 resume。Memory、Automation、eval 和 Frontend 开发工作区不在本切片。

Project vNext 核心仍未完成；完成本切片后仍需 Phase 3B–3I 和最终全链路缺陷清零。Phase 4–5
继续是需求触发项，不进入当前完成门。

## 待验证

- [ ] Run control 在所有 stop 路径正常 finalize
- [ ] Windows/POSIX 子进程树 cancel/timeout 后无残留
- [ ] CLI/Web workspace lease 跨进程生效
- [ ] normal/cancelled/timed_out/interrupted/failed 各只有一个 durable terminal
- [ ] resume 只使用新 message，不重放旧 Tool
- [ ] CLI、HTTP/SSE、React、真实服务与可见浏览器通过
- [ ] Python/前端全量、wheel、提交后重建与进程/端口/temp 清理通过

## 环境例外

先前 Cutover 红灯遗留的
`C:\Users\admin\AppData\Local\Temp\pytest-of-admin\pytest-150`（约 9 KB）仍未擅自删除；本切片
所有临时文件继续定向到 `D:\CodexScratch`。
