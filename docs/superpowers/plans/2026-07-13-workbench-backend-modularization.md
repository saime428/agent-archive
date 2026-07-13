# 计划：Workbench 后端模块化——建立 `ChatRuntime` seam

日期：2026-07-13
状态：已执行（自动门禁与真实 DeepSeek Workbench 验收通过）
设计：`docs/superpowers/specs/2026-07-13-workbench-backend-modularization-design.md`

## 实施约束

- 本轮只拆分 `src/agent/web/server.py` 的既有职责；除已批准的五项运行期变化外，不修改 URL、HTTP method、payload、SSE event、审批、文件、run 或前端行为。
- 五项运行期变化仅为：registry runtime-local、三个 runtime 入口统一 prune、非法的新 session id 在创建 job 前同步失败、list/create/load/save/delete 拒绝 session storage reparse redirection、load 拒绝 JSON/目录 session id mismatch。
- `ChatRuntime` 的运行期 interface 固定为 `start`、`poll`、`decide`；不新增 `get_job`、`exists`、`close`、后台 reaper、thread adapter 或 DTO。
- 允许的领域依赖只有 `chat_runtime.py -> chats.py -> runs.py` 与 `settings.py -> runs.py`；`files.py` 不依赖其他 web 领域模块，任何领域模块都不得导入 `server.py`。
- 不新增 `web/utils.py`、router、controller、service、repository、依赖注入框架、Web 框架、asyncio、依赖或 `tests/web/` 目录。
- 不新增 SSE 自动重连、`Last-Event-ID`/`after` 续传、前端事件去重或 job 取消协议；现有 event `id` 只标识本次流中的 sequence。
- builder 搬迁后不从 `server.py` re-export；生产保留 interface 只有 `serve_workbench`、`create_workbench_handler`、`static_file_path`。
- 每个 Task 都把“移动 + server 接线 + 测试 import”作为一个原子提交；提交前必须通过该 Task 的聚焦测试与 `git diff --check`。
- 执行 Task 1 前运行 `git rev-parse HEAD` 并记录为 `<implementation-base>`，另确认 `git merge-base HEAD 679e2ff` 等于 `679e2ff`，把该 PR #7 head 记为 `<old-base>`。实现 commit 检查用 `<implementation-base>`，完整分支 scope 检查用 `<old-base>`。只按各 Task 的精确文件列表暂存；`.superpowers/`、`docs/main.pdf`、`else/`、`pytest-output.txt` 等无关未跟踪文件不得加入提交。
- 所有 pytest 都显式使用 `--basetemp D:\CodexScratch\agent-workbench-backend\pytest`，不把测试临时文件放到 C 盘；`--basetemp` 不会创建其 parent，因此执行第一条 pytest 前必须显式创建并核对 `D:\CodexScratch\agent-workbench-backend`。最终门禁后再次核对绝对路径并清理该目录。
- PR #7 未合并时只做本地实现与验证，不创建 stacked PR；独立 PR 的发布门禁见文末。

固定 runtime 构造与 interface：

```python
runtime = ChatRuntime(
    workspace,
    llm_factory=make_llm,
    clock=time.monotonic,
    approval_timeout=APPROVAL_WAIT_TIMEOUT_SECONDS,
    job_ttl=CHAT_JOB_TTL_SECONDS,
)

runtime.start(message=message, session_id=session_id)
runtime.poll(job_id, after=after, timeout=timeout)
runtime.decide(job_id=job_id, approve=approve)
```

执行 Task 1 前先初始化测试 scratch root；若 `D:\CodexScratch` 不可用，按项目约定暂停并请求用户选择替代位置：

```powershell
$scratch = 'D:\CodexScratch\agent-workbench-backend'
New-Item -ItemType Directory -Path $scratch -Force | Out-Null
if ((Resolve-Path -LiteralPath $scratch).Path -ne $scratch) { throw "Unexpected scratch path: $scratch" }
```

## Task 1：用真实 HTTP 固定 adapter 派发

**Files:**

- Modify: `tests/test_web.py`

**先写 characterization tests：**

在测试文件内增加一个最小 HTTP helper：使用标准库 `ThreadingHTTPServer`、随机端口、后台线程和 `http.client.HTTPConnection`，结束时调用 `shutdown()`、`server_close()` 并 join 线程。不得引入 `requests` 或修改生产 handler signature。

用 sentinel builders 记录 positional/keyword 参数并返回唯一 JSON 标记，参数化覆盖以下显式分支：

| Method | Path | 当前目标 |
| --- | --- | --- |
| GET | `/api/health` | `build_health_payload(root)` |
| GET | `/api/config` | `build_config_payload(root)` |
| GET | `/api/chats` | `build_chats_payload(root)` |
| GET | `/api/tools` | `build_tools_payload()` |
| GET | `/api/runs` | `build_runs_payload(root)` |
| GET | `/api/files?path=src` | `build_files_payload(root, "src")` |
| GET | `/api/file?path=README.md` | `build_file_payload(root, "README.md")` |
| GET | `/api/diff?path=a&snapshot=b` | `build_diff_payload(root, "a", "b")` |
| GET | `/api/chats/chat_1` | `build_chat_payload(root, "chat_1")` |
| GET | `/api/runs/run_1` | `build_run_detail_payload(root, "run_1")` |
| POST | `/api/chat/turn` | `build_chat_turn_payload(root, body)` |
| POST | `/api/chat/start` | 当前 `build_chat_start_payload(root, body)` |
| POST | `/api/chat/approval` | 当前 `build_chat_approval_payload(body)` |
| POST | `/api/chat/rename` | `build_chat_rename_payload(root, body)` |
| POST | `/api/chat/delete` | `build_chat_delete_payload(root, body)` |
| POST | `/api/config` | `build_save_config_payload(root, body)` |
| POST | `/api/snapshot/restore` | `build_restore_snapshot_payload(root, body)` |
| POST | `/api/file/save` | `build_save_file_payload(root, body)` |

另锁定以下 adapter 行为：

1. 已知 job 的 `/api/chat/events` 返回 `200 text/event-stream`；此时临时 patch 当前 `_get_chat_job` 与 `build_chat_events_payload`，令首批 payload 为 `done=True, events=[]`。测试只检查 status/header 后主动关闭 client，不等待 keep-alive body EOF。
2. 不存在的 job 在 SSE 响应头发送前返回现有 JSON `400` 与 `Unknown chat job: ...`。
3. `/` 继续走 static fallback；未知 POST 继续返回 JSON `404`。
4. 缺少 JSON body、chat start 缺少 message、approval 的 `approve` 非 bool 时保持现有 `400` 文案。
5. chat start 的非空 message 在派发前保持现有 `strip()` 规范化；空字符串 `session_id` 仍等同于未指定并创建新会话。
6. 用单个异常 sentinel 按 handler 当前的 method-specific catch 分支参数化：GET 锁定 `ConfigError`/`ValueError`/`SandboxError -> 400`、`RunStoreError -> 404`、`OSError -> 500`；POST 锁定 `ConfigError`/`ValueError -> 400`、`DeepSeekError -> 502`、`OSError -> 500`。非法 JSON 仍返回 `Invalid JSON body: ...` 的 `400`。不要断言当前不存在的 POST `SandboxError`/`RunStoreError` 或 GET `DeepSeekError` 映射，也不为每条业务路由复制异常测试。

这些是重构前必须通过的特征测试，不伪造预期失败。

**验证与提交：**

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_web.py -q
git diff --check
git add -- tests/test_web.py
git diff --cached --check
git commit -m "test: characterize Workbench HTTP routing"
```

## Task 2：收口 session storage path、identity 与删除 ownership

**Files:**

- Modify: `src/agent/core/chat.py`
- Modify: `src/agent/web/server.py`
- Modify: `tests/test_chat.py`
- Modify: `tests/test_ui.py`
- Modify: `tests/test_web.py`

**先写失败测试：**

1. 扩展 `test_conversation_state_rejects_unsafe_session_ids`：`ConversationState.create(tmp_path, session_id="../runs")` 在构造时即抛出现有 session-id `ValueError`。
2. 在 redirection 创建前构造一个合法 state，随后分别让 `.agent/chats`、session directory 或 `session.json` 成为 symlink/junction/reparse path：`ConversationState.list`、`create`、`load`、已有 state 的 `save` 与 `delete` 按适用路径都拒绝，目标 `session.json`/marker 不枚举、不读取、不改写、不删除。即使目标仍在 workspace/chats 内也拒绝，防止 alias 删除或串写；仅当平台明确拒绝创建链接时 skip 对应用例。
3. 在 `chat_a/session.json` 写入合法结构但声明 `session_id="chat_b"`，断言 `ConversationState.load(..., "chat_a")` 立即失败，后续 turn 不运行，`chat_b` marker 不变；`ConversationState.list` 把该项视为损坏数据跳过，不让单个 mismatch 阻断整个列表。
4. `ConversationState.delete` 可删除包含损坏 `session.json` 的正常会话目录，证明删除不解析 JSON。
5. `ConversationState.list` 仍跳过一个损坏的普通 session JSON 与非法名称目录并返回其他合法会话，保持当前列表容错；但第 2 项的 `_SessionPathError` 必须向上抛出，不能被同一容错分支吞掉。
6. `ConversationState.delete` 对不存在会话保持 `Chat session not found: <id>`；对 `../runs` 或 reparse path 保持 `session_id resolves outside chats.`。
7. `build_chats_payload` 只投影 `ConversationState.list`；`build_chat_delete_payload` 的成功 payload 仍是 `{"status": "ok", "session_id": ..., "deleted": True}`，既有错误文案不变。
8. 通过真实 HTTP POST `/api/chat/start` 发送 `{"message": "x", "session_id": "../runs"}`，断言同步 JSON `400`；把 `server.make_llm` patch 成一旦调用就失败，证明没有启动 LLM worker。

先运行：

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_chat.py tests/test_ui.py tests/test_web.py -q
```

Expected：create 提前校验、统一 no-redirection、持久化 id mismatch、`delete` 与 HTTP fail-fast 用例失败；既有 chat payload 用例通过。

**最小实现：**

1. 增加 core-private `_SessionPathError(ValueError)` 与 `_chats_root(cwd)`：resolve cwd 后构造 lexical `.agent/chats`，比较 root 的 `resolve()` 结果与 lexical path 的 `normcase` 形式；解析抛出 `OSError`/`RuntimeError` 或比较不同时统一 fail closed 为 `_SessionPathError`。该 subtype 只供 core 内部区分边界失败，外部仍看到既有 `ValueError` contract。
2. 扩展 `_session_path`：保留现有 id 正则，非法 id 也抛 `_SessionPathError`；复用 `_chats_root` 构造 lexical `<session_id>/session.json`，再比较整条 path 的 `resolve()` 结果与 lexical path 的 `normcase` 形式；解析失败或路径不同时抛同一 subtype，从而覆盖 session directory 与文件级 redirection。不要为同一目的再叠加 commonpath helper。
3. 新增 `ConversationState.list(cwd) -> list[ConversationState]`：只从 `_chats_root` 枚举目录，先忽略不符合 session id 正则的目录，再逐项调用 `load`；`_SessionPathError` 必须重新抛出，plain `ValueError`/JSON/字段/读取错误继续只跳过该 session。`build_chats_payload` 只排序、截断和投影返回的 states。
4. `ConversationState.create` 生成或接受 session id 后调用 `_session_path(root, session_id)` 再构造 state；既有 `load`、`save` 已调用该 helper，因此自动共享同一边界，不复制检查。
5. `ConversationState.load` 解析 JSON 后先要求原始 `session_id` 是 string 且与请求 id 完全相同，再构造 state；不把 mismatch 强制改写成请求值，也不延迟到 save。
6. 新增 `ConversationState.delete(cwd, session_id) -> None`：调用 `_session_path`，把 `_SessionPathError` 翻译为当前删除接口的 `session_id resolves outside chats.`，然后只对返回 canonical path 的 parent 检查 `is_dir()` 并 `shutil.rmtree()`；不调用 `load()`。
7. `_load_or_create_chat_state` 改为先 `ConversationState.load`，只捕获 `FileNotFoundError` 后 `create`；不得在 core 边界检查前自行 `is_file()`。`server.py::build_chat_delete_payload` 只做 request 字段校验、调用 `delete` 并返回原 payload；移除 Web 中会话路径拼接与 `shutil` 使用。

不得引入 shared path util、session lock、active-job 查询或原子写改造。no-redirection 检查只覆盖操作时已存在的 reparse path；同机并发换路径与 hard link alias 明确延期，不在注释或测试中夸大为已解决。

**验证与提交：**

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_chat.py tests/test_ui.py tests/test_web.py -q
git diff --check
git add -- src/agent/core/chat.py src/agent/web/server.py tests/test_chat.py tests/test_ui.py tests/test_web.py
git diff --cached --check
git commit -m "fix: centralize chat session lifecycle"
```

## Task 3：先提取可复用的 run 投影

**Files:**

- Create: `src/agent/web/runs.py`
- Modify: `src/agent/web/server.py`
- Modify: `tests/test_ui.py`

**先锁定现有 contract：**

移动前先运行现有 run 与消费方测试：

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_ui.py -q
```

Expected：通过，作为纯移动基线。

**最小实现：**

一次移动以下完整簇，不复制实现：

- `build_runs_payload`、`_build_run_list_item`、`_summary_field`；
- `build_run_detail_payload`；
- `_build_task_review`、`_build_workflow_hints`、`_build_patch_review`、`_build_failure_recovery`；
- `_failure_from_tool_call`、`_replay_step_from_tool_call`；
- 将 `_build_failure_summary`、`_build_run_replay` 改名为内部共享 interface `build_failure_summary`、`build_run_replay`。

`server.py` 从 `runs.py` 导入四个非下划线函数。显式 run 路由继续调用两个 payload builder；尚未搬走的 `_build_workspace_risk` 与 `_turn_process` 分别切换为 `build_failure_summary`、`build_run_replay`，随后删除 server 中两份旧定义。不得让 `runs.py` 导入 `server.py`。

`tests/test_ui.py` 只把 run builder 的 import 改到 `agent.web.runs`；health/chat 消费测试继续间接锁定两个共享投影的 payload。

**验证与提交：**

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_ui.py tests/test_web.py -q
git diff --check
git add -- src/agent/web/runs.py src/agent/web/server.py tests/test_ui.py
git diff --cached --check
git commit -m "refactor: extract Workbench run projections"
```

## Task 4：提取无状态 chat 逻辑与响应投影

**Files:**

- Create: `src/agent/web/chats.py`
- Modify: `src/agent/web/server.py`
- Modify: `tests/test_ui.py`

**先锁定现有 contract：**

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_ui.py tests/test_web.py -q
```

Expected：通过。

**最小实现：**

移动以下 chat 簇：

- `build_chats_payload`、`build_chat_payload`、`build_chat_turn_payload`、`build_chat_rename_payload`、`build_chat_delete_payload`；
- list/title/turn projection helpers；
- repair/display/friendly-summary/process/thinking/public-action/fallback helpers；
- `_approve_once_handler`；
- 将 `_load_or_create_chat_state`、`_chat_turn_response` 改为供 runtime 使用的 `load_or_create_chat_state`、`build_chat_turn_response`。

`chats.py` 从 `runs.py` 导入 `build_run_replay`；不得导入 `server.py`。同步 `build_chat_turn_payload` 与仍暂留 server 的异步 worker 都调用同一 state/response helper。

`server.py` 立即从 `chats.py` 导入 builders 与两个 helper，删除已移动实现；异步 `_ChatJob`、registry、start/poll/approval、worker 与 batching 此 Task 暂不移动。

`tests/test_ui.py` 把同步 chat/list/rename/delete builders 改从 `agent.web.chats` 导入；对应同步测试的 `make_llm` monkeypatch 改为 `agent.web.chats.make_llm`。异步 job 测试在 Task 5 前仍 patch `agent.web.server.make_llm`，不得提前混改。

**验证与提交：**

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_ui.py tests/test_web.py tests/test_chat.py -q
git diff --check
git add -- src/agent/web/chats.py src/agent/web/server.py tests/test_ui.py
git diff --cached --check
git commit -m "refactor: extract Workbench chat projections"
```

## Task 5：把异步 job 生命周期封装进 `ChatRuntime`

**Files:**

- Create: `src/agent/web/chat_runtime.py`
- Modify: `src/agent/web/server.py`
- Modify: `tests/test_web.py`
- Modify: `tests/test_ui.py`

**先写 interface 测试：**

将 `tests/test_web.py` 现有 TTL、tagged chunks、tiny-chunk batching 测试改为只调用 `ChatRuntime`。把 `tests/test_ui.py` 中四组异步 start/approval/timeout 测试迁移或改写到 `tests/test_web.py`，删除重复的 builder/private-state 断言。

通过 interface 覆盖：

1. event sequence 从 0 开始；`poll(after=n)` 返回 `events[n:]`，`next` 为偏移量。
2. start、poll、decide 三个入口都能清理已完成且超过 TTL 的 job；活跃 job 不清理。
3. 两个 runtime 的 registry 互不相见，另一实例 poll 返回现有 unknown-job 文案。
4. tagged stream chunk 与 64-char batching 保持；最终拼接文本和 `chunk_chars` 不变。
5. pending approval 的批准、拒绝、超时、提前/重复/late decision 与 reason 字段保持。late decision 与 worker timeout 争夺同一 condition lock：测试只断言迟到决定必然抛 `ValueError` 且动作不执行，不跨竞态断言单一错误字符串；无竞态分支继续断言现有精确文案。
6. 看到 final/error 后继续 poll，最终必须得到 `done=True`；测试不把 final event 当完成屏障。
7. 无效 config、非法/reparse session path 与持久化 id mismatch 在 start 阶段同步失败且不调用 `llm_factory`；factory/provider/turn 异常产生 `error` event 并最终 done。
8. monkeypatch stdlib `threading.Thread` 为 start 时抛错的最小 fake，并固定 job id；`start` 重新抛错后，通过 public `poll` 断言该 id unknown，证明 registry 已回滚。
9. 负数 `after` 保持 `ValueError`，负数 timeout 保持 nonblocking；无测试访问 `_ChatJob`、registry、lock 或 condition。

测试时钟分工固定：manual/frozen clock 只覆盖 `timeout=0` 或不进入等待的 timestamp、deadline、elapsed 与 TTL prune；会进入正数 `Condition.wait(...)` 的 poll/approval 用例使用真实 `time.monotonic` 加极短 `approval_timeout`/poll timeout，并以 event/condition 同步线程。不要为了测试再注入 wait、sleep 或 condition adapter。

更新 Task 1 的 HTTP matrix：handler 创建前 monkeypatch `server.ChatRuntime` 为记录 typed 调用的 fake runtime；start row 用 `{"message": "  hi  ", "session_id": ""}` 断言 `start(message="hi", session_id="")`，并由 fake runtime 返回新会话 payload；approval row 断言 `decide(job_id=..., approve=...)`。SSE row 断言第一次 `poll(job_id, after=0, timeout=0)` 发生在 `200` 响应头前并复用含一个 event、`done=True` 的首批 payload，响应为 `Connection: close`，event 写出后不再 poll，client 能读到 EOF；另一个 row 让首批 `done=False`、第二次 poll 抛 unknown，断言已发送的 SSE `200` 关闭连接且不追加 JSON 响应。

SSE adapter 不读取 `Last-Event-ID`，也不接受续传 offset；前端现有 error handler 继续关闭 `EventSource`。本 Task 不修改静态资源来增加重连或事件去重。

Task 2 的非法 session HTTP 用例不再 patch 已删除的 `server.make_llm`：handler 创建前把 `server.ChatRuntime` patch 为一个构造真实 `ChatRuntime`、但注入 fail-fast `llm_factory` 的 factory，继续证明 session 校验发生在 factory 调用前。

先运行：

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_web.py tests/test_ui.py -q
```

Expected：新 interface import/断言失败，现有 payload/static contract 通过。

**最小实现：**

1. 在 `chat_runtime.py` 移入常量、精简 `_ChatJob`、runtime-local registry、locks/conditions、event append、prune、worker、approval wait 与 stream batching。
2. `_ChatJob` 只保留 `job_id`、`started_at`、events、condition、done/completed_at 与 approval 状态；删除 workspace/session/message/result/error 死字段。
3. 所有显式 timestamp、deadline、elapsed 与 TTL 读取使用 injected `clock`；三个 public 方法入口先 prune。`Condition.wait(remaining)` 保持标准库真实阻塞，不新增 wait/sleep seam；冻结的 fake clock 不得用于正数等待。无后台线程负责 prune，无 `close()`。
4. `start` 同步加载 secrets/config/state，注册 job、追加 `chat_started` 后才启动 daemon worker；`thread.start()` 抛错时在 registry lock 下删除同一 job 后重新抛出。worker 内调用 injected `llm_factory`、`ChatSession.run_turn` 与 `chats.build_chat_turn_response`。
5. `poll` 与 `decide` 只返回 dict copy/payload，不暴露 job。
6. `create_workbench_handler` closure 创建一个 runtime。HTTP adapter 校验 raw message/session/job_id/approve，向 `start` 传入一次 `strip()` 后的非空 message；runtime 不重复边界校验，空字符串 session id 继续由现有 load-or-create 语义视为新会话。删除旧的 async payload builders。
7. `_send_sse` 先 nonblocking poll，成功后才进入 SSE 响应阶段；此时先设 `self.close_connection = True`，发送 `Connection: close` 而不是当前自相矛盾的 `keep-alive`，并由 `_send_sse` 自己捕获 header/body `OSError`。后续 poll 的 unknown/expired 也只结束连接，不能回到外层发送 JSON。每批 events 写完后若 `done=True` 立即终止，不额外 poll 空批次；无 Content-Length 的 SSE 始终以 socket EOF 收口。断连不取消 worker。
8. 保留现有审批锁内分支顺序：`decide` 先看到 deadline 过期时写入 `timed_out` 并返回 `chat approval has expired.`；worker timeout 先清理 pending 或 job 已完成时，迟到 `decide` 分别沿用 no-pending/already-finished 错误。本轮不增加 approval 终态字段来统一竞态文案。

**验证与提交：**

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_web.py tests/test_ui.py tests/test_chat.py tests/test_cli.py -q
git diff --check
git add -- src/agent/web/chat_runtime.py src/agent/web/server.py tests/test_web.py tests/test_ui.py
git diff --cached --check
git commit -m "refactor: encapsulate Workbench chat runtime"
```

## Task 6：提取文件、diff 与 snapshot 逻辑

**Files:**

- Create: `src/agent/web/files.py`
- Modify: `src/agent/web/server.py`
- Modify: `tests/test_ui.py`

**先锁定现有 contract：**

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_ui.py -q
```

Expected：通过。

**最小实现：**

一次移动：

- `build_files_payload`、`build_file_payload`、`build_save_file_payload`、`build_diff_payload`、`build_restore_snapshot_payload`；
- `_read_sandbox`、`_display_path`、snapshot resolve/text/metadata/JSON helpers；
- restore target、diff text、Workbench file-save trace、normalized `_is_within`。

`_read_sandbox` 只属于 files，不导入 `settings.py`。保留 workspace/external-read、snapshot 必须位于 `.agent/runs/<run>/snapshots`、metadata、binary、restore 与审计格式的所有现有分支和文案。

`server.py` 只导入五个 file payload builders；`tests/test_ui.py` 把对应 imports 改到 `agent.web.files`。HTTP route matrix 继续 monkeypatch server 已导入的 builder 名称，不改生产 interface。

**验证与提交：**

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_ui.py tests/test_web.py -q
git diff --check
git add -- src/agent/web/files.py src/agent/web/server.py tests/test_ui.py
git diff --cached --check
git commit -m "refactor: extract Workbench file payloads"
```

## Task 7：提取 health、config 与 tools 逻辑

**Files:**

- Create: `src/agent/web/settings.py`
- Modify: `src/agent/web/server.py`
- Modify: `tests/test_ui.py`
- Modify: `tests/test_web.py`

**先锁定现有 contract：**

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_ui.py tests/test_web.py -q
```

Expected：通过。

**最小实现：**

移动：

- `build_health_payload`、provider notice、settings readiness；
- workspace risk、git status、memory review 及其 payload helpers；
- `build_config_payload`、`build_save_config_payload`、project TOML read/validate/dump helpers；
- `build_tools_payload`。

`settings.py::_build_workspace_risk` 从 `runs.py` 导入 `build_failure_summary`；不得复制 failure 判定，也不得导入 files/chats/server。

`server.py` 只导入 health/config/tools builders。`tests/test_ui.py` 和 `tests/test_web.py` 把 settings builders 与 monkeypatch 路径改到 `agent.web.settings`；保持 secret 不泄露、provider readiness、approval=never 浏览器拒绝、TOML escaping、native_tools 与 tool catalog 断言。

**验证与提交：**

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_ui.py tests/test_web.py tests/test_cli.py -q
git diff --check
git add -- src/agent/web/settings.py src/agent/web/server.py tests/test_ui.py tests/test_web.py
git diff --cached --check
git commit -m "refactor: extract Workbench settings payloads"
```

## Task 8：收窄 server、交叉审查与最终门禁

**Files:**

- Modify: `src/agent/web/server.py`（仅在仍有陈旧 import/helper 时）
- Amend: `docs/superpowers/specs/2026-07-13-workbench-backend-modularization-design.md`
- Amend: `docs/superpowers/plans/2026-07-13-workbench-backend-modularization.md`
- Test only if a real contract requires it: `tests/test_cli.py`

**结构检查：**

1. `server.py` 只保留 serve/handler、显式路由、query、JSON/SSE/static 传输和异常到 HTTP 状态码映射。
2. `server.py` 不再定义 `build_*_payload`、`_ChatJob`、registry、worker 或领域 helper。
3. 测试不再从 `agent.web.server` 导入 builders，也不访问 runtime 私有状态。
4. `runs.py` 不导入其他 web 领域模块；chats/settings 只按批准方向导入 runs；runtime 只按批准方向导入 chats；files 独立。
5. 不新增 facade、`__all__` 样板、route table、共享 utils、依赖或前端改动。

可用以下只读检查辅助审查；negative grep 应无输出：

```powershell
rg -n "^def build_|^class _ChatJob|_CHAT_JOBS|_run_chat_job" src/agent/web/server.py
rg -n "from agent\.web\.server import .*build_|server\._CHAT_|server\._ChatJob" tests
rg -n "agent\.web\.server" src/agent/web/chat_runtime.py src/agent/web/chats.py src/agent/web/runs.py src/agent/web/files.py src/agent/web/settings.py
rg -n --glob '*.py' "\.agent.*chats|session\.json|shutil\.rmtree" src/agent/web
```

**自动门禁：**

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_web.py tests/test_ui.py tests/test_chat.py tests/test_cli.py tests/test_docs.py -q
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest -q
python -m agent.cli doctor
git diff --check
git diff --check <implementation-base>
git diff --check <old-base>
git diff --name-only <old-base>
git log --oneline <old-base>..HEAD
git status --short
```

**真实 Workbench：**

1. 页面加载 health/config/files/chats/runs；
2. 发起 streaming chat，确认 sequence、thinking/content/args batching 和 final 展示；
3. 记录当前本地 Workbench 配置，确认 `sandbox=workspace-write`、`approval=risky-confirm`、`dry_run=false`；明确要求执行无写入的 `python -c "print('workbench-approval-ok')"`，审批卡保留 capability reason，批准后同一 turn 完成；
4. 检查对应 trace 保留 approval reason、命令结果与 `workbench-approval-ok` stdout，然后恢复原本地配置；
5. 主动断开一个 SSE client，确认 worker 不取消且 server 仍响应新的 health 请求；
6. 使用不存在的 job 请求 events，确认返回 JSON `400` 而非已发送的 SSE `200`；
7. 无可用 provider key 时明确记录环境阻塞，不把 fake/static 测试冒充真实 provider 验收。

真实 Workbench 验收完成后把 spec 状态改为“已实现”，plan 状态改为“已执行”，并记录实际验证结果。若缺少 provider key 等外部条件，只能记录“实现与自动门禁通过，真实验收阻塞”，不得标记全部完成，也不得 push/open PR；只有真实验收补齐或用户明确豁免该门禁后才能发布。

**验证与提交：**

```powershell
python -m pytest --basetemp D:\CodexScratch\agent-workbench-backend\pytest tests/test_docs.py -q
git diff --check
git add -- src/agent/web/server.py docs/superpowers/specs/2026-07-13-workbench-backend-modularization-design.md docs/superpowers/plans/2026-07-13-workbench-backend-modularization.md
git diff --cached --check
git commit -m "chore: close Workbench backend modularization"
git diff --check <old-base>..HEAD
git diff --name-only <old-base>..HEAD
git status --short
$scratch = (Resolve-Path 'D:\CodexScratch\agent-workbench-backend').Path
if ($scratch -ne 'D:\CodexScratch\agent-workbench-backend') { throw "Unexpected scratch path: $scratch" }
Remove-Item -LiteralPath $scratch -Recurse -Force
```

若 `server.py` 无额外 cleanup，Task 8 仍以 spec/plan 的实际验收记录形成非空收口提交，不回写或重排已经通过的 Task 7 commit。

## 执行结果（2026-07-13）

- Task 1-7 已按原子边界提交：HTTP characterization、ConversationState storage/identity、runs、chats、ChatRuntime、files、settings 均各自通过对应聚焦门禁后提交。
- Task 8 负向扫描无输出：`server.py` 不再定义领域 builder/job/worker，测试不导入 server builders 或访问 runtime 私有状态，领域模块没有反向导入 `server.py`，direct chat storage 只由 `ConversationState` 拥有。
- 自动门禁结果：指定聚焦套件 223 passed、1 skipped；全量套件 573 passed、1 skipped；修改范围 Ruff、`git diff --check 944673f..HEAD` 与 `git diff --check 679e2ff..HEAD` 均通过。全仓 Ruff 另报告 5 个本分支未修改的既有问题，不属于本计划 diff。
- doctor 确认 DeepSeek key 可用，且实际配置满足 `sandbox=workspace-write`、`approval=risky-confirm`、`dry_run=false`。
- 真实 Workbench run `run_20260713_214907_523487` 验证页面/API、连续 SSE sequence、`thinking/content/args` batching、final、完整 run-command capability reason、同 turn 审批续跑、`workbench-approval-ok` stdout 与 trace/summary。
- 主动断开 SSE 后 worker 未取消且 health 返回 200；不存在 job 返回 JSON 400；本地 config 验收前后字节一致，无需恢复写入。

## 独立 PR 发布门禁

实现与本地验收完成后先检查：

```powershell
gh pr view 7 --json state,isDraft,baseRefName,headRefName,mergeStateStatus,url
```

- PR #7 未合并：停止在本地已验证分支，不 push/open backend PR。
- PR #7 已合并：fetch 远端并从 `baseRefName` 确认 `<merged-target>`；保证 tracked worktree clean，确认 `<old-base>` 仍为 `679e2ff`，然后执行 `git rebase --onto <merged-target> <old-base> codex/v3.1-workbench-backend`。不得用普通 `git rebase <merged-target>`，否则 squash/rebase merge 可能把 PR #7 commits 重放；不得使用 `reset --hard`。
- rebase 后以 `<merged-target>` 而非旧 `<implementation-base>` 重新运行 Task 8 全部自动门禁与真实 Workbench 验收，并检查 `git log --oneline <merged-target>..HEAD`、`git diff --check <merged-target>..HEAD`、`git diff --name-only <merged-target>..HEAD` 只含本轮 spec、plan、backend modules 与测试。
- 真实验收成功（或用户明确豁免）后才 push `codex/v3.1-workbench-backend` 并创建一个独立 PR；PR body 写明 scope、五项有意行为变化、thread/SSE 失败路径收口、测试证据、真实 Workbench 结果和并发 session lock 的明确延期。
- 若 PR #7 无法合并或 rebase 需要改变已批准设计，暂停发布并请用户重新决策，不静默改为 stacked PR。

## Plan 对抗审查记录

2026-07-13 已完成。剩余决策按用户授权统一采用推荐答案，审查结论如下：

1. 保留 injected `clock`，但不新增 wait/sleep/condition adapter；fake clock 只进非阻塞路径，真实阻塞测试用短时限。
2. 保留 approval timeout/late-decision 的 lock-winner 文案，不为统一竞态错误增加终态字段。
3. HTTP adapter 独占 message 校验与 `strip()`；runtime 接收 typed、normalized 参数，空 session id 继续表示新会话。
4. 明确 SSE 不支持自动重连或 `Last-Event-ID` replay；同时补齐 preflight 后的 transport ownership、`Connection: close`/EOF、done-with-events 终止与并发 prune 失败收口。
5. `_SessionPathError` 让列表只容错坏数据而不吞掉 storage boundary 失败；`_session_path` 拒绝完整 session storage path 的 reparse redirection，`load` 额外校验 JSON/目录 session id 一致。该保证不覆盖并发换路径或 hard link alias。
6. `thread.start()` 失败必须回滚 registry；测试通过 public interface 观察，不暴露 job 私有状态。
7. HTTP characterization 增加异常到状态码 matrix，但不为每条业务路由复制错误测试。
8. ChatRuntime 仍通过 deletion test：外部 interface 只有 `start/poll/decide`；`llm_factory` 与 `clock` 是已有生产/测试 adapter 的真实 seam，thread/condition 保持内部实现。
9. 模块依赖顺序仍为 `server -> settings/files/chats/chat_runtime/runs`、`settings -> runs`、`chats -> runs`、`chat_runtime -> chats`；无需新增 facade、utils 或 router。
10. pytest 临时目录固定到 D 盘，第一条测试前显式创建并核对 basetemp parent，门禁后清理；完整分支 scope 使用 `<old-base>`，实现增量使用 `<implementation-base>`。
11. PR #7 合并后必须用 `rebase --onto <merged-target> 679e2ff`，避免 squash merge 重放前端 commits；真实 provider 验收未完成时默认阻止发布。

明确延期不变：per-session lock、活跃 job 与 rename/delete 串行化、后台 reaper、job cancellation、SSE reconnect/replay、并行 tool calls、对抗同机并发文件系统篡改或 hard link alias。计划已达到 shared understanding，可以从 Task 1 开始执行。
