# 计划：Workbench 后端模块化——建立 `ChatRuntime` seam

日期：2026-07-13
状态：草案，待对抗审查
设计：`docs/superpowers/specs/2026-07-13-workbench-backend-modularization-design.md`

## 实施约束

- 本轮只拆分 `src/agent/web/server.py` 的既有职责；除已批准的三项运行期变化外，不修改 URL、HTTP method、payload、SSE event、审批、文件、run 或前端行为。
- 三项运行期变化仅为：registry runtime-local、三个 runtime 入口统一 prune、非法的新 session id 在创建 job 前同步失败。
- `ChatRuntime` 的运行期 interface 固定为 `start`、`poll`、`decide`；不新增 `get_job`、`exists`、`close`、后台 reaper、thread adapter 或 DTO。
- 允许的领域依赖只有 `chat_runtime.py -> chats.py -> runs.py` 与 `settings.py -> runs.py`；`files.py` 不依赖其他 web 领域模块，任何领域模块都不得导入 `server.py`。
- 不新增 `web/utils.py`、router、controller、service、repository、依赖注入框架、Web 框架、asyncio、依赖或 `tests/web/` 目录。
- builder 搬迁后不从 `server.py` re-export；生产保留 interface 只有 `serve_workbench`、`create_workbench_handler`、`static_file_path`。
- 每个 Task 都把“移动 + server 接线 + 测试 import”作为一个原子提交；提交前必须通过该 Task 的聚焦测试与 `git diff --check`。
- 执行 Task 1 前运行 `git rev-parse HEAD` 并记录为 `<implementation-base>`。只按各 Task 的精确文件列表暂存；`.superpowers/`、`docs/main.pdf`、`else/`、`pytest-output.txt` 等无关未跟踪文件不得加入提交。
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

另锁定四条 adapter 行为：

1. 已知 job 的 `/api/chat/events` 返回 `200 text/event-stream`；此时临时 patch 当前 `_get_chat_job` 与 `build_chat_events_payload`，令首批 payload 为 `done=True, events=[]`。测试只检查 status/header 后主动关闭 client，不等待 keep-alive body EOF。
2. 不存在的 job 在 SSE 响应头发送前返回现有 JSON `400` 与 `Unknown chat job: ...`。
3. `/` 继续走 static fallback；未知 POST 继续返回 JSON `404`。
4. 缺少 JSON body、chat start 缺少 message、approval 的 `approve` 非 bool 时保持现有 `400` 文案。

这些是重构前必须通过的特征测试，不伪造预期失败。

**验证与提交：**

```powershell
python -m pytest tests/test_web.py -q
git diff --check
git add -- tests/test_web.py
git diff --cached --check
git commit -m "test: characterize Workbench HTTP routing"
```

## Task 2：收口 session id 校验与删除 ownership

**Files:**

- Modify: `src/agent/core/chat.py`
- Modify: `src/agent/web/server.py`
- Modify: `tests/test_chat.py`
- Modify: `tests/test_ui.py`
- Modify: `tests/test_web.py`

**先写失败测试：**

1. 扩展 `test_conversation_state_rejects_unsafe_session_ids`：`ConversationState.create(tmp_path, session_id="../runs")` 在构造时即抛出现有 session-id `ValueError`。
2. `ConversationState.delete` 可删除包含损坏 `session.json` 的合法会话目录，证明删除不解析 JSON。
3. `ConversationState.delete` 对不存在会话保持 `Chat session not found: <id>`；对 `../runs` 保持 `session_id resolves outside chats.`。
4. 创建合法名称、但指向工作区外目录的 symlink/junction，断言删除被 containment 拒绝且外部 marker 保留；仅当当前平台明确拒绝创建链接时 skip 该平台用例。
5. `build_chat_delete_payload` 的成功 payload 仍是 `{"status": "ok", "session_id": ..., "deleted": True}`，错误文案不变。
6. 通过真实 HTTP POST `/api/chat/start` 发送 `{"message": "x", "session_id": "../runs"}`，断言同步 JSON `400`；把 `server.make_llm` patch 成一旦调用就失败，证明没有启动 LLM worker。

先运行：

```powershell
python -m pytest tests/test_chat.py tests/test_ui.py tests/test_web.py -q
```

Expected：create 提前校验、`delete` 与 HTTP fail-fast 用例失败；既有 chat payload 用例通过。

**最小实现：**

1. `ConversationState.create` 先 resolve cwd，生成或接受 session id，再调用既有 `_session_path(root, session_id)` 做一次校验后构造 state；不新增第二套正则。
2. 新增 `ConversationState.delete(cwd, session_id) -> None`。它复用 `_session_path` 校验，并把该校验的 `ValueError` 翻译为当前删除接口的 `session_id resolves outside chats.`；随后对 chats root 与 session directory 执行当前 `resolve()` + `normcase/commonpath` containment，保持 Windows drive mismatch 防护。
3. containment 通过后只检查 `is_dir()` 并 `shutil.rmtree()`；不调用 `load()`。
4. `server.py::build_chat_delete_payload` 只做 request 字段校验、调用 `ConversationState.delete` 并返回原 payload；移除该函数中的路径拼接和 `shutil` 使用。

不得引入 shared path util、session lock、active-job 查询或原子写改造。

**验证与提交：**

```powershell
python -m pytest tests/test_chat.py tests/test_ui.py tests/test_web.py -q
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
python -m pytest tests/test_ui.py -q
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
python -m pytest tests/test_ui.py tests/test_web.py -q
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
python -m pytest tests/test_ui.py tests/test_web.py -q
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
python -m pytest tests/test_ui.py tests/test_web.py tests/test_chat.py -q
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
5. pending approval 的批准、拒绝、超时、提前/重复/late decision 与 reason 字段保持。
6. 看到 final/error 后继续 poll，最终必须得到 `done=True`；测试不把 final event 当完成屏障。
7. 无效 config 与非法新 session id 在 start 阶段同步失败且不调用 `llm_factory`；factory/provider/turn 异常产生 `error` event 并最终 done。
8. 无测试访问 `_ChatJob`、registry、lock 或 condition。

更新 Task 1 的 HTTP matrix：handler 创建前 monkeypatch `server.ChatRuntime` 为记录 typed 调用的 fake runtime；start/approval rows 分别断言 `start(message=..., session_id=...)` 与 `decide(job_id=..., approve=...)`。SSE row 断言第一次 `poll(job_id, after=0, timeout=0)` 发生在 `200` 响应头前，并复用首批 payload。

Task 2 的非法 session HTTP 用例不再 patch 已删除的 `server.make_llm`：handler 创建前把 `server.ChatRuntime` patch 为一个构造真实 `ChatRuntime`、但注入 fail-fast `llm_factory` 的 factory，继续证明 session 校验发生在 factory 调用前。

先运行：

```powershell
python -m pytest tests/test_web.py tests/test_ui.py -q
```

Expected：新 interface import/断言失败，现有 payload/static contract 通过。

**最小实现：**

1. 在 `chat_runtime.py` 移入常量、精简 `_ChatJob`、runtime-local registry、locks/conditions、event append、prune、worker、approval wait 与 stream batching。
2. `_ChatJob` 只保留 `job_id`、`started_at`、events、condition、done/completed_at 与 approval 状态；删除 workspace/session/message/result/error 死字段。
3. 所有时间读取使用 injected `clock`；三个 public 方法入口先 prune。无后台线程负责 prune，无 `close()`。
4. `start` 同步加载 secrets/config/state，注册 job、追加 `chat_started` 后才启动 daemon worker；worker 内调用 injected `llm_factory`、`ChatSession.run_turn` 与 `chats.build_chat_turn_response`。
5. `poll` 与 `decide` 只返回 dict copy/payload，不暴露 job。
6. `create_workbench_handler` closure 创建一个 runtime。HTTP adapter 校验 raw message/session/job_id/approve 后传 typed 参数；删除旧的 async payload builders。
7. `_send_sse` 先 nonblocking poll，成功后才发送 SSE header；写失败只结束该连接，不取消 worker。

**验证与提交：**

```powershell
python -m pytest tests/test_web.py tests/test_ui.py tests/test_chat.py tests/test_cli.py -q
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
python -m pytest tests/test_ui.py -q
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
python -m pytest tests/test_ui.py tests/test_web.py -q
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
python -m pytest tests/test_ui.py tests/test_web.py -q
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
python -m pytest tests/test_ui.py tests/test_web.py tests/test_cli.py -q
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
```

**自动门禁：**

```powershell
python -m pytest tests/test_web.py tests/test_ui.py tests/test_chat.py tests/test_cli.py tests/test_docs.py -q
python -m pytest -q
python -m agent.cli doctor
git diff --check
git diff --check <implementation-base>..HEAD
git diff --name-only <implementation-base>..HEAD
git status --short
```

**真实 Workbench：**

1. 页面加载 health/config/files/chats/runs；
2. 发起 streaming chat，确认 sequence、thinking/content/args batching 和 final 展示；
3. 发起需要审批的无害 `run_command`，审批卡保留 reason，批准后同一 turn 完成；
4. 检查对应 trace 保留 approval reason 与命令结果；
5. 主动断开一个 SSE client，确认 worker 不取消且 server 仍响应新的 health 请求；
6. 使用不存在的 job 请求 events，确认返回 JSON `400` 而非已发送的 SSE `200`；
7. 无可用 provider key 时明确记录环境阻塞，不把 fake/static 测试冒充真实 provider 验收。

真实 Workbench 验收完成后把 spec 状态改为“已实现”，plan 状态改为“已执行”，并记录实际验证结果。若缺少 provider key 等外部条件，只能记录“实现与自动门禁通过，真实验收阻塞”，不得标记全部完成。

**验证与提交：**

```powershell
git diff --check
git add -- src/agent/web/server.py docs/superpowers/specs/2026-07-13-workbench-backend-modularization-design.md docs/superpowers/plans/2026-07-13-workbench-backend-modularization.md
git diff --cached --check
git commit -m "chore: close Workbench backend modularization"
```

若 `server.py` 无额外 cleanup，Task 8 仍以 spec/plan 的实际验收记录形成非空收口提交，不回写或重排已经通过的 Task 7 commit。

## 独立 PR 发布门禁

实现与本地验收完成后先检查：

```powershell
gh pr view 7 --json state,isDraft,baseRefName,headRefName,mergeStateStatus,url
```

- PR #7 未合并：停止在本地已验证分支，不 push/open backend PR。
- PR #7 已合并：fetch 远端，确认其实际合并目标，保证 tracked worktree clean 后把本轮 commits rebase 到合并后基线；不得使用 `reset --hard`。
- rebase 后重新运行 Task 8 全部自动门禁与真实 Workbench 验收，并确认 PR diff 只含本轮 spec、plan、backend modules 与测试。
- 之后 push `codex/v3.1-workbench-backend` 并创建一个独立 PR；PR body 写明 scope、三项有意行为变化、测试证据、真实 Workbench 结果和并发 session lock 的明确延期。
- 若 PR #7 无法合并或 rebase 需要改变已批准设计，暂停发布并请用户重新决策，不静默改为 stacked PR。

## Plan 对抗审查记录

待逐项对抗审查后填写；审查通过前不得执行 Task 1。
