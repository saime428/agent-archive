# Phase 3I Legacy retirement 验收记录

- 日期：2026-07-25
- 状态：待实施与独立验收
- 设计：[Phase 3I 设计](../superpowers/specs/2026-07-25-phase3-legacy-retirement-design.md)
- 计划：[Phase 3I 计划](../superpowers/plans/2026-07-25-phase3-legacy-retirement.md)

## 当前结论

尚未完成。只有旧壳、`/legacy/`、同步 `/api/chat/turn` 与死代码删除，现行 React/async Interface 无回归，且
源码、detached、wheel、served-wheel、package inventory、可见浏览器和清理证据全部通过后，才能改为完成。

通过后进入最终对话、生成、前端、后端、CLI、package、浏览器与缺陷清零矩阵；当前不得提前声明 Phase 3 或
Project vNext 核心完成。

## 待记录证据

- 最终代码 commit/tree 与 wheel SHA-256/大小；
- retired URL/API 404、根/preview/async chat 不变和生产引用清零；
- frontend/Python 全量、served UI、可见浏览器和控制台；
- detached 重建、源码/wheel 静态闭包、temp/process/worktree 与 Git 状态清理。
