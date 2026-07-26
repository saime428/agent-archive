# Phase 3H 命令面板与布局持久化验收记录

- 日期：2026-07-25
- 状态：3H Command/Layout 已完成
- 设计：[Phase 3H 设计](../superpowers/specs/2026-07-25-phase3-command-layout-design.md)
- 计划：[Phase 3H 计划](../superpowers/plans/2026-07-25-phase3-command-layout.md)

## 当前结论

3H 已完成并通过独立验收。顶部命令面板只聚合新建任务、五个工作台视图、刷新、会话轨道和上下文画布
九个已有动作；`Ctrl+K` / `⌘K`、过滤、上下键、Enter、Escape、空态、modal 防叠加和 focus return 均已闭环。
单一 `agent.frontend.layout` 只保存四个非敏感布局字段，损坏、越界或被浏览器拒绝时安全退化。

下一切片为 3I Legacy retirement；Phase 3 与 Project vNext 核心仍需 3I 和最终全链路缺陷清零，
本记录不提前声明核心完成。

## 提交与构建闭包

- 设计提交：`573877d`；最终代码提交：
  `05b6fc3197feb77194baf07a6cea77f4c7d5f637`，tree：
  `ff2fd5c4a3cd997a189ea5a0088750bee812e7d4`。
- 固定同一 `SOURCE_DATE_EPOCH` 独立构建两次 wheel，均为
  `agent-2.1.0-py3-none-any.whl`、1,307,371 bytes，SHA-256 均为
  `29a921fb64c6f07503fb397b1e7b15ababa57255bb8cfdb43fbac3a08efb93c7`。
- wheel 中 30 个 preview 文件、3,751,075 bytes 与 detached 源码逐字节一致；主 bundle
  `index-DR8CVulA.js` 为 492,999 bytes，CSS `index-CfbbGzen.css` 为 66,824 bytes。
- detached 重新执行 `build:preview` 后 tracked preview 零漂移；没有新增 dependency，
  `npm audit --audit-level=low` 为 0 漏洞，`release doctor` 返回 `release readiness: complete`。

## 功能与安全边界

- `CommandPalette` 复用 Radix Dialog、Lucide 和 App 既有 handler；没有 registry、fuzzy search、命令历史、
  快捷键配置、后端 API 或重复业务规则。
- 打开其他 dialog 时 `Ctrl+K` 不叠加第二个 modal；命令进入 Workspace 后仍由既有 Files dirty guard
  保护未保存编辑。
- layout parser 逐项校验布尔值、260–420 rail width 和五个允许的 workspace view；storage 读取、解析或
  写入异常只退回内存默认值。
- localStorage 不含 workspace/session/run/file id、编辑 buffer、Terminal、Provider、approval 或 secret；
  E2E 对实际序列化对象做了精确相等断言。
- 320/390/664/1440 无横向溢出，键盘、accessible name、reduced motion、focus trap/return 和视觉基线不回归。

## 自动化验收

- 主工作树最终提交前 Python 全量：`1178 passed in 128.77s`。
- 同一提交 D 盘 detached worktree 全量：`1178 passed in 139.44s`。
- wheel-site 关闭仓库 `pythonpath` 注入后的隔离全量：`1178 passed in 140.23s`；`agent.__file__`
  明确来自 D 盘 wheel-site。
- 主工作树和 detached 前端均通过 typecheck、lint、UI policy、33 个 Vitest、production build 与
  Playwright 59 passed；1 个 30 秒性能录制用例按设计 skipped。
- layout/storage 定向 Vitest 3 passed；命令面板与布局 Playwright 5 passed；取消/恢复竞态用例串行
  `repeat-each=10` 为 10/10 passed。
- Windows served wrapper 6 passed、1 个 POSIX-only 用例 skipped；wheel 实服 5/5 passed，覆盖默认入口、
  Files/Git、真实 Terminal、approval cancel、真实 Python 父子树停止和服务重启恢复。

## 可见浏览器

使用 wheel 实服打开根 React Workbench：`Ctrl+K` 自动聚焦搜索，过滤并执行 Git 真实视图；隐藏 canvas
与最后 Git view 在 reload 后恢复，Escape 把焦点返回命令按钮。664×929 可见视口中
`scrollWidth == innerWidth == 664`，浏览器 console warning/error 为 0。

## 审查中修复或排除的问题

1. 取消后 resume 的测试注入器可能把事件发给已关闭 EventSource：共享 helper 等待并选择最新 live source，
   串行重复 10 次稳定通过。
2. `listbox` option 曾嵌套额外按钮：把 option 本身改为可点击按钮，保持 combobox active-descendant 与
   搜索框键盘焦点，减少一层交互 DOM。
3. 10 worker 压力复跑有一次 Chromium 在 `page.goto` 资源性崩溃；同用例单 worker 重复 10 次和两轮正式
   全量均通过，排除为产品断言失败，正式配置继续使用既有单 worker。
4. 首轮 wheel served 在 detached 根寻找不存在的 `.venv`，Terminal 返回 WinError 2；显式使用既有
   `AGENT_TEST_PYTHON` 后 5/5 通过，确认是验收环境路径而非产品缺陷。

## 临时项与 Git 状态

- 4174/4175 无 LISTENING，wheel 实服已停止，served workspace/home 已由包装器清理；主工作树和 detached
  均通过 `git diff --check`，detached tracked 状态为空。
- 本轮 7 个 `D:\CodexScratch\agent-phase3h-*` 根约 478 MB，其中提交后独立证据根
  `agent-phase3h-postcommit-05b6fc3` 约 446 MB。它们只含可重建的 detached、node_modules、wheel、cache
  和测试输出；按用户清理授权规则暂时保留，不影响提交或运行。
- 主工作树只保留两份用户原有的未跟踪 handoff；未修改、未暂存。没有 push、Ready 或 merge。

## 完成检查

- [x] 九个真实命令、Ctrl/⌘K、过滤/键盘/空态、modal 与 focus return
- [x] 四项非敏感 layout reload、边界校验和 storage 失败退化
- [x] dirty guard、安全边界、320/390/664/1440、reduced motion 与 visual baseline
- [x] 主树/detached/wheel 全量、确定性构建、真实服务、可见浏览器与 release doctor
- [x] 代码提交与验证文档分离；Project vNext 核心继续保持未完成
