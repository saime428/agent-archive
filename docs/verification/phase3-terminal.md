# Phase 3G Terminal 与进程管理验收记录

- 日期：2026-07-25
- 状态：待实施与独立验收
- 设计：[Phase 3G 设计](../superpowers/specs/2026-07-25-phase3-terminal-design.md)
- 计划：[Phase 3G 计划](../superpowers/plans/2026-07-25-phase3-terminal.md)

## 当前结论

尚未完成。只有配置门、共享策略、单进程 runtime、React 闭环、五轴审查、源码/wheel 全量、真实 served
Workbench 与提交后 detached 证据全部通过后，才能把本记录改为完成。

通过后下一切片为 3H Command/Layout；当前不得提前声明 Phase 3 或 Project vNext 核心完成。

## 待记录证据

- 最终代码 commit/tree 与 wheel SHA-256/大小；
- enable、argv/cwd policy、cursor/ring、input、stop/timeout/close 与 tree cleanup；
- Python/前端全量、真实 process served UI、可见浏览器和控制台；
- detached 重建、wheel 闭包、temp/process/worktree 与 Git 状态清理。
