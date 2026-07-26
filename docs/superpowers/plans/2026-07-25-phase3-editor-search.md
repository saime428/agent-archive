# Phase 3E 编辑器与工作区搜索实施计划

- 日期：2026-07-25
- 状态：已完成
- 设计：[Phase 3E 编辑器与工作区搜索](../specs/2026-07-25-phase3-editor-search-design.md)

## 固定边界

- 只修改共享文件搜索遍历、独立 Web search route、React Files 视图、一个 Monaco adapter、直接测试、
  依赖锁和本切片文档。
- 复用 `search_files`、WorkspaceSandbox、`/api/file/save`、snapshot、现有主题与 ConfirmDialog；不新增
  状态库、React Monaco wrapper、第二条写链或搜索索引。
- 所有测试 basetemp、wheel、缓存和 detached worktree 放在 `D:\CodexScratch`；两份既存未跟踪
  handoff 不修改、不暂存。

## Task 1：文档与红灯

提交 spec、plan、verification 骨架和 docs 契约。先增加失败测试覆盖：

- search route/query encoding、sandbox、glob/text/Unicode、忽略目录、文件/扫描/结果上限与文件竞态；
- 多标签 buffer、dirty close、保存成功/失败、只读、搜索跳转、重复响应顺序和 Ctrl/Cmd+S；
- 窄屏 textarea fallback、长路径、empty/loading/error/truncated、焦点与无横向溢出。

## Task 2：共享搜索与 Web Interface

把现有 `search_files` 的 `rglob + read_bytes` 改为剪枝、按文件有界的确定性遍历，保留现有 Tool payload
兼容并补充 scan 计数。`build_search_payload` 只构造已有 action/context/sandbox 并消费 executor 结果；
server 注册一个 GET route，frontend client 增加一个类型化方法。

## Task 3：最小 Monaco 多标签

精确安装 `monaco-editor@0.56.0`。新增一个懒加载 adapter，负责一个 editor、多 model、Worker、主题、
view state、jump、Ctrl/Cmd+S 和完整 dispose。FilesView 只管理 tabs/buffers/search/save/confirm；窄屏走
原生 textarea，共享同一 props 和状态。

## Task 4：审查与验证

运行 Python Web/UI/Tool 定向集，frontend unit/typecheck/lint/UI policy/build/Playwright。五轴审查确认：搜索
路径与资源有界、保存安全链未分叉、dirty 数据不静默丢失、异步结果无竞态、键盘/窄屏可用、Monaco
不进入首屏同步 chunk。

## Task 5：提交后真实路径

从最终代码提交创建 D 盘 detached worktree：重跑 Python 全量与 frontend 全矩阵；用真实 served Workbench
完成搜索、三标签、跳转、dirty close、保存 snapshot、刷新保护和移动 fallback；构建 wheel 后比较静态
资源字节，验证隔离安装、包体、Worker 请求、release doctor、`git diff --check` 和清理。

最后更新 verification、方向与 roadmap，只声明 3E 完成，下一步为 3F Git/Diff。

## 完成门

- 多标签、搜索跳转、保存/关闭保护真实闭环，snapshot 与 sandbox 不回归；
- 搜索、Monaco model/Worker 和输出均满足固定上限，无静默脏数据丢失；
- 全量、真实浏览器、wheel、提交后复验和清理通过；
- Project vNext 核心仍保持未完成。
