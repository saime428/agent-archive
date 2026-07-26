# Phase 3G Terminal 与进程管理验收记录

- 日期：2026-07-25
- 状态：3G Terminal 已完成
- 设计：[Phase 3G 设计](../superpowers/specs/2026-07-25-phase3-terminal-design.md)
- 计划：[Phase 3G 计划](../superpowers/plans/2026-07-25-phase3-terminal.md)

## 当前结论

3G 已完成并通过独立验收。Terminal 默认关闭，CLI 显式启用后可在 React Workbench 通过结构化 argv
启动一个真实进程，按 cursor 续读输出、发送 line-mode stdin，并在 stop、timeout 或服务关闭时清理进程树。
实现没有增加依赖、PTY、shell、环境编辑、持久化或多进程会话。

下一切片为 3H Command/Layout；Phase 3、Frontend vNext 与 Project vNext 核心仍需 3H–3I 和最终全链路
缺陷清零，不在本记录中提前声明完成。

## 提交与闭包

- 设计提交：`1dcdc9b`；后端提交：`5a8b711`；前端与最终代码提交：
  `e262f5294fbef8e243f1da7e6e471b776dce6746`，tree：
  `1e75288b1f31fe1f0588933968b19814ba4caff5`。
- wheel：`agent-2.1.0-py3-none-any.whl`，1,305,212 bytes；固定同一
  `SOURCE_DATE_EPOCH` 独立构建两次，SHA-256 都是
  `a7f5e2c26c1a3d4e7aba3ece642ee84a990ae60c98d4c39012ece6a2e029f75f`。
- wheel 中 `config.py`、`cli.py`、`tools/shell.py`、`web/server.py`、`web/terminal.py` 和全部
  30 个 preview 文件均与 detached 源码逐字节一致；preview 共 3,742,983 bytes。
- 主同步 bundle 为 `index-Dp6lYrwl.js`，487,703 bytes；CSS 为 `index-DFx2Gaxa.css`，
  64,020 bytes。没有新增 runtime dependency，`npm audit --audit-level=low` 为 0 漏洞。

## 功能与安全边界

- `terminal_enabled` 默认为 false，只能由项目 CLI 显式设置；浏览器 Settings 只读展示。
- GET snapshot 和 start/input/stop 三条 POST 复用 loopback、Host/Origin、JSON body 与 state-change
  检查；runtime 固定 `shell=False`。
- Terminal 和 `run_command` 共用 command/path policy、process-group 与 tree-stop helper；argv、cwd、
  timeout、NUL、stale id、单活动进程与 UTF-8 byte 上限均有边界测试。
- stdout/stderr 使用 incremental UTF-8 decoder 与全局 cursor；ring 限制 1 MiB/4,096 events，
  cursor 落后时返回 `truncated`。
- stop、timeout、close 和自然退出共享唯一 finalize 路径；Windows 使用 `taskkill /T /F`，POSIX 使用
  process group。真实父子进程测试证明 parent/child 都被停止。

## 自动化验收

- Terminal 后端直接测试：18 passed，覆盖配置门、策略、Unicode split、stdin ASCII/多字节边界、
  自然/非零退出、stop、timeout、close、父子树、truncation、long-poll 与 HTTP。
- 最终代码提交后的主工作树全量：`1177 passed in 122.15s`。
- 同一提交的 D 盘 detached worktree 全量：`1177 passed in 130.70s`。
- wheel-site 隔离导入全量：`1177 passed in 130.29s`；`agent.__file__` 明确来自 D 盘 wheel-site，
  测试关闭仓库 `pythonpath` 注入。
- detached 前端从 lockfile 安装 236 个包；typecheck、lint、UI policy、Vitest 30 passed、production
  build 与 Playwright 54 passed 全部通过，1 个 30 秒性能录制用例按设计 skipped。
- Windows served wrapper 6 passed，1 个 POSIX-only 用例 skipped；wheel 实服 5 passed，覆盖默认入口、
  Files/Git、真实交互 Terminal、approval cancel、真实 Python 父子树停止与服务重启恢复。
- detached 重新执行 `build:preview` 后 tracked preview 零漂移；`release doctor` 返回
  `release readiness: complete`。

## 可见浏览器

使用 wheel 实服打开根 React Workbench，显式启用的 Terminal 完成
`idle → running → ready-visible → stdin hello-visible → got:hello-visible → stopped`。664×929 可见视口
中五个工作台入口、命令摘要、输出和 stdin 均可操作，`scrollWidth == innerWidth == 664`；浏览器控制台
warning/error 为 0。

## 审查中修复的问题

1. `serve_workbench` 在 Terminal 构造或关闭失败时可能漏关 MCP：把 MCP close 保持在独立 finally。
2. 320px 工作台导航标签被隐藏后按钮失去可访问名称：保留 `aria-label`/`title` 并统一窄屏图标按钮。
3. Windows served wrapper 只停止 server parent：复用 `taskkill /PID ... /T /F` 清理整棵进程树。
4. stdin 的 16 KiB 契约按字符而非 UTF-8 bytes 计数：改为精确 byte 上限并补多字节边界测试。
5. 新进程沿用上一进程的“用户已向上滚动”状态：start 时重置 follow-tail。

## 清理与 Git 状态

- 本轮 `agent-phase3g-postcommit-e262f52` 的 detached worktree、wheel、wheel-site、npm/pip/pytest cache、
  served workspace 与浏览器 workspace 已按核对后的 D 盘绝对路径清理；4174/4175 无监听，Git worktree
  只剩主工作树。
- 一次较早失败的 served harness 留下 4 KiB workspace 和空 home；对应 parent/child 已确认退出。工具策略
  拒绝删除这两个精确目录，未绕过策略：
  `D:\CodexScratch\agent-phase3g-served-temp\agent-served-workspace-I7ak0d`、
  `D:\CodexScratch\agent-phase3g-served-temp\agent-served-home-RomjxE`。
- 主工作树只保留两份用户原有的未跟踪 handoff；未修改、未暂存。没有 push、Ready 或 merge。

## 完成检查

- [x] 默认关闭、CLI enable、结构化 argv、cwd/path/Host/Origin/大小边界
- [x] cursor/ring、stdout/stderr、stdin、stop/timeout/exit/close 与真实进程树
- [x] React disabled/running/error/recovery、键盘、320/390/664/1440 与 visual baseline
- [x] 源码、detached、wheel、真实服务、可见浏览器与 release doctor
- [x] 代码提交与验证文档分离；Project vNext 核心继续保持未完成
