# 设计：Phase 3F Git 工作区与 Diff

- 日期：2026-07-25
- 状态：设计已锁定，待实施与独立验收
- 上位方向：[Phase 3 方向分析与审查](../../project-vnext-phase3-direction-review.md)

## 目标

在 React Workbench 增加一个只读 Git 视图：读取当前 workspace 根仓库的 staged、unstaged、untracked
和 conflict 状态，选择文件后查看 staged 或 unstaged unified diff。它补齐“我改了什么、准备提交什么”
的个人 coding 闭环，但不提供 stage、unstage、commit、checkout、discard、push 或仓库初始化。

本切片完成后只允许声明“3F Git/Diff 完成”；Phase 3 和 Project vNext 核心仍需 3G–3I 与最终全量
缺陷清零。

## 官方语义与本地事实

- [Git status 官方文档](https://git-scm.com/docs/git-status)说明 porcelain v1 是面向脚本、跨版本和
  用户配置稳定的格式；`-z` 使用 NUL 分隔路径，rename/copy 的路径顺序与普通短格式不同。
- [Git diff 官方文档](https://git-scm.com/docs/git-diff)明确：默认 `git diff` 比较工作树与 index，
  `git diff --cached` 比较 index 与 HEAD，且两者都可在 `--` 后用 pathspec 限定单文件。
- 当前验收环境为 `git version 2.55.0.windows.3`。实现不得依赖人类可读 `git status --short` 的引号
  或 `old -> new` 文本。

## 只读 Interface

新增两条 GET Interface，不复用 snapshot `/api/diff` 的不同语义：

```text
GET /api/git/status
GET /api/git/diff?path=<repo-relative-path>&area=staged|unstaged
```

status 成功响应固定为：

```json
{
  "git_available": true,
  "is_repository": true,
  "reason": null,
  "entries": [
    {
      "path": "src/app.py",
      "original_path": null,
      "index_status": "M",
      "worktree_status": null,
      "staged": true,
      "unstaged": false,
      "untracked": false,
      "conflicted": false
    }
  ],
  "entry_count": 1,
  "truncated": false
}
```

`reason` 只在预期状态时使用：`git_unavailable`、`not_repository`、`repository_root_outside_workspace`。
这些情况返回 200，让 UI 能稳定展示状态；命令 timeout、无法解码或异常退出才返回既有有界 JSON 400。
workspace 必须正好是 repository top-level；若它只是父仓库的子目录，不允许读取 workspace 外的 sibling
状态，提示用户改为打开仓库根。

status 使用：

```text
git -c core.fsmonitor=false status --porcelain=v1 -z --untracked-files=all --ignore-submodules=dirty
```

解析 XY 两列并保留 rename/copy 的 `original_path`。最多返回前 1,000 项，最多解析 1 MiB 原始状态；
任一上限命中后 `truncated=true`，UI 使用“至少”表述。invalid UTF-8、畸形 record 或 Git timeout 必须
显式失败，不能猜路径。状态只读，不刷新 index 以外的工作区内容。

diff 请求要求非空相对 `path` 和精确 `area`。路径继续通过 WorkspaceSandbox 限制在 workspace 内，
包括已删除文件的 non-strict resolve；命令固定追加 `--no-ext-diff --no-textconv -- <path>`，staged
再追加 `--cached`。结果沿用 `ContextBudget.git_output_chars=20,000`：

```json
{
  "path": "src/app.py",
  "area": "unstaged",
  "diff": "diff --git ...",
  "truncated": false
}
```

untracked 文件没有 Git diff，前端不发请求并明确提示去 Files 查看；binary、删除、rename、unborn HEAD
与 conflict 交给 Git 原生 diff 表达。空 diff 是合法状态，不伪造成错误。

## React 视图

- Workspace 顶部增加 Git 入口；GitView 自己管理 status/diff 的 idle/loading/empty/error/truncated，
  不塞进全局 10 秒 System refresh。
- 状态列表展示 path 和 staged/unstaged/untracked/conflict 文本 badge。选择文件后，只显示该文件实际
  可用的 staged/unstaged 切换；两者都有时默认 unstaged。
- diff 用等宽、可横向滚动的 `<pre>`，保留原始 unified diff，不做危险 HTML 高亮。payload 继续使用
  `data-payload` 边界；长路径可复制但不得撑破布局。
- Git View 是只读证据面；不出现 stage、discard、commit、push 或任何确认框。320/390/1440px、键盘
  focus、reduced motion 和现有 dirty Files 离开保护不能回归。

## 安全与性能

- 所有 Git subprocess 使用 argv、`shell=False`、固定 30 秒 timeout；diff 禁止 external diff 与
  textconv，status 禁用外部 fsmonitor，避免只读界面执行仓库配置的辅助程序。
- 不接受 ref、commit、任意 Git option 或多 path。`--` 固定隔开受 sandbox 验证的单一路径。
- status 和 diff 均有返回上限；个人工具先复用现有同步 Git 执行模型。若 30 秒仍不足，显示 timeout，
  不在本切片增加 background Git job、watcher 或索引。

## 验收

- clean、staged、unstaged、同文件双状态、untracked、rename/空格/Unicode、deleted、binary、conflict、
  unborn HEAD、非仓库、父仓库子目录、path escape、invalid area、timeout/失败与截断有测试。
- 状态选文件后 staged/unstaged diff 正确，空 diff 和 untracked 提示清晰；刷新不复用旧选择或慢响应。
- Python 定向/全量、frontend unit/lint/typecheck/build/Playwright、真实 Git served Workbench、wheel 与
  detached worktree 通过；可见浏览器控制台无 warning/error。

## 非目标

- stage/unstage、discard、commit、amend、branch、checkout、merge、rebase、stash、push/pull/fetch、
  remote、GitHub/PR、仓库初始化、文件历史、blame、图谱或 diff editor。
- Terminal、Command/Layout、legacy retirement 或 Phase 4–5 需求触发项。
