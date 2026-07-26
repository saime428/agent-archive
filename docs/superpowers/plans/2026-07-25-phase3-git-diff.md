# Phase 3F Git 工作区与 Diff 实施计划

- 日期：2026-07-25
- 状态：执行中
- 设计：[Phase 3F Git 工作区与 Diff](../specs/2026-07-25-phase3-git-diff-design.md)

## 固定边界

- 新增一个 Web Git 模块、两条 GET route、一个 GitView、API 类型/adapter、直接测试和本切片文档。
- status 使用 porcelain v1 `-z` 独立结构化解析；diff 复用现有 `git_diff` executor、sandbox、timeout
  与 20,000 字符预算。
- 只读；不新增 dependency、Git 写命令、后台 watcher、索引或 snapshot diff 分支。
- 所有测试 basetemp、wheel、cache、真实仓库和 detached worktree 放在 `D:\CodexScratch`；两份既存
  handoff 不修改、不暂存。npm 命令显式使用 D 盘 cache。

## Task 1：文档与红灯

提交 spec、plan、verification 骨架和 docs 契约。先增加失败测试覆盖 status NUL parser、rename/copy、
状态 flags、上限、非仓库/父仓库，以及 staged/unstaged diff、删除文件、path escape 和 invalid area。

## Task 2：只读 Web Interface

新增 `agent.web.git`：验证 workspace repository root，用固定 argv 获取/解析 status；构造已有
`git_diff` InternalAction 并消费 executor observation。共享 Git diff argv 补上 `--no-ext-diff` 与
`--no-textconv`。server 只注册两个 GET route，不增加 POST。

## Task 3：最小 GitView

扩展 typed API，Workspace 增加 Git tab。GitView 显示 repository/clean/error/truncated、状态条目和
staged/unstaged 切换；untracked 明确无 diff。复用现有 button、overview tag、payload 与响应式样式，
不新增状态库或 diff 渲染依赖。

## Task 4：审查与验证

运行 Git/Web/UI 定向集和 frontend unit/typecheck/lint/UI policy/build/Playwright。五轴审查确认：path
不能 escape、父仓库不泄漏、Git config 不执行 external helper、输出有界、慢响应不覆盖、只读边界清晰。

## Task 5：提交后真实路径

从最终代码提交创建 D 盘 detached worktree：重跑 Python 全量与 frontend 全矩阵；在真实临时 Git 仓库
构造 staged+unstaged+untracked+rename/binary/deleted，验证 API、served UI、可见浏览器、wheel 字节闭包、
release doctor、`git diff --check` 和清理。

最后更新 verification、方向与 roadmap，只声明 3F 完成，下一步为 3G Terminal。

## 完成门

- status → 选文件 → staged/unstaged diff 真实闭环，非 Git/clean/untracked/超限清晰；
- Web 只读且不执行 external diff/textconv/fsmonitor，不泄漏 workspace 外路径；
- 全量、真实浏览器、wheel、提交后复验和清理通过；
- Project vNext 核心仍保持未完成。
