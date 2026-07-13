# 设计：Workbench 后端解体——以 ChatRuntime seam 拆分 `server.py`

日期：2026-07-13
状态：草案，待对抗审查
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
- 每个 `create_workbench_handler(workspace)` 创建一个 runtime；不同 Workbench 实例不共享 job registry。
- `llm_factory`、`clock`、`approval_timeout` 和 `job_ttl` 是真实的内部测试 seam：生产使用现有实现，测试传入 fake factory、可控时钟和短时限；它们不是新的用户配置。
- 不为 `threading.Thread`、`Condition` 或 registry 定义 Protocol/adapter；它们不需要替换，留在 implementation 内。

### Interface

```python
runtime.start(request)
runtime.poll(job_id, after=after, timeout=timeout)
runtime.decide(request)
```

返回值沿用当前 HTTP payload 形状，不新增仅供内部使用的 DTO：

- `start` 返回 `status`、`job_id`、`session_id`；
- `poll` 返回 `job_id`、`events`、`done`、`next`；
- `decide` 返回 `status`、`job_id`、`approved`。

`start` 在模块内部校验 `message`、可选 `session_id`，`decide` 校验 `job_id` 与 `approve`；无效输入继续抛出现有 `ValueError` 文案。这样 HTTP adapter 不需要一层只做转发的 chat payload builder，也不会形成 `chats.py` 与 `chat_runtime.py` 的循环依赖。同步兼容 `/api/chat/turn` 继续由 `chats.py` 直接运行，不伪装成异步 job。

### 状态所有权

以下状态只能存在于 `ChatRuntime` implementation：

- job registry 与 registry lock；
- `_ChatJob` 数据；
- 每个 job 的 condition、events、done/result/error；
- `approval_pending`、`approval_deadline`、`approval_decision`；
- TTL pruning 与 worker 完成时间。

`server.py`、`chats.py` 和测试不能获取 job 对象，也不能取得 condition 或 lock。SSE handler 只通过 `poll` 读取事件。

### 生命周期不变量

1. job 必须先注册并写入 `chat_started`，再启动 worker。
2. event `sequence` 从 1 开始并严格递增；`poll(after=n)` 只返回 `sequence > n` 的事件。
3. 只有已完成且超过 TTL 的 job 可被 prune；活跃或等待审批的 job 不得被 TTL 删除。
4. 一个 job 同时最多有一个 pending approval。
5. `decide` 只接受未完成、pending 且未过截止时间的 job。
6. 过期决定必须把状态归一为 `timed_out`、唤醒 worker，并返回现有错误文案；不能退化成普通拒绝。
7. worker 无论成功、provider 错误还是意外异常，都必须在 `finally` 清理审批状态、标记完成并通知 waiter。
8. SSE 断开只停止该 HTTP 写循环，不取消 worker；本轮不新增取消协议。
9. `STREAM_EVENT_BATCH_CHARS`、事件名、事件字段、approval reason 和 final/error 顺序保持不变。

## HTTP adapter

`create_workbench_handler` 在 closure 中持有 resolved workspace 和一个 `ChatRuntime`。路由继续使用当前直白的 `if path == ...` 分支；本轮不建立 route table、decorator 或 dispatcher class。

端点映射保持不变：

| 路径族 | 目标模块 |
| --- | --- |
| `/api/health`、`/api/config`、`/api/tools` | `settings.py` |
| `/api/files`、`/api/file`、`/api/file/save`、`/api/diff`、`/api/snapshot/restore` | `files.py` |
| `/api/chats`、`/api/chats/*`、`/api/chat/turn`、rename/delete | `chats.py` |
| `/api/chat/start`、`/api/chat/events`、`/api/chat/approval` | 直接调用 `ChatRuntime` |
| `/api/runs`、`/api/runs/*` | `runs.py` |
| 其他 GET | 现有 static fallback |

异常到 HTTP 状态码的映射继续集中在 handler；领域模块抛出现有 `ConfigError`、`RunStoreError`、`SandboxError`、`DeepSeekError`、`ValueError` 或 `OSError`，不新增 Web 专用异常层。

## 迁移顺序

### 1. 提取 `ChatRuntime`

- 先用现有行为测试锁定 start/poll/approve/timeout/finish；
- 把 `_ChatJob`、全局 registry 与异步 worker 移入 runtime；
- 把测试从私有状态操作改为通过 `start`、`poll`、`decide`；
- 确认每个 handler/runtime 的 registry 隔离。

这是本轮唯一包含结构性设计判断的步骤。

### 2. 按领域移动无状态逻辑

依次移动 `runs.py`、`files.py`、`settings.py`、`chats.py`。每次只做 import/path 调整，避免在移动 commit 中顺手改文案、payload 或算法。

不新增兼容 facade。仓库内测试直接改为从新模块导入；生产入口仍只从 `server.py` 导入 `serve_workbench`。

### 3. 收窄 `server.py`

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

## 测试策略

### 替换私有测试

`tests/test_web.py` 中直接创建 `_ChatJob`、修改 `_CHAT_JOBS` 或持有 `_CHAT_JOBS_LOCK` 的测试必须删除或改写。替代测试只使用 `ChatRuntime` interface，覆盖：

- 完成 job 超过 TTL 后在 `poll` 时被清理；
- 活跃 job 不被清理；
- tagged stream chunk 与 tiny-chunk batching；
- pending approval 的批准、拒绝、超时和 late decision；
- final/error 后 `done=True` 且 waiter 被唤醒；
- 两个 runtime 的 registry 互不相见。

旧测试与新 interface 测试重复时，删除旧测试，不叠加两套实现细节断言。

### 保留 payload 合约

`tests/test_ui.py` 继续覆盖 health/config/files/chats/runs payload 和静态前端 contract，只更新 import 来源。同步 `/api/chat/turn`、历史摘要中文映射、快照恢复、run review/replay 等既有断言不得因搬文件而弱化。

`tests/test_web.py` 增加一个小型 HTTP wiring smoke：使用临时 `ThreadingHTTPServer` 和随机端口，至少请求 health、files、chats、runs 各一个只读端点，证明 handler 在模块移动后仍正确路由。它不复制每个 payload 的领域测试。

不为本轮新建完整 `tests/web/` 目录或按模块机械拆测试文件；现有两个测试文件足以承载行为与 contract。

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
- 不改 `core/loop.py`、LLM provider、审批策略或 shell 策略。
- 不改静态前端模块、CSS、端点名称或 payload 设计。
- 不引入 Flask/FastAPI/aiohttp、asyncio、任务队列或数据库。
- 不新增通用 repository、controller、service、router、facade 或依赖注入框架。
- 不处理 Workbench 鉴权、`0.0.0.0` 暴露或 worker 取消协议。
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
- `tests/test_web.py`
- `tests/test_ui.py`
- 仅在真实 import/contract 受影响时修改 `tests/test_cli.py`

不预计修改前端、core、provider、policy、tools、config schema 或 README。

## 完成定义

1. `server.py` 不再定义 `_ChatJob`、job registry、chat worker 或领域 payload builders。
2. `ChatRuntime` 只有 `start`、`poll`、`decide` 三个运行期方法，且完全拥有 job 可变状态。
3. 测试不再访问 chat job 私有 class、registry、lock 或 condition。
4. 领域模块不导入 `server.py`，依赖方向与本文一致。
5. 现有 HTTP/JSON/SSE/审批/文件/run 合约保持，聚焦测试与全量测试通过。
6. 真实 Workbench streaming + approval 验收通过。

## PR 策略

该实现从 `679e2ff` 单独分支，不继续向 PR #7 追加大规模重构。若 PR #7 尚未合并，新 PR 以 `codex/v3.0-frontend-modules` 为 base，只展示本轮后端模块化 diff；PR #7 合并后再按实际目标分支更新 base。

spec、plan 和实现可以在同一新分支分批提交，但在本设计与后续 plan 通过对抗审查前不搬生产代码。
