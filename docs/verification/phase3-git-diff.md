# Phase 3F Git 工作区与 Diff 验收记录

- 日期：2026-07-25
- 状态：3F Git/Diff 已完成
- 设计：[Phase 3F 设计](../superpowers/specs/2026-07-25-phase3-git-diff-design.md)
- 计划：[Phase 3F 计划](../superpowers/plans/2026-07-25-phase3-git-diff.md)

## 结论

3F Git/Diff 已完成。Workbench 通过独立只读 Interface 展示当前仓库的 staged、unstaged 与 untracked
状态，并按文件读取 staged/unstaged diff；没有新增 commit、push、stage 或文件写入路径。

下一切片为 3G Terminal。3G–3I 与最终全链路缺陷清零仍未完成，因此本记录不构成 Phase 3 或
Project vNext 核心完成声明；Phase 4–5 仍是需求触发项。

## 实现与边界

- `GET /api/git/status` 使用稳定的 porcelain v1 `-z` 输出，禁用 fsmonitor，解析 rename/copy 来源；
  返回最多 1,000 项、最多解析 1 MiB，并对无 Git、非仓库根目录、Git 不可用和超限给出显式状态。
- `GET /api/git/diff?path=<repo-relative>&area=staged|unstaged` 复用现有 `execute_git_tool`、
  `WorkspaceSandbox`、timeout 与输出预算；固定 `--no-ext-diff --no-textconv`，拒绝未知 area、越界路径、
  绝对路径和非仓库根 workspace。
- unstaged diff 比较 index 与 worktree；staged diff 比较 HEAD 与 index。untracked 文件不伪造 diff，
  UI 引导到 Files 查看内容。
- React Git 视图有独立刷新、请求序号竞态保护、状态徽标、staged/unstaged 切换，以及 clean、
  non-repo、error、truncated、binary、deleted、rename 与 Unicode 路径状态。
- 未增加 dependency、Git 写操作、历史浏览器、commit/push UI、自动刷新轮询或第二套 Git 执行器。

## 测试证据

- Python 定向：Git Tool、porcelain parser、HTTP、server contract 共 `139 passed`。
- 主工作树源码全量：`1155 passed in 137.42s`；wheel-site 隔离导入全量：
  `1155 passed in 137.87s`，导入路径来自 D 盘 wheel-site；最终代码提交 detached worktree 全量：
  `1155 passed in 134.87s`。
- frontend `npm run check`：typecheck、lint、UI policy、production build 通过；Vitest `29 passed`；
  Playwright `49 passed`，1 个 30 秒录制用例按设计 skipped；`npm audit` 为 0 漏洞。
- served wrapper：`5 passed`、1 个 POSIX-only 用例在 Windows skipped；源码与 wheel 的真实 served
  Workbench 均 `4 passed`，覆盖真实 Git staged/unstaged/untracked，同时回归 Files 搜索/保存/snapshot、
  Runs、审批取消、父子进程树停止和服务重启恢复。
- 状态矩阵覆盖 clean、non-repo、Git 不可用、staged、unstaged、untracked、conflict、binary、deleted、
  rename/copy、Unicode/空格路径、超限、helper 禁用、sandbox 与 stale response。

## 提交、包体与 wheel

- 设计提交：`52165e8`；后端提交：`05e612a`；前端提交：`0a36c61`；进程停止测试稳定性修复：
  `343d728`；最终运行时修复提交：`0a4335aff37880aab5a8c24ee0f4a86bfdf9735c`，tree
  `1af5d8d33a1f9b7f91fd9e0be43778ded624ee4b`。
- wheel：`agent-2.1.0-py3-none-any.whl`，1,299,171 bytes，SHA-256
  `96da88655e8806b1a15edf5a16185b0fabed3a3c9239af0d4acc9fe259101288`；最终提交重复构建 hash 一致。
  wheel 内 30 个 preview 文件及 `web/git.py`、`web/server.py`、`web/chat_runtime.py`、`tools/git.py`
  与源码逐字节一致，
  `release doctor` 完成，wheel 实服 4/4 通过。
- 首屏同步 JS 为 480,430 raw / 149,104 gzip bytes；相对 3E 增加 5,336 raw / 1,182 gzip bytes。
  preview 共 30 个文件、3,732,892 raw bytes，没有新增 runtime dependency。

## 可见浏览器

- wheel 启动的隔离 Workbench 连接真实临时 Git 仓库；状态列表正确显示同一 `src/app.py` 的 staged 与
  unstaged 标记、Unicode/空格 untracked 文件以及 Workbench 自身本地锁文件。
- 选择 `src/app.py` 后，默认 unstaged diff 正确显示 index 到 worktree；切换 Staged 后正确显示
  base 到 index。选择 untracked 文件时不发起 diff，并显示到 Files 查看内容的明确提示。
- 1440px 截图人工检查无重叠、截断或横向溢出。源码/wheel served Playwright 的浏览器
  warning/error 收集结果均为空。

## 验收中发现并修复

1. 并行全量检查首次暴露 `test_run_command_surfaces_tree_stop_failure` 的时间竞态：测试子进程只运行
   2 秒，而超时为 1 秒，重载时父进程可能先自然退出。生产代码不能把“父进程已退出”等同于进程树
   清理成功，否则可能漏掉孤儿子进程；因此只把测试进程改为 60 秒，并连续 5 次定向通过。
2. 最终全量在 99% 暴露审批自然超时与用户决策的竞态：worker 抢先清空 pending 后，接口会把同一
   次过期审批随机报告为“无待审批”。修复在共享 ChatRuntime 保留 expired outcome，并在下一次
   `approval_required` 清除旧 outcome；竞态路径连续 20 轮、ChatRuntime 36 项与三套全量均通过。
3. 首次 PEP 517 构建因 `TMPDIR` 未覆盖而短暂使用
   `C:\\Users\\admin\\AppData\\Local\\Temp\\pip-ephem-wheel-cache-vpnuq424`；该临时路径由 pip 自动
   清理，读验证已不存在。后续构建固定 `TMPDIR`、`TEMP`、`TMP` 到 D 盘。
4. 最终 served wheel 首次重跑时，同一条 shell `export` 中的 `TEMP="$TMPDIR"` 读取了旧值，Node 因而
   短暂创建 C 盘 `agent-served-workspace-FJLrVN`。测试脚本 finally 已自动删除 workspace/home，读验证
   无任何 `agent-served-*` 路径残留；随后改为逐条 export，并在 D 盘重新 4/4 通过。

## 清理与状态

- 3F 的 D 盘 detached worktree、wheel、wheel-site、npm/pip/pytest cache、served workspace 与浏览器
  workspace 已按已核对的绝对路径清理；Git worktree 只剩主工作树，无后台作业或 4174/4175 监听；
  不触碰两份用户原有的未跟踪 handoff 文档。
- 没有 push、Ready 或 merge。3D/3E 已记录的 C 盘 pytest/npm cache 残留仍等待用户明确授权，本切片未动。

## 完成清单

- [x] porcelain、repository root、sandbox、helper 禁用、timeout 与输出上限
- [x] staged/unstaged/untracked/conflict/binary/deleted/rename/Unicode/clean/non-repo
- [x] React 竞态、状态切换、错误/空态、窄屏/桌面与可访问性
- [x] 源码、wheel、detached、真实服务、可见浏览器与包体门
- [x] D 盘 temp/worktree/process 清理；C 盘自动清理结果已只读确认
