# Phase 3 可恢复任务生命周期实施计划

- 日期：2026-07-25
- 状态：已执行并通过 3A 完成门
- 设计：[Phase 3 可恢复任务生命周期](../specs/2026-07-25-phase3-recoverable-task-lifecycle-design.md)

## 目标与顺序

用最小共享 lifecycle seam 让 CLI 与 Workbench 获得 cancel、整轮 timeout、workspace 占用、
durable event、重启 interrupted 和安全 resume。严格按 core → process → store/runtime → HTTP/CLI →
React → 全量验收推进；前一层未绿，不接后一层。

## 固定边界

- 不改 Provider/MCP transport、config schema、Memory、Automation、eval 或 Frontend 开发工作区。
- 不新增 Python/Node 依赖；不安装系统服务，不写 C 盘。
- 不改变 Tool policy、sandbox、approval、snapshot、Host/Origin、redaction 或旧 payload 必填字段。
- 所有临时目录、服务 workspace/home、Playwright output 和 wheel 放在 `D:\CodexScratch` 唯一目录。
- 两份未跟踪 handoff 文档不读取、不修改、不暂存。
- 每个 Task 后做正确性、可读性、架构、安全、性能五轴 diff 审查。

## Task 1：锁定文档与外部契约

### 测试先行

在 `tests/test_docs.py` 增加 3A 契约：

- Phase 3 方向、spec、plan 和最终 verification 存在；
- 明确 `resume` 不重放 Tool、单 workspace lease、1–3600 秒 timeout、三个 durable terminal event；
- 当前文档仍声明 Phase 3/Project vNext 未完成，Phase 4–5 仍为需求触发项。

先运行目标测试，因 verification 不存在和实现状态未完成而红；只创建 verification 骨架并写
“实施中”，不提前勾选门禁。

### 审查

历史 Cutover 文档不修改；测试只绑定完成边界和 Interface，不绑定行号或中间 commit hash。

## Task 2：RunControl 与 workspace lease

### 红灯

新增 `tests/core/test_run_control.py`、`tests/core/test_run_lease.py`：

- cancel 幂等且优先于 deadline；deadline 使用注入 monotonic clock；timeout 边界等于 deadline；
- bool/0/负数/3601 被 timeout validator 拒绝，None 得到默认 900；
- 同 workspace 两个 lease 竞争时第二个立即 busy；释放后可取得；不同 workspace 可并行；
- Windows/POSIX owner 诊断有界且 redacted，lock file redirect/reparse 被拒绝；
- context manager 异常也释放 OS handle；owner 内容不是所有权依据。

红灯命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/test_run_control.py tests/core/test_run_lease.py -q
```

### 实现

- `src/agent/core/run_control.py`：`RunControl`、stop reason、统一 timeout validation；
- `src/agent/core/run_lease.py`：非阻塞 `WorkspaceRunLease` 与明确 busy/path 错误；
- 复用 `_user_store` 的 containment、regular-file、redaction/atomic 原语；OS lock/unlock 只写一次平台分支。

### 绿灯与审查

目标测试通过；确认没有 PID 猜测、stale-file 删除、轮询队列或全局 singleton。

## Task 3：run loop 可终止且照常 finalize

### 红灯

扩展 `tests/core/test_loop_core.py`、`tests/core/test_loop_recovery.py`、`tests/test_chat.py`：

- deadline/cancel 在首轮前、stream chunk 间、approval 后、下一轮前分别产生唯一 terminal；
- `CANCELLED` 不在 recoverable 集，timeout 与 approval timeout 可区分；
- stop 仍生成 summary、tool_calls、after_run hook、memory candidate 和 conversation turn；
- `ChatTurn` 可读取无新字段的旧 JSON，并保存可选 job/resumed id；
- 未传 control 的事件、summary 和 terminal reason 保持原样。

### 实现

- `ErrorCode.CANCELLED`；
- `run_once(..., control=None)` 在已有 loop seam 检查，不复制第二个 loop；
- stop 用内部 synthetic action/observation 进入现有 `_finalize_run`；
- approval outcome 增加 run cancel/timeout，不与 approval 自身过期混淆；
- `ChatSession.run_turn` 接收可选 run/job/resume/control 并 additive 保存。

### 绿灯与审查

运行上述测试和完整 `tests/core`、`tests/test_chat.py`。审查所有 `actions[-1]`/`observations[-1]`
边界、hook 抛错、空首轮 stop 和 redaction。

## Task 4：可停止的 `run_command` 进程树

### 红灯

扩展 `tests/test_tools_shell.py`：

- 启动 repo venv Python 父进程及睡眠子进程；cancel 与整轮 timeout 后父/子 PID 均不可存活；
- Tool timeout 仍为既有 `TIMEOUT` 且 stop source 为 `tool_timeout`；
- cancel 为 `CANCELLED`；整轮 deadline 为 `TIMEOUT/run_timeout`；
- 正常 stdout/stderr、exit code、UTF-8 replacement、截断、cwd、policy 与 path validation 不回归；
- tree-stop 辅助失败返回明确 details，测试进程必须在 finally 精确清理。

### 实现

以 `Popen + communicate(timeout=短轮询)` 替换一次性 `subprocess.run`：Windows `taskkill /T /F`；
POSIX `start_new_session` + process group TERM/KILL。只在 cancel/timeout 路径调用 tree stop。

### 绿灯与审查

目标文件全绿，并用 D 盘独立 smoke 再检查 PID。不得遗留后台进程或放宽命令 policy。

## Task 5：durable job store、单 workspace runtime 与 crash recovery

### 红灯

扩展 `tests/test_web.py`，测试不经私有映射伪造绿灯：

1. start 返回前 session、metadata、active pointer、首事件和 run id 已落盘；
2. 不同 session、同步/异步入口及两个 runtime instance 共享同一 workspace lease；
3. 内存 TTL 后 poll 从 durable store 恢复；cursor 只返回尾部；
4. event JSONL 末尾残行可忽略，中间坏行/sequence 缺口拒绝；symlink/junction/reparse 拒绝；
5. cancel 幂等并唤醒 approval；shell cancel 与 timeout 各只有一个 terminal event；
6. worker error 写 failed event、minimal summary、conversation turn 并释放 active/lease；
7. crash fixture 的新 runtime 只写一次 interrupted event/summary/turn，再启动不重复；
8. resume 只接受四种异常终态，新 job 记录来源，旧 LLM/Tool 调用计数不增加；
9. thread start/persistence 失败精确回滚 metadata/event/active/lease，不误删别的 job。

### 实现

- `chat_runtime.py` 保留一个 runtime 类，增加 store helper 仅服务 job metadata/event；
- job id/path/redirect 先校验，metadata/active 原子写，event append/flush/fsync 后进 condition；
- in-memory prune 与 durable record 分开；disk load 只针对请求 job；
- normal/cancel/timeout/interrupted/failed 使用一个 terminal transition helper；
- sync turn 通过 shared lease；rename/delete 只检查 owner session，不无条件抢占 workspace。

### 绿灯与审查

运行 `tests/test_web.py`。重点审查 lock acquisition/release 的所有异常路径、terminal 幂等、
active pointer compare-before-delete、消息/event redaction 与 crash 中间态。

## Task 6：HTTP/SSE 与 CLI Adapter

### HTTP 红灯/实现

在现有参数化 route/validation 测试中加入 start timeout、cancel、resume、SSE after：

- timeout bool/边界、job/message 类型、unknown/invalid status 均为稳定 400 JSON；
- cancel 重复为 200 且状态稳定；
- `after` 缺省 0，负数/非整数 400；SSE id/事件从 cursor 严格递增；
- Host/Origin 对新 POST 与既有 route 同样生效；安全响应头/no-store 不变。

`server.py` 只解析/委派，不复制 lifecycle 规则。

### CLI 红灯/实现

扩展 `tests/test_cli.py`：

- `agent run/chat --timeout-seconds` 边界；
- deadline 输出 status/error/terminal_reason/summary 并返回非零；
- chat timeout/cancel turn 持久化后可继续输入；输入阶段 Ctrl+C 仍退出，执行阶段 Ctrl+C 只取消本 turn；
- 两个 CLI/Web owner 竞争时 busy，无模型或 Tool 调用；lease 在所有异常/关闭路径释放。

CLI 只创建 control/lease 并消费 `RunResult`，不实现第二套 stop 状态机。

### 绿灯与审查

运行 `tests/test_web.py tests/test_cli.py tests/test_chat.py`；确认旧命令帮助与默认行为兼容。

## Task 7：React cancel、cursor reconnect 与安全 resume

### 红灯

扩展现有 Vitest：

- API client 的 start timeout、cancel、resume payload；
- EventSource 首次 `after=0`，收到 sequence 后重连用 `last+1`，重复/乱序仍丢弃；
- `cancelled`、`timed_out`、`interrupted` 都是 terminal，reducer 文案和 phase 不冒充 normal final；
- active turn 显示停止按钮且只发一次 cancel；approval busy 与 cancel 状态可区分；
- settle 后 composer 恢复；异常终态的下一条消息调用 resume，normal final 调 start；
- sessionStorage 刷新恢复仍使用同 job，不产生第二个 turn。

### 实现

只扩展既有 API Adapter、SSE subscriber、chat reducer 和 App；不新增状态库、router 或组件框架。
停止操作必须有可访问名称/焦点状态；窄屏和 reduced-motion 不回归。

### 绿灯与审查

运行 typecheck、lint、UI policy、Vitest 和目标 Playwright。检查 event listener/cleanup、double settle、
stale closure、按钮竞态和 session 切换。

## Task 8：真实服务、可见浏览器与恢复演练

### Playwright 实服

扩展专用真实 Python 服务测试，使用 D 盘 wrapper workspace：

- FakeLLM normal final；
- approval 等待 cancel 后文件不存在、terminal 持久化；
- 允许命令的长 Python 父/子进程 cancel 后 PID 均消失；
- 页面刷新从 durable cursor 恢复；
- 通过 fixture 停止/重启服务后 active job 成为 interrupted，用户新消息 resume，不重放旧 Tool；
- console/request failure/意外 4xx/5xx 为 0，服务停止后端口/进程/temp/control 清理。

如果 wrapper 无法在同一测试安全重启，新增一个只负责 restart 的 served config/script；不得把生产
服务控制 endpoint 暴露给浏览器。

### 可见浏览器

真实 Workbench：发起可控长任务 → 点击停止 → 查看 cancelled 历史 → 刷新 → 新消息 resume →
normal final；再打开 Runs 看到 cancel run summary。记录 console warning/error 和网络失败。

### 审查

确认测试不读私有 runtime 状态、不写仓库、不使用真实危险命令、不靠固定 sleep 判断 PID。

## Task 9：全量、wheel、提交与提交后复验

### 全量门禁

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp <D唯一目录>\pytest
Set-Location frontend
npm run check
node --test scripts/start-served-workbench.test.mjs
npm run test:e2e:served
Set-Location ..
.\.venv\Scripts\agent.exe release doctor --cwd .
git diff --check
```

另在 D 盘构建 wheel，比较新增 core Module、`server.py`、`chat_runtime.py` 和完整 preview bundle 的
路径/字节；从 wheel 启动服务跑 cancel/resume smoke。

### 精确提交

按逻辑拆为至多三次提交：core/process、runtime/API/CLI、React/docs。逐文件 `git add --`，每次
检查 cached name/status/check；绝不使用 `git add -A`。不 push、不 Ready、不 merge。

### 提交后复验

从最终提交在 D 盘 detached worktree 执行 Python 全量、前端全量、真实 served E2E 和 wheel smoke；
删除精确 worktree/temp 后，verification 写入 commit/tree/测试/进程清理证据，再作只含文档状态的
验证提交。

## 完成门

- core stop 永远进入 finalize；子进程树实际停止；OS lease 跨进程生效；
- normal/cancelled/timed_out/interrupted/failed 各只有一个 durable terminal；
- resume 只消费新 message，不重放 Tool；CLI/HTTP/React 共用核心语义；
- 所有聚焦、全量、wheel、真实服务、可见浏览器和提交后复验通过；
- D 盘临时目录、进程、端口和 lock owner 无残留；无关 handoff 未触碰；
- verification 只声明 3A 完成，下一步为 3B Memory，不提前声明 Phase 3 完成。

## 计划五轴审查

1. 正确性：先证明 finalize 和进程树停止，再做 durable/store/UI；crash、worker error、重复 cancel、
   重复 restart 和旧 session migration 都有门禁。
2. 可读性：九个 Task 各只有一个层级责任，红灯、实现、绿灯和停止条件相邻。
3. 架构：RunControl/Lease 是 CLI、Web、后续 Automation 的真实共享 seam；runtime 仍只有一个
   job 状态机，server/React 只做 Adapter。
4. 安全：跨进程 lease、redirect/reparse、redaction、Tool 不重放、进程树清理、Origin 与审批均测试。
5. 性能：无队列/数据库/扫描；event O(1) append，job 按 id load，SSE 从 cursor 续读。

审查修正：将 CLI/Web 的竞争纳入同一 OS lease；将 sync turn 与 session rename/delete 区分；
将 Ctrl+C、worker error、event 中间坏行、active pointer compare-delete、wheel 实服和提交后重建加入
门禁。结论：通过，无未解决 finding，可以实施 Task 1。
