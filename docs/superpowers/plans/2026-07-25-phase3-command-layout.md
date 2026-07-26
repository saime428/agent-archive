# Phase 3H 命令面板与布局持久化实施计划

- 日期：2026-07-25
- 状态：已完成
- 设计：[Phase 3H 命令面板与布局持久化](../specs/2026-07-25-phase3-command-layout-design.md)

## 固定边界

- 只改 React 源码、前端测试、生成 preview 与 3H 文档；不改 Python runtime/API/config。
- 命令面板只调用已有 handler；不新增 dependency、registry、fuzzy search 或快捷键配置。
- localStorage 只保存 railOpen、railWidth、canvasEnabled、workspaceView 四项非敏感布局。
- 所有临时目录、cache、wheel、served workspace 和 detached worktree放在 `D:\CodexScratch`；两份既有
  handoff 不修改、不暂存。

## Task 1：文档与失败契约

提交 spec、plan、verification 骨架和 docs 契约。先以 layout unit 与 Playwright 断言锁定 storage 失败退化、
键盘交互、真实动作、reload 恢复、modal/focus 和窄屏边界。

## Task 2：最小布局状态

增加一个纯函数 layout helper，校验并读取/写入单一 localStorage key；App 用单一 layout state 复用现有 rail、
canvas 与 workspace handler。WorkspacePanel view 受控化，但保留 dirty Files guard。

## Task 3：最小命令面板

复用 Radix Dialog 和现有 CSS token，实现顶部按钮、Ctrl/⌘K、搜索、上下键、Enter、Escape、空态与 focus
return。只注册新建、五个工作台 view、刷新、rail 与 canvas 九个已有动作。

## Task 4：审查与真实验收

运行 layout unit、typecheck、lint、UI policy、build、Playwright 和 Python docs/静态资产契约；五轴审查确认
没有 dirty bypass、modal stack、storage crash、敏感持久化、重复业务逻辑或窄屏/focus 回归。

从最终代码提交创建 D 盘 detached worktree，重跑前后端矩阵；核对 preview/wheel 闭包、release doctor、
真实 served Workbench、可见浏览器、console、端口/进程/temp 与 Git 状态清理。

最后更新 verification、方向与 roadmap，只声明 3H 完成，下一步为 3I Legacy retirement。

## 完成门

- Ctrl/⌘K → 搜索/键盘选择 → 执行现有动作的真实闭环；
- 四项非敏感布局在 reload 后恢复，损坏或拒绝 storage 时安全回退；
- dirty guard、modal focus、320/390/1440、reduced motion 与安全边界不回归；
- 全量、真实浏览器、wheel、提交后复验和清理通过；Project vNext 核心仍保持未完成。
