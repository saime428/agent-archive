# Phase 3E 编辑器与工作区搜索验收记录

- 日期：2026-07-25
- 状态：3E Editor/Search 已完成
- 设计：[Phase 3E 设计](../superpowers/specs/2026-07-25-phase3-editor-search-design.md)
- 计划：[Phase 3E 计划](../superpowers/plans/2026-07-25-phase3-editor-search.md)

## 结论

3E Editor/Search 已完成。React Files 现在用一个懒加载 Monaco editor 管理多文件 model，并共享桌面
Monaco 与窄屏原生 textarea 的 tab/buffer/save 状态；递归搜索通过独立只读 `/api/search` 复用现有
`search_files`、WorkspaceSandbox 与错误语义。文件保存仍只走 `/api/file/save`、显式确认和 snapshot。

下一切片为 3F Git/Diff。3F–3I 与最终全链路缺陷清零仍未完成，因此本记录不构成 Phase 3 或
Project vNext 核心完成声明；Phase 4–5 仍是需求触发项。

## 实现与边界

- 普通文本、相对路径和 glob 使用确定性递归遍历；进入目录前剪枝 `.git`、`.venv`、
  `node_modules`、`dist`、`build`、`__pycache__`、`.pytest_cache` 和 `.agent/runs`。
- 单文件正文上限 1 MiB、扫描上限 10,000 文件、返回上限 50 条、excerpt 上限 200 字符；响应区分
  `truncated` 与 `scan_truncated`，UI 对未知剩余结果使用“至少”和“仅显示前 N 条”。
- 桌面端精确锁定 `monaco-editor@0.56.0`，一个 editor/多 model，保留每个标签的 buffer、baseline、
  dirty 与 view state；最多 20 个标签。小于 768px 使用原生 textarea fallback。
- dirty 标签关闭、工作台离开和 `beforeunload` 均有保护；保存失败保留 buffer/dirty。Ctrl/Cmd+S 与
  按钮共用保存确认；截断或含 replacement character 的文件保持只读。
- 未增加 React wrapper、状态库、LSP、索引、正则/批量替换、文件新建/删除、Git、Terminal 或第二条
  写入链。`dompurify` 通过 npm override 固定到 3.4.12，依赖审计为 0 漏洞。

## 测试证据

- Python 定向：backend/search/API/docs/frontend contract 共 `270 passed`；API client unit `11 passed`。
- 主工作树全量：`1145 passed in 109.36s`。
- wheel-site 隔离导入全量：`1145 passed in 115.24s`，导入路径明确来自 D 盘 wheel-site，不是仓库
  editable install。
- 最终代码提交 detached worktree 全量：`1145 passed in 119.18s`。
- frontend `npm run check`：typecheck、lint、UI policy、production build 通过；Vitest `28 passed`；
  Playwright `47 passed`、1 个 30 秒录制用例按设计 skipped。新增的永久断言确认首个桌面文件打开时
  实际发出 `editor.worker` 请求。
- served wrapper：`5 passed`、1 个 POSIX-only 用例在 Windows skipped；真实 served Workbench：
  `4 passed`，覆盖真实搜索、多标签保存/snapshot/diff、审批取消、父子进程树清理与重启恢复。
- detached `npm ci` 从锁文件安装 236 个包；完整前端检查、重新 `build:preview`、`npm audit` 后 Git
  仍 clean，证明提交中的生成资源可重现。

## 提交、包体与 wheel

- 设计提交：`1000769`；搜索后端提交：`e7840fd`；最终 runtime 提交：
  `2ea25790c0118e814e93a9bf97ea645ff365e479`，tree
  `dba444d9c060bb7da8633599e32e6fd3f957e2c8`。
- wheel：`agent-2.1.0-py3-none-any.whl`，1,295,077 bytes，SHA-256
  `e5c1364591d445f20d82130d63569814e818d21be2853d2864147f70f2ea4d8a`；30 个 preview 文件及
  `filesystem.py`、`web/files.py`、`web/server.py` 与源码逐字节一致。wheel `release doctor` 完成，
  wheel 实服 4/4 通过。
- 首屏同步 JS 为 475,094 raw / 147,922 gzip bytes；相对 3E 前 gzip 只增加 2,262 bytes，低于
  50 KiB 门。16 个 Monaco async JS/CSS/Worker/语言资源共 3,043,879 raw / 781,190 gzip bytes，
  低于 15 MiB / 5 MiB 门。wheel 相对 3D 增加 790,565 bytes。

## 可见浏览器

- wheel 启动的隔离 Workbench 扫描 3 个文件并得到 2 条真实结果；点击 `src/app.py` 跳到第 2 行，
  Monaco 加载 adapter、editor API、Python 语法和 Worker，编辑后出现 dirty 标记。
- 保存确认显示路径、58 字节、UTF-8 与 snapshot；确认后生成 run
  `run_20260726_030617_233996`。磁盘复核内容、snapshot original/metadata、tool_calls 与 summary 均存在。
- 再打开 README 得到两个独立标签。390×844 时 `monacoCount=0`、`nativeEditorCount=1`，且
  `scrollWidth=clientWidth=390`；恢复 1280×720 后 Monaco 重新出现。
- 桌面与移动截图人工检查无重叠或横向溢出；浏览器 console warning/error 为 0。

## 验收中发现并修复

1. 保存失败时确认框遮住错误反馈；失败路径现在关闭确认框，同时保留 editor buffer 与 dirty。
2. Monaco 在每次受控 `value` 回传时重复恢复旧 view state，可能让连续输入光标回跳；现在只在 model
   真正切换时保存/恢复 view state，并以标签切换后连续输入顺序回归覆盖。
3. 搜索命中超过返回上限时 UI 未显示“仅显示前 N 条”；现在明确展示结果上限并有 E2E 断言。
4. 锁文件中的 transitive `dompurify@3.4.8` 有已知漏洞；最小 override 升到 3.4.12，audit 清零。

## 清理与状态

- `D:\CodexScratch` 中 10 个本轮 `phase3e-*`/`agent-phase3e-*` 目录、detached worktree、wheel、cache、
  wheel-site、pytest 与浏览器 workspace 已按核对后的绝对路径删除；无运行后台作业，4175 无监听进程，
  Git worktree 只剩主工作树。
- 主工作树只保留两份用户原有的未跟踪 handoff 文档；未修改、未暂存。没有 push、Ready 或 merge。
- 本轮主工作树 npm 命令误用了 `C:\Users\admin\AppData\Roaming\npm-cache`：统计时段内 39 个修改
  文件共 26,760,675 bytes，其中 11 个日志共 25,761 bytes。共享内容寻址 cache 无法安全归因，未在
  无授权时删除；后续 npm 命令固定 D 盘 cache。3D 记录的约 37.1 MB C 盘 pytest 残留同样未动。

## 完成清单

- [x] 多标签、独立 buffer/view state、dirty close、离开与刷新保护
- [x] Ctrl/Cmd+S、保存成功/失败、snapshot、截断/编码只读
- [x] 文本/路径/glob/Unicode/empty/error/truncated/ignore/limit/sandbox/竞态
- [x] 桌面 Monaco/Worker、移动 textarea、主题、焦点、长路径与 overflow
- [x] 源码、wheel、detached、真实服务、可见浏览器与包体门
- [x] D 盘 temp/worktree/process 清理；C 盘遗留等待用户授权
