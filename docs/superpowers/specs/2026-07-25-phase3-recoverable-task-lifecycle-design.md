# 设计：Phase 3 可恢复任务生命周期

- 日期：2026-07-25
- 状态：设计与计划均已审查；待实施
- 上位方向：[Phase 3 方向分析与审查](../../project-vnext-phase3-direction-review.md)

## 目标

把当前进程内、完成后才可靠持久化的 Web chat job，收口为一个可取消、有整轮超时、可重连、
可识别服务中断、可安全续接的本地任务生命周期；CLI 与 Workbench 复用同一 run stop 终态。

本切片完成后，允许声明“3A Lifecycle 完成”，不允许声明 Phase 3、Frontend vNext 或
Project vNext 核心完成。

## 当前事实

- `run_once` 是唯一 Agent loop，Tool/approval/stream 事件均从这里产生，run 日志只在正常
  `_finalize_run` 时集中落盘。
- `ChatRuntime` 只在内存保存 job/event，完成 5 分钟后 prune；进程重启后 job ID 成为 unknown。
- `_active_sessions` 只拒绝同 session 的并发 turn；不同 session 和同步 `/api/chat/turn` 仍可
  同时修改同一 workspace。
- approval 有独立等待超时；`run_command` 有 30–120 秒 Tool 超时；整轮没有 deadline。
- React 用 sessionStorage 保留 active job，SSE 断线时重连一次并从 sequence 0 重放，客户端去重。
- CLI `--resume` 恢复 conversation history，不等于中断任务恢复；CLI 当前没有整轮 timeout。

## 固定语义

### Run control

新增一个无依赖的共享 `RunControl` 值对象，只有三项职责：

- 线程安全地记录 cancel request；
- 用 monotonic clock 判断 deadline；
- 返回 `cancelled`、`timed_out` 或 `None`。

`run_once` 在模型调用前后、每个流式 chunk、approval 后、Tool 前和下一轮前检查 control。
检测到 stop 后生成一个可落盘的终态 observation 并照常执行 `_finalize_run`；不得用异常跳过
run summary、tool trace、hook 和 conversation 保存。

`ErrorCode` 增加 `CANCELLED`。`TIMEOUT` 继续表示 timeout；二者都不是 recoverable Tool error，
不会要求模型继续尝试。终态分别为 `cancelled` 与 `timed_out`。

模型非流式请求和外部 MCP 调用无法由 Python 强制中断时，stop 在调用返回后生效，最坏延迟仍
受各 Adapter 既有 transport timeout 约束。不得为此遗留仍可写工作区的后台 model/tool 线程。

### 子进程停止

`run_command` 从一次性 `subprocess.run` 改为同样参数和输出契约的 `Popen + communicate` 有界轮询：

- cancel 或整轮 deadline 到达时停止整个进程树；
- Windows 使用系统 `taskkill /PID <pid> /T /F`，POSIX 使用独立 process group 的 TERM/KILL；
- Tool 自身 `timeout_seconds` 仍保留并返回 `TIMEOUT`；整轮 stop 分别返回 `CANCELLED` 或
  `TIMEOUT`，details 写明 stop source；
- stdout/stderr 的 decode、截断、sandbox、command policy 和 argv 语义不变。

如果进程树无法确认停止，返回明确错误并保持 job terminal；不得只关闭浏览器流。

### Workspace 占用

一个 workspace 同时只允许一个 Agent turn，包括 CLI `run/chat`、异步 start 与同步
`/api/chat/turn`。共享 `WorkspaceRunLease` 使用 `.agent/chat-jobs/workspace.lock` 的非阻塞 OS
文件锁；同进程状态只用于快速查询，不作为唯一互斥来源。Automation 后续也必须复用该 lease。

lease 持有期间可在锁文件写入有界、redacted 的 owner 诊断（kind、session/job id），但这些内容
不决定所有权；只有 OS lock handle 是权威。CLI 和 Web 的冲突都返回明确 busy 结果，不排队。

session rename/delete 继续只与同 session 活跃 turn 互斥，不因其他 session 的运行无条件阻塞。
锁文件是普通持久文件，锁的所有权由 OS handle 决定；进程退出后不需要猜 PID 或删除 stale lock。

### Durable job/event

存储根固定为 `.agent/chat-jobs`：

- `<job_id>.json`：version、job/session/run id、status、started/completed time、timeout、
  `resumed_from_job_id` 和经过 redaction 的原始 user message；
- `<job_id>.events.jsonl`：按 sequence 追加的已 redacted Run Event；
- `active.json`：当前 workspace job 指针，原子替换，完成后只在仍指向本 job 时删除。

job id 必须通过固定正则，所有父目录必须是 workspace 内真实目录，拒绝 symlink/reparse redirect。
metadata 与 active pointer 使用现有原子替换原语；event 每条在 runtime condition 内完成一次
append/flush/fsync 后才对 poll 可见。读取允许忽略 crash 造成的唯一末尾残行，禁止跳过中间坏行。

内存完成 job 仍可按现有 TTL prune，但 `_get_job` 必须能从 durable metadata/event 重新加载；
durable 审计记录本切片不自动删除。

### 服务重启与 resume

`ChatRuntime` 初始化时先尝试 workspace OS lock：

- 能取得锁且 `active.json` 指向 `running`/`cancel_requested` job，说明旧 owner 已退出；追加唯一
  `interrupted` 终态，写最小 run summary 和 conversation turn，然后清除 active pointer；
- 取不到锁说明另一个进程仍拥有任务，不修改其状态；
- 恢复操作幂等，重复启动不得追加第二个 interrupted turn/event。

新增 `POST /api/chat/resume`，请求为 `job_id`、非空新 `message` 和可选 timeout。只允许从
`cancelled`、`timed_out`、`interrupted` 或 `failed` job 续接；复用旧 session，创建新 run/job，
并记录 `resumed_from_job_id`。

resume **不会重放旧 message 或任何 Tool**。它只用 conversation 中已持久化的终态和用户的新
message 继续，因此不会重复文件写入、命令或 MCP 副作用。

### HTTP/SSE 与 Workbench

新增/扩展 Interface：

| Interface | 行为 |
| --- | --- |
| `POST /api/chat/start` | 接受可选 `timeout_seconds`，返回 job/session/run id |
| `POST /api/chat/cancel` | 按 job id 幂等请求 cancel；唤醒 approval；已 terminal 返回当前状态 |
| `POST /api/chat/resume` | 从允许的 terminal job 用新 message 安全续接 |
| `GET /api/chat/events?job_id=&after=` | 从有界非负 cursor 续读；无 `after` 等价 0 |

timeout 只接受整数 1–3600 秒，默认 900 秒；boolean 不视为整数。错误仍用 JSON/no-store，
Host/Origin/CSP 规则不变。

SSE 增加 `cancelled`、`timed_out`、`interrupted` terminal event。客户端重连 URL 携带
`after=lastSequence+1`，仍对重复 sequence 防御性去重。React 在 active turn 显示“停止”按钮；
terminal 后重新开放 composer，下一条消息通过 resume Interface 续接。刷新或服务重启后仍能
从 sessionStorage job id 读取 durable terminal event 并回到持久化 conversation。

### CLI

`agent run` 与 `agent chat` 增加相同的可选 `--timeout-seconds`（1–3600，默认 900）；每个 chat
turn 新建 control。CLI 的 timeout/cancel 结果继续打印 run id、status、terminal_reason、summary
并使用非零退出/错误输出；conversation chat 保留终态后仍可输入下一条消息。

Ctrl+C 落在 model 或 Tool 调用时转换为本 turn 的 `cancelled` 结果并完成日志，不吞掉第二次
Ctrl+C 或 REPL 输入阶段的退出语义。

## Conversation 与 payload 兼容

`ChatTurn` 新增可选 `job_id` 和 `resumed_from_job_id`，默认 `None`，旧 session JSON 可继续加载。
现有字段与 URL 不删除；start/turn/final payload 只做 additive change。旧前端不认识新 terminal
event 时仍可通过 durable session fallback 看到终态，但当前 React 必须原生处理。

## 允许文件

- `src/agent/core/actions.py`
- `src/agent/core/run_control.py`（新）
- `src/agent/core/run_lease.py`（新）
- `src/agent/core/loop.py`
- `src/agent/core/chat.py`
- `src/agent/tools/shell.py`
- `src/agent/web/chat_runtime.py`
- `src/agent/web/server.py`
- `src/agent/web/chats.py`
- `src/agent/cli.py`
- `frontend/src/api/{client,sse,types}.ts` 及其现有测试
- `frontend/src/chat/state.ts` 及其现有测试
- `frontend/src/App.tsx`、`frontend/src/styles.css`
- `frontend/e2e/workbench.spec.ts`、`frontend/e2e-served/served-workbench.spec.ts`
- 对应 Python 测试、文档契约、implementation plan 与 verification

若需要修改 Provider/MCP transport、config schema、file/snapshot API、Memory、Automation、eval、
Monaco/Git/Terminal 或增加依赖，停止并另写 spec。

## 测试设计

### Core

- deadline 在首个 model call 前、流式 chunk 间、Tool 前分别生成一次 `timed_out` terminal，
  summary/tool_calls/after_run hook 均存在；cancel 对应 `CANCELLED`。
- approval 等待收到 cancel 立即醒来，不执行 write Tool；整轮 timeout 与 approval timeout 事件不同。
- 真实 Python 子进程及其子进程在 cancel/timeout 后不再存活；stdout/stderr 与原有 policy 回归通过。
- 未传 control 的既有 `run_once` 行为、事件顺序和结果完全兼容。

### Runtime/store

- 不同 session、同步/异步入口和两个 runtime instance 都不能同时取得 workspace turn lease。
- start 返回前 metadata、active pointer、session 和 `chat_started` event 已可读；线程启动失败精确回滚。
- memory prune 后 poll 可从磁盘恢复；cursor、末尾残行、坏中间行、redirect path 均有确定行为。
- cancel 幂等；approval cancel、shell cancel、timeout、normal final、worker error 各只有一个 terminal event。
- 构造 crash 遗留 active pointer 后，新 runtime 产生一次 interrupted event/turn/summary；再次启动不重复。
- resume 拒绝 running/completed/unknown job，允许四种异常终态，并证明旧 Tool 不被自动重放。

### HTTP/CLI/React

- 路由、JSON validation、Origin/Host、SSE `after` 和 terminal events 契约覆盖。
- CLI timeout validation、run/chat terminal output、退出码与旧 session load 覆盖。
- Vitest 覆盖 cursor reconnect、三个新 terminal event、cancel/resume API 和 reducer。
- Playwright 覆盖普通 final、approval cancel、长命令 cancel、刷新恢复、服务重启 interrupted 后新消息
  resume；全程无 console error、loopback 4xx/5xx（预期 validation 用例除外）。

## 验收门

- spec 与 plan 分别通过正确性、可读性、架构、安全、性能五轴审查；
- 目标测试先红后绿；Python 聚焦、完整 `pytest -q`、前端 `npm run check`、真实 Python 实服 E2E、
  CLI smoke、`agent release doctor` 与 `git diff --check` 通过；
- 可见浏览器完成 cancel → durable terminal → 新消息 resume，刷新不丢 job；
- D 盘隔离 workspace/home/temp 验证进程、端口、lock 和临时目录无残留；
- wheel 内新增 Module、server、React bundle 与源码一致；
- 不暂存两份无关 handoff，不 push、不 Ready、不 merge。

## 非目标

- 不自动重试或重放有副作用的 Tool；不做 checkpoint 级 model continuation。
- 不做多个 workspace 队列、并行 Agent、sub-agent、worktree orchestration 或远程任务。
- 不做 Automation scheduler、Memory 修订、eval、Monaco、Git UI、Terminal UI 或命令面板。
- 不引入数据库、消息队列、WebSocket、后台系统服务、第三方进程库或前端依赖。
- 不删除 legacy Workbench；它仍是本切片回滚入口。

## 设计审查记录

1. 正确性：resume 被锁为“新消息续接”，避免把 conversation resume 错写成 Tool replay；timeout、
   approval timeout、cancel、worker failure 和 process interruption 使用不同终态。
2. 可读性：RunControl 只负责 stop reason；job store、run loop、HTTP 和 UI 各保留现有职责。
3. 架构：继续使用单一 run loop、SSE Interface、文件 store 与安全链；新增 OS lease 是第二个真实
   进程竞争者所需的最小 seam，不建立通用调度框架。
4. 安全：job message/event 先 redaction；路径拒绝 redirect；resume 不重放；子进程必须整树停止；
   Host/Origin、sandbox、approval 和 snapshot 不变。
5. 性能：单 workspace slot 消除冲突；event append 为 O(1)，poll 从 cursor 返回；磁盘 reload 只读
   单个 job，不扫描全部历史。

审查结论：通过，无未解决 finding。implementation plan 必须先证明 stop 的 run finalize 和进程树
清理，再接 HTTP/React；若这两个根语义失败，停止后续适配层实施。
