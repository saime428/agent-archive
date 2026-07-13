# 设计：Workbench 后端解体——以 ChatRuntime seam 拆分 `server.py`

日期：2026-07-13
状态：已通过对抗审查，待实现计划
依据：`docs/code-review-2026-07-12.md` 3.1、5.4
实现基线：`679e2ff`
实现分支：`codex/v3.1-workbench-backend`
计划：待本设计通过对抗审查后编写

## 背景

`src/agent/web/server.py` 当前约 1798 行，同时承担：

- HTTP 路由、JSON 响应、SSE 和静态文件传输；
- Workbench 健康、设置和工具目录 payload；
- 文件读取、保存、diff、快照恢复和审计日志；
- 会话列表、同步兼容 turn、异步 chat job、审批和展示投影；
- run 列表、任务审查、失败恢复和 replay 投影。

生产代码只有 CLI 需要 `serve_workbench`，但测试从 `server.py` 导入大量 `build_*_payload` 函数，部分测试还直接修改 `_CHAT_JOBS`、`_CHAT_JOBS_LOCK` 和 `_ChatJob`。这说明 HTTP adapter、领域逻辑和并发生命周期没有形成清晰 seam。

本轮不是为了追求更少的单文件行数，也不是把 1798 行平均搬进若干文件。核心决策是把异步聊天任务做成一个深 `ChatRuntime` 模块：HTTP 和测试只学习很小的 interface，线程、锁、TTL、审批状态和事件序列留在其 implementation 内。其余无状态逻辑按既有领域搬移，减少 `server.py` 的修改冲突。

## 目标

1. `server.py` 只负责 HTTP/static/SSE 传输、显式路由和错误到状态码的映射。
2. 建立深 `ChatRuntime` 模块，集中拥有 chat job 的全部可变状态和并发规则。
3. 设置、文件、聊天投影和运行审查按领域落到独立模块，且不反向依赖 `server.py`。
4. 保持现有 URL、请求字段、JSON payload、SSE 事件和 Workbench 行为兼容。
5. 测试穿过新 interface，不再读取或修改 chat job 私有状态。
6. 不引入依赖、Web 框架、asyncio 迁移或通用路由抽象。

## 设计原则

### 先建立 seam，再移动代码

真正复杂且有状态的是 chat job 生命周期。`ChatRuntime` 的删除测试成立：若删除它，锁、条件变量、TTL、审批截止时间、事件序列和 worker 收尾会重新散回 HTTP handler 与测试，因此该模块有实际深度。

设置、文件和 run payload 主要是无状态或本地文件系统逻辑，不为它们新增 class、port 或 adapter。它们继续使用普通函数；拆分的收益来自 locality，而不是制造可替换性。

### 依赖方向单向

允许的主要依赖方向：

```text
server.py
  ├─> settings.py
  ├─> files.py
  ├─> chats.py
  ├─> chat_runtime.py ─> chats.py
  └─> runs.py

web domain modules ─> agent.core / agent.policy / agent.tools / agent.llm
```

禁止：

- 任何领域模块导入 `agent.web.server`；
- 为共享一两个私有函数新增 `web/utils.py`；
- `settings.py`、`files.py`、`runs.py` 互相调用；
- 通过 `server.py` re-export 搬走的 test-only 函数，保留旧的宽 interface。

若移动时出现循环依赖，优先把行为放回拥有该状态或 payload 的领域模块，而不是新增抽象层绕开循环。

## 模块划分

| 模块 | 保留或迁入的职责 | 对外 interface |
| --- | --- | --- |
| `web/server.py` | `serve_workbench`、handler、显式 GET/POST 路由、JSON/SSE/static 传输、query 读取、HTTP 错误映射 | `serve_workbench`、`create_workbench_handler`、`static_file_path` |
| `web/chat_runtime.py` | `_ChatJob`、registry、lock、condition、worker、事件追加/轮询、审批、TTL、stream batching | `ChatRuntime.start`、`poll`、`decide` |
| `web/chats.py` | 会话列表/详情、同步 `/api/chat/turn`、重命名/删除、turn payload、状态与展示投影 | 当前 chat payload builders 及供 runtime 使用的 turn/state helper |
| `web/settings.py` | health、provider readiness、workspace risk、memory review、config 读取/校验/写入、tool inventory | 对应 settings/health/tools payload builders |
| `web/files.py` | 文件列表/读取/保存、diff、snapshot restore、Workbench save trace、路径与 snapshot 私有 helper | 对应 file/diff/snapshot payload builders |
| `web/runs.py` | run 列表/详情、task review、workflow hints、failure、patch review、recovery、replay | `build_runs_payload`、`build_run_detail_payload` |

聊天会话的持久化路径、session id 校验与目录删除统一由 `ConversationState` 拥有。`chats.py` 的删除 payload builder 只做请求字段校验、调用 `ConversationState.delete(cwd, session_id)` 并投影响应；它不复制 session id 正则或自行删除目录。`ConversationState.delete` 先复用既有 `_session_path` 校验 id，再对 chats root 与 session directory 执行当前的 `resolve()` + normalized `commonpath` containment，不能假设合法 id 足以阻止预先存在的 symlink/junction 越界。通过检查后只删除目录而不读取 `session.json`，因此仍可删除内容损坏的会话，并保持现有非法路径与不存在会话错误文案。snapshot containment 与聊天存储不是同一领域，现有同类检查随 snapshot helper 迁入 `files.py`；两处各自保留安全边界，不为数行安全逻辑新增共享 `web/utils.py`。

不以各文件行数作为验收条件。允许某个领域模块仍然较长，只要 interface、状态所有权和依赖方向清楚；不为了“平均”继续拆出浅模块。

## `ChatRuntime` seam

### 构造

```python
runtime = ChatRuntime(
    workspace,
    llm_factory=make_llm,
    clock=time.monotonic,
    approval_timeout=APPROVAL_WAIT_TIMEOUT_SECONDS,
    job_ttl=CHAT_JOB_TTL_SECONDS,
)
```

- `workspace` 在构造时 resolve，并固定该 runtime 的数据根目录。
- 每个 `create_workbench_handler(workspace)` 创建一个 runtime；不同 Workbench 实例不共享 job registry。job id 只在签发它的 runtime 内有效，另一实例查询时按现有 unknown-job 错误处理。
- `llm_factory`、`clock`、`approval_timeout` 和 `job_ttl` 是真实的内部测试 seam：生产使用现有实现，测试传入 fake factory、可控时钟和短时限；它们不是新的用户配置。
- 不为 `threading.Thread`、`Condition` 或 registry 定义 Protocol/adapter；它们不需要替换，留在 implementation 内。
- runtime 不启动后台 reaper，也不新增 `close()`：`start`、`poll`、`decide` 在处理请求前各执行一次轻量 prune。完全空闲时，过期 job 可保留到下一次 runtime 操作或进程退出；只有需要对空闲期内存作硬上限保证时，才另行设计后台清理生命周期。

### Interface

```python
runtime.start(message=message, session_id=session_id)
runtime.poll(job_id, after=after, timeout=timeout)
runtime.decide(job_id=job_id, approve=approve)
```

返回值沿用当前 HTTP payload 形状，不新增仅供内部使用的 DTO：

- `start` 返回 `status`、`job_id`、`session_id`；
- `poll` 返回 `job_id`、`events`、`done`、`next`；
- `decide` 返回 `status`、`job_id`、`approved`。

HTTP adapter 在信任边界校验 `message`、可选 `session_id`、`job_id` 与 `approve`，保留现有 `ValueError` 文案，再把 typed 参数传入 runtime。`ChatRuntime` 不接收原始 HTTP `dict`，避免其 interface 泄漏传输 payload 形状。校验直接留在对应路由分支，不新增只做转发的 chat payload builder，也不会形成 `chats.py` 与 `chat_runtime.py` 的循环依赖。同步兼容 `/api/chat/turn` 继续由 `chats.py` 直接运行，不伪装成异步 job。

`start` 保持现有同步/异步失败边界：它先在请求线程加载 workspace secrets、config/diagnostics 与已有或新建的 `ConversationState`，这些步骤全部成功后才注册 job、追加 `chat_started` 并启动 worker。配置或 session 错误因此仍直接抛给 HTTP adapter，不能创建一个随后只发 `error` 的空壳 job。`make_llm`、`ChatSession.run_turn` 和响应投影留在 worker；provider 构造或执行期错误继续通过 SSE `error` 事件报告，并最终以 `done=True` 收口。

本轮保持现有同 session 并发语义：runtime 不新增 per-session lock，也不阻止两个 job 同时加载并写回同一 `ConversationState`；`ConversationState.delete` 也不查询 runtime 中是否有活跃 job。直接 API 调用因此仍可能出现后写覆盖先写，或运行中的 worker 在删除后重新保存会话。当前前端通过活跃 turn 期间禁用发送按钮降低概率，但这不是服务端一致性保证。若要修复，需单独设计 start/rename/delete 的串行化、冲突响应和锁回收，不夹带在模块搬移 PR 中。

### 状态所有权

以下状态只能存在于 `ChatRuntime` implementation：

- job registry 与 registry lock；
- `_ChatJob` 的 `job_id`、`started_at`、events、condition、`done` 与 `completed_at`；
- `approval_pending`、`approval_deadline`、`approval_decision`；
- TTL pruning 与 worker 完成时间。

现有 `_ChatJob.workspace`、`session_id`、`message`、`result`、`error` 没有读取者，提取时直接删除。workspace 固定在 runtime，session/message 作为 worker 参数传入，最终结果与错误继续只通过 final/error 事件表达；不为可能的未来调试保留死状态。

`server.py`、`chats.py` 和测试不能获取 job 对象，也不能取得 condition 或 lock。SSE handler 只通过 `poll` 读取事件。

SSE adapter 在发送 `200 text/event-stream` 响应头前先调用一次 `runtime.poll(job_id, after=0, timeout=0)`，并把返回 payload 作为首批结果复用。这样 unknown 或已过期 job 仍能由 handler 映射为现有 JSON `400`，不会在响应头已经发送后再尝试改写错误响应；不为预检额外暴露 `get_job()`、`exists()` 或 job 对象。

### 生命周期不变量

1. job 必须先注册并写入 `chat_started`，再启动 worker。
2. event `sequence` 是 append 前的零基索引，从 0 开始并严格递增。
3. `poll(after=n)` 把 `after` 解释为事件列表偏移量，返回 `events[n:]`，即 `sequence >= n`；`next = n + len(returned_events)`。
4. `start`、`poll`、`decide` 进入时都使用同一个 injected clock prune；只有已完成且超过 TTL 的 job 可删除，活跃或等待审批的 job 不得被 TTL 删除。
5. 一个 job 同时最多有一个 pending approval。
6. `decide` 只接受未完成、pending 且未过截止时间的 job。
7. 过期决定必须把状态归一为 `timed_out`、唤醒 worker，并返回现有错误文案；不能退化成普通拒绝。
8. worker 无论成功、provider 错误还是意外异常，都必须在 `finally` 清理审批状态、标记完成并通知 waiter。
9. `final` 或 `error` 事件可能先于 finally 中的 `done=True` 被观察到；只有 `poll(...)["done"] is True` 才是 worker 完成屏障。
10. SSE 断开只停止该 HTTP 写循环，不取消 worker；本轮不新增取消协议。
11. `STREAM_EVENT_BATCH_CHARS`、事件名、事件字段、approval reason 和 final/error 顺序保持不变。

## HTTP adapter

`create_workbench_handler` 在 closure 中持有 resolved workspace 和一个 `ChatRuntime`。路由继续使用当前直白的 `if path == ...` 分支；本轮不建立 route table、decorator 或 dispatcher class。

端点映射保持不变：

| 路径族 | 目标模块 |
| --- | --- |
| `/api/health`、`/api/config`、`/api/tools` | `settings.py` |
| `/api/files`、`/api/file`、`/api/file/save`、`/api/diff`、`/api/snapshot/restore` | `files.py` |
| `/api/chats`、`/api/chats/*`、`/api/chat/turn`、rename/delete | `chats.py` |
| `/api/chat/start`、`/api/chat/events`、`/api/chat/approval` | adapter 校验输入后调用 `ChatRuntime` |
| `/api/runs`、`/api/runs/*` | `runs.py` |
| 其他 GET | 现有 static fallback |

异常到 HTTP 状态码的映射继续集中在 handler；领域模块抛出现有 `ConfigError`、`RunStoreError`、`SandboxError`、`DeepSeekError`、`ValueError` 或 `OSError`，不新增 Web 专用异常层。

## 迁移顺序

### 1. 提取 `ChatRuntime`

- 先用现有行为测试锁定 start/poll/approve/timeout/finish；
- 把 `_ChatJob`、全局 registry 与异步 worker 移入 runtime；
- 删除 `_ChatJob` 中没有读取者的 workspace/session/message/result/error 字段；
- 把测试从私有状态操作改为通过 `start`、`poll`、`decide`；
- 确认每个 handler/runtime 的 registry 隔离。

这是本轮主要的结构性设计判断。

### 2. 收口聊天会话删除

- 在 `ConversationState` 增加 `delete(cwd, session_id)`；
- 复用既有 session id 校验与 `_session_path`，同时保留当前 resolved normalized-commonpath containment，拒绝合法名称的外部 symlink/junction；
- 只检查并删除会话目录，不加载或解析 `session.json`；
- 保持现有成功 payload、非法路径及会话不存在错误文案。

### 3. 按领域移动无状态逻辑

依次移动 `runs.py`、`files.py`、`settings.py`、`chats.py`。每次只做 import/path 调整，避免在移动 commit 中顺手改文案、payload 或算法。

不新增兼容 facade。仓库内测试直接改为从新模块导入；生产入口仍只从 `server.py` 导入 `serve_workbench`。

仓库扫描确认生产代码仅从 `agent.web.server` 导入 `serve_workbench`；`build_*_payload` 的旧路径只有仓库测试使用，README 与当前产品文档没有把它们声明为公共 API。因此 builder 搬迁后不从 `server.py` re-export：这是有意的内部 Python import 路径变更。`server.py` 的保留 interface 仅为 `serve_workbench`、`create_workbench_handler`、`static_file_path`。

### 4. 收窄 `server.py`

- 删除已经迁出的 imports、globals、payload builders 和私有 helper；
- handler 调用新模块或 runtime；
- 保留 JSON/SSE/static 传输与现有显式路由；
- 最后跑全量与真实 Workbench 验收。

## 兼容约束

本轮以下内容必须保持：

- 所有现有 URL 和 HTTP method；
- 请求字段校验、错误文案和 HTTP 状态码；
- JSON key、值类型及用户可见中文映射；
- SSE event 名、字段、sequence、批量规则和终止条件；
- `/api/chat/turn` 旧同步 fallback；
- `approval=never`、超时、批准/拒绝语义；
- 工作区、外部只读、snapshot 与 restore 的安全检查；
- run trace、summary、redaction 和 Workbench file-save 审计格式；
- CLI 的 `serve_workbench` 调用方式。

字典 key 的序列化顺序和 JSON 缩进不是稳定 interface；语义 payload 与浏览器消费行为才是兼容目标。

有意的运行期行为变化限于两项：registry 从进程全局改为 runtime-local，以及过期 job 从“仅在 poll 时清理”改为“任一 runtime 操作进入时清理”。同一 Workbench 的正常 HTTP 行为不变；不再支持另一 handler 凭 job id 读取前一实例任务，也不保证 job 超过 TTL 后仍可通过非 poll 操作取得。这些都不是已支持的产品路径，前者避免跨工作区串 job 与测试污染，后者以三个入口的一次 prune 代替额外后台线程。另有一项不影响运行期行为的内部 import 路径变更：builder 不再从 `agent.web.server` re-export。

## 测试策略

### 替换私有测试

`tests/test_web.py` 中直接创建 `_ChatJob`、修改 `_CHAT_JOBS` 或持有 `_CHAT_JOBS_LOCK` 的测试必须删除或改写。替代测试只使用 `ChatRuntime` interface，覆盖：

- 完成 job 超过 TTL 后在 `start`、`poll`、`decide` 任一入口都会被清理；
- 活跃 job 不被清理；
- tagged stream chunk 与 tiny-chunk batching；
- pending approval 的批准、拒绝、超时和 late decision；
- final/error 可先出现，但继续轮询后必须得到 `done=True` 且 waiter 已被唤醒；
- 两个 runtime 的 registry 互不相见；
- start 的 config/session 准备失败同步抛出且不调用 `llm_factory`，provider/turn 失败则产生 `error` 事件并最终完成。

旧测试与新 interface 测试重复时，删除旧测试，不叠加两套实现细节断言。

### 保留 payload 合约

`tests/test_ui.py` 继续覆盖 health/config/files/chats/runs payload 和静态前端 contract，只更新 import 来源。同步 `/api/chat/turn`、历史摘要中文映射、快照恢复、run review/replay 等既有断言不得因搬文件而弱化。

`tests/test_chat.py` 用聚焦测试锁定 `ConversationState.delete`：拒绝越界 session id、拒绝合法 session 名指向工作区外的 symlink/junction，同时无需解析 `session.json` 即可删除内容损坏的会话目录。`tests/test_ui.py` 保留现有删除 payload 成功断言，并覆盖原有非法路径与不存在会话文案。

`tests/test_web.py` 增加一个紧凑的 HTTP route-dispatch matrix：使用临时 `ThreadingHTTPServer`、随机端口、sentinel builders 和 fake runtime，覆盖 handler 中每个显式 GET/POST 分支，断言 method/path/query/body 被派发给正确目标；另以不存在的 job 请求 `/api/chat/events`，断言在 SSE 响应头发送前得到现有 JSON `400`。矩阵只验证 adapter wiring，不复制领域 payload 断言，也不为测试修改 `create_workbench_handler` 的生产 signature、引入 router 或依赖注入框架。

不为本轮新建完整 `tests/web/` 目录或按模块机械拆测试文件；现有 `tests/test_web.py`、`tests/test_ui.py`、`tests/test_chat.py` 足以承载行为与 contract。

### 验收命令

```powershell
python -m pytest tests/test_web.py tests/test_ui.py tests/test_cli.py -q
python -m pytest -q
python -m agent.cli doctor
git diff --check
```

真实 Workbench 验收至少覆盖：

1. 页面加载 health/config/files/chats/runs；
2. 发起一个 streaming chat，事件持续更新；
3. 发起一个需要审批的无害 `run_command`，审批卡出现、批准后同一 turn 完成；
4. trace 中保留 approval reason 与命令结果；
5. SSE 客户端断开后服务仍能响应新请求。

## 非目标

- 不新增或修改产品功能。
- 不实现并行 `tool_calls`、标准 `role=tool` 历史或 provider 能力探测。
- 除给 `ConversationState` 增加会话删除操作外，不改 `core/loop.py`、其他 core 行为、LLM provider、审批策略或 shell 策略。
- 不改静态前端模块、CSS、端点名称或 payload 设计。
- 不引入 Flask/FastAPI/aiohttp、asyncio、任务队列或数据库。
- 不新增通用 repository、controller、service、router、facade 或依赖注入框架。
- 不处理 Workbench 鉴权、`0.0.0.0` 暴露或 worker 取消协议。
- 不新增 per-session lock，不修复同一会话的并发 turn 覆盖或活跃 job 与 rename/delete 的竞态。
- 不以 `server.py` 降到某个任意行数作为完成标准。

## 预计实现文件

新增：

- `src/agent/web/chat_runtime.py`
- `src/agent/web/chats.py`
- `src/agent/web/settings.py`
- `src/agent/web/files.py`
- `src/agent/web/runs.py`

修改：

- `src/agent/web/server.py`
- `src/agent/core/chat.py`
- `tests/test_web.py`
- `tests/test_ui.py`
- `tests/test_chat.py`
- 仅在真实 import/contract 受影响时修改 `tests/test_cli.py`

不预计修改前端、其他 core 模块、provider、policy、tools、config schema 或 README。

## 完成定义

1. `server.py` 不再定义 `_ChatJob`、job registry、chat worker 或领域 payload builders。
2. `ChatRuntime` 只有 `start`、`poll`、`decide` 三个运行期方法，且完全拥有 job 可变状态。
3. 测试不再访问 chat job 私有 class、registry、lock 或 condition。
4. 领域模块不导入 `server.py`，依赖方向与本文一致。
5. 现有 HTTP/JSON/SSE/审批/文件/run 合约保持，聚焦测试与全量测试通过。
6. 真实 Workbench streaming + approval 验收通过。

## PR 策略

当前本地实现分支从 PR #7 head `679e2ff` 创建，但不继续向 PR #7 追加大规模重构，也不以 `codex/v3.0-frontend-modules` 为 base 创建 stacked PR。PR #7 未合并期间只完成本地 spec、plan、实现与验证；待 PR #7 合并后，先 fetch 合并后的实际目标分支，把本轮 commits rebase 到该基线，再重新运行验收并确认 PR diff 只包含本轮后端模块化改动，之后才 push/open 一个独立 PR。若 PR #7 无法合并，发布保持阻塞并重新决策，不静默降级为 stacked PR。

本轮保持一个独立 PR，不再拆成 stacked PR。为保持可审查性，提交按以下层次组织：

1. spec 与 plan；
2. HTTP route-dispatch characterization matrix；
3. `ChatRuntime` 提取、对应 server 接线及 interface 测试；
4. `ConversationState.delete` ownership 修正、调用方切换及聚焦测试；
5. `runs.py` 移动、server 接线与测试 import 更新；
6. `files.py` 移动、server 接线与测试 import 更新；
7. `settings.py` 移动、server 接线与测试 import 更新；
8. `chats.py` 移动、server 接线与测试 import 更新；
9. `server.py` 清理、全量测试与真实 Workbench 验收收口。

每个实现 commit 必须保持仓库可运行且不破坏全量测试；每步至少运行对应聚焦测试与 `git diff --check`，最终再运行全量验收。不得出现“先删除旧实现、后续 commit 才接线”的断点。模块移动、server 接线和该模块测试 import 更新视为同一原子提交。不得把状态性 runtime 重构和无状态函数搬移揉进同一实现提交。spec、plan 和实现可以在同一新分支分批提交，但在本设计与后续 plan 通过对抗审查前不搬生产代码。
