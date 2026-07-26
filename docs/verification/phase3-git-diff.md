# Phase 3F Git 工作区与 Diff 验收记录

- 日期：2026-07-25
- 状态：待实施与独立验收
- 设计：[Phase 3F 设计](../superpowers/specs/2026-07-25-phase3-git-diff-design.md)
- 计划：[Phase 3F 计划](../superpowers/plans/2026-07-25-phase3-git-diff.md)

## 当前结论

尚未完成。只有只读 Interface、React 闭环、五轴审查、源码/wheel 全量、真实 Git served Workbench 与
提交后 detached 证据全部通过后，才能把本记录改为完成。

通过后下一切片为 3G Terminal；当前不得提前声明 Phase 3 或 Project vNext 核心完成。

## 待记录证据

- 最终代码 commit/tree 与 wheel SHA-256/大小；
- porcelain parser、status flags、repository root、sandbox、helper 禁用与上限；
- staged/unstaged/untracked/conflict/binary/deleted/rename/Unicode/clean/non-repo；
- Python/前端全量、真实 Git served UI、可见浏览器和控制台；
- detached 重建、wheel 闭包、temp/process/worktree 与 git 状态清理。
