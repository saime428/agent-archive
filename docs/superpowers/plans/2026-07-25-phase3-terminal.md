# Phase 3G Terminal 与进程管理实施计划

- 日期：2026-07-25
- 状态：执行中
- 设计：[Phase 3G Terminal 与进程管理](../specs/2026-07-25-phase3-terminal-design.md)

## 固定边界

- 新增一个 Web Terminal runtime、四条 route、一个 TerminalView、typed API、直接测试和验收文档。
- 只支持单活动、结构化 argv、line-mode stdin、内存 ring buffer；不新增 dependency、PTY、shell 或持久层。
- 提取并复用 `tools.shell` 的 command/path policy、process-group 与 tree-stop helper；Terminal 不扩大权限。
- `terminal_enabled` 默认 false，只允许项目 CLI 显式写入；浏览器不加入启用白名单。
- 所有测试 temp、wheel、cache、真实 workspace 和 detached worktree放在 `D:\CodexScratch`；两份既存
  handoff 不修改、不暂存。

## Task 1：文档与红灯

提交 spec、plan、verification 骨架和 docs 契约。先以失败测试锁定配置门、argv/cwd 策略、cursor ring、
input、自然退出、stop/timeout/close 唯一终态和进程树清理。

## Task 2：共享执行安全链与 TerminalRuntime

把现有 shell command/path validation、process-group args、tree-stop helper 提升为两调用方共享函数，不改
`run_command` 行为。实现单进程 `TerminalRuntime`：reader/monitor/finalize、1 MiB/4,096 event ring、15 秒
long-poll、600/3,600 秒 timeout、UTF-8 incremental decode 与 stale id 防护。

## Task 3：Web Interface 与配置门

给 AgentConfig、CLI parser/show 与 typed config record 增加 `terminal_enabled`；不加入浏览器写白名单。
server 注册 GET snapshot 与 start/input/stop POST，复用 Host/Origin/JSON 限制，并在正常服务关闭时 close
runtime。API 测试用真实 loopback handler 覆盖 disabled 与完整进程闭环。

## Task 4：最小 TerminalView

Workspace 增加 Terminal tab；程序、逐行参数、相对 cwd、timeout 组成 argv。实现 disabled/idle/start、
cursor output、stdin、stop 和所有终态，复用现有 toolbar/button/error/payload 样式；只增加必要的 terminal
样式和 API unit/mock E2E，不引入 terminal renderer 或状态库。

## Task 5：审查与真实验收

运行 Terminal/Web/config/shell 定向集、Python 全量与 frontend unit/typecheck/lint/UI policy/build/Playwright。
五轴审查确认 shell 不可达、cwd/path 不越界、输出有界、竞态终态唯一、stop/timeout/close 清整棵树、
刷新恢复且窄屏/focus 不回归。

从最终代码提交创建 D 盘 detached worktree，重跑全矩阵；源码与 wheel served Workbench 启用临时项目
配置并运行真实交互进程，核对 wheel 字节闭包、release doctor、可见浏览器、console、端口/进程/temp 和
Git 状态清理。

最后更新 verification、方向与 roadmap，只声明 3G 完成，下一步为 3H Command/Layout。

## 完成门

- disabled → CLI enable → start → cursor output → input → stop/timeout/exit 的真实闭环；
- 策略/containment/Host/Origin/上限不弱化，父子进程树与终态清理可证明；
- 全量、真实浏览器、wheel、提交后复验和清理通过；
- Project vNext 核心仍保持未完成。
