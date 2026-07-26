# 设计：Phase 3G Terminal 与进程管理

- 日期：2026-07-25
- 状态：设计已锁定，待实施与独立验收
- 上位方向：[Phase 3 方向分析与审查](../../project-vnext-phase3-direction-review.md)

## 目标

在 React Workbench 增加一个显式启用的 line-mode Terminal：启动一个受现有命令策略约束的真实子进程，
按 cursor 续读 stdout/stderr，向 stdin 发送行，主动停止或按时限停止整棵进程树，并在浏览器刷新后恢复
当前进程状态与已保留输出。

这不是 PTY 或任意 shell。第一版只允许一个活动进程，API 接受结构化 argv，继续拒绝 shell wrapper、
危险命令、网络命令、越界 cwd/path 和未列入 `allowed_commands` 的程序。本切片完成后只允许声明
“3G Terminal 完成”；Phase 3 和 Project vNext 核心仍需 3H–3I 与最终全量缺陷清零。

## 官方语义与本地事实

- [Python subprocess 官方文档](https://docs.python.org/3/library/subprocess.html)说明 `Popen` 用于需要持续
  控制的高级子进程，stdin/stdout/stderr 使用 `PIPE` 建立父子进程管道；`shell=False` 可直接传 argv。
- 同一文档明确 Windows 的 `CREATE_NEW_PROCESS_GROUP` 和 POSIX 的新 session/process group 语义；本项目
  已在 `agent.tools.shell` 使用它们，并以 `taskkill /T /F` 或 `killpg` 停止进程树。
- 当前 `run_command` 已有 command allowlist、shell/network/dangerous deny、workspace path 校验、进程组与
  tree-stop helper。3G 必须提取并复用这些原语，不能建立第二套宽松执行策略。

## 显式启用与安全边界

- 新增布尔配置 `terminal_enabled=false`。只能通过项目 CLI 显式开启：

  ```text
  agent config set terminal_enabled true --cwd <workspace>
  ```

- 浏览器 Settings 只显示状态，不把 `terminal_enabled` 加入可写白名单；关闭仍可用 CLI unset/false。
- Workbench 继续只监听 loopback，并复用 Host、Origin、JSON body 上限和 CSP。Terminal 所有 POST 都走
  既有 state-change 授权。
- Terminal 固定 `shell=False`，不接受 command string、shell operator、环境变量覆盖、绝对/外部 cwd；
  cwd 通过 `WorkspaceSandbox(..., allow_external_read=False)`，argv 通过现有 command/path 策略。
- stdin 内容不写 run log、配置或持久文件；stdout/stderr 原样在内存有界保存，不宣称 secret redaction。
  UI 明确提示不要输入密钥。新进程或服务关闭会丢弃旧 buffer。

## Interface

新增一条 GET 与三条 POST：

```text
GET  /api/terminal?terminal_id=<id>&after=<cursor>&timeout=<0..15>
POST /api/terminal/start
POST /api/terminal/input
POST /api/terminal/stop
```

`GET` 不要求已有 terminal；未启用或 idle 也返回 200，供 UI 稳定展示。响应固定包含：

```json
{
  "enabled": true,
  "terminal_id": "terminal_0123456789ab",
  "status": "running",
  "argv": ["python", "-u", "worker.py"],
  "cwd": ".",
  "timeout_seconds": 600,
  "exit_code": null,
  "events": [{"sequence": 0, "stream": "stdout", "text": "ready\n"}],
  "next": 1,
  "truncated": false,
  "cleanup_error": null
}
```

`after` 是下一个期望 sequence；返回 `sequence >= after` 的保留事件并把 `next` 设为下一 sequence。
cursor 已落到 ring buffer 之前时 `truncated=true`，从最早保留事件继续。`timeout` 只用于最长 15 秒的
long-poll，不改变进程时限。

start 请求：

```json
{"argv":["python","-u","worker.py"],"cwd":".","timeout_seconds":600}
```

- argv 1–64 项，单项不超过 8 KiB，总计不超过 32 KiB，不允许 NUL；timeout 1–3,600 秒，默认 600。
- 一个 workspace 同时只有一个 running terminal；活动时再次 start 返回 400。终态后新 start 替换旧
  内存状态，不保留多 session/history。
- input 请求含匹配的 `terminal_id` 与最多 16 KiB UTF-8 `data`；服务端追加换行并 flush。空值、NUL、
  stale id、非 running 或 stdin 已关闭均显式失败。
- stop 幂等：匹配 terminal id 时停止整个进程树；已终态直接返回当前状态。timeout 与 stop 分别落成
  `timed_out`、`stopped`；自然 exit code 0 为 `completed`，非零为 `failed`。

## Runtime

- `TerminalRuntime` 是 workspace-scoped、纯内存对象。一个 monitor thread 等待退出/timeout，stdout 与
  stderr 各一个 reader thread；所有事件在一个 condition 下分配全局 sequence。
- 输出使用 incremental UTF-8 decoder，chunk 不在多字节字符中间产生伪 replacement；无法解码的旧
  code page 仍以 replacement 显示，不在本切片增加编码选择器。
- 最多保留 1 MiB 文本与 4,096 个事件；超限从最旧事件删除并推进 earliest cursor。UI 必须提示截断。
- stop、timeout、自然退出和服务 close 共用一个 finalize lock 与同一 tree-stop helper，终态只写一次；
  reader 在终态前短时 join，避免最后一段输出晚于 done。
- `serve_workbench` finally 调用 `TerminalRuntime.close()`；正常 Ctrl-C、API stop、timeout 和测试 wrapper
  的协作式退出必须清理进程树。服务被 OS 强杀无法执行 finally，因此功能保持默认关闭，不提供 detached。

## React 视图

- Workspace 增加 Terminal tab。disabled 态显示精确 CLI 启用命令；不提供浏览器内启用开关。
- start form 使用“程序”单行输入 + “参数（每行一项）”textarea + 相对 cwd + timeout，组装明确 argv；
  不猜测跨平台 command-line quoting。
- output 用等宽 `<pre>`，stdout/stderr/system 有可读区分；保留空格与换行、自动追随尾部，但用户向上
  滚动后不抢回滚动位置。running 时 long-poll，终态停止请求；刷新从 after=0 恢复当前 buffer。
- stdin 是单行输入，Enter 发送；stop 有明确危险动作样式。loading/error/disabled/idle/running/
  completed/failed/stopped/timed_out/truncated 全部可见，窄屏不横向撑破。

## 验收

- 配置默认关闭、CLI enable、Host/Origin、argv/cwd/path/allowlist/长度/NUL/timeout/stale id 均有测试。
- 真实 Python 子进程覆盖 stdout+stderr 续读、Unicode split、stdin→stdout、自然 0/非零退出、stop、
  timeout、父子进程树、输出截断、long-poll、单活动进程、终态幂等和 close 清理。
- React 覆盖 disabled、start、cursor output、input、stop、timeout/error、refresh recovery、320/390/1440
  与键盘 focus；served Workbench 使用真实进程而非 mock。
- Python/前端全量、detached、wheel、release doctor、可见浏览器、console 与 temp/process 清理通过。

## 非目标

- PTY/ConPTY、ANSI/VT renderer、全屏 TUI、shell wrapper/operator、Ctrl+C 字节转发、resize signal、tabbed
  terminals、多并发、detached/background、服务崩溃后进程接管、历史持久化、环境变量编辑或 secrets 输入。
- SSH/container/WSL、远程 terminal、端口转发、任务 runner、自动命令建议、Git 写操作、3H Command/Layout、
  3I legacy retirement 或 Phase 4–5 需求触发项。
