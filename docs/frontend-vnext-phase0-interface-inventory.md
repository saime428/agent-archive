# Frontend vNext 阶段 0：HTTP/SSE Interface 契约清单

- 日期：2026-07-23
- 状态：基线快照（对应后端 `d1ab2dc`）
- 用途：React 前端数据 Adapter 的唯一契约来源；旧静态前端与新前端是同一
  Interface 的两个 Adapter。Interface 变更需先写独立后端 spec。
- 事实来源：`src/agent/web/server.py`、`src/agent/web/chat_runtime.py`、
  `src/agent/web/static/assets/sse.js`（逐行核对，非转述）。

## 1. 传输与安全边界（所有端点共享）

| 约束 | 事实 |
| --- | --- |
| 绑定 | 仅 loopback；Host 头非 loopback → 403 `Workbench only accepts loopback requests.` |
| 写保护 | POST 校验 `Sec-Fetch-Site` 与 `Origin`；跨源写 → 403 `Cross-origin Workbench writes are not allowed.` |
| 请求体 | POST 仅接受 `Content-Type: application/json`、非空、≤ 64 000 字节、顶层必须是 JSON object；违规 → 400 |
| 响应头 | `Cache-Control: no-store`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`、CSP `default-src 'self'`（img 额外 `data:`，`frame-ancestors 'none'`，`base-uri 'none'`） |
| 错误格式 | 统一 `{"error": "<message>"}` |

CSP 含 `script-src 'self'`：React 构建产物必须由同一 Python 服务器提供，
不能依赖外部 CDN 或 dev server 直连（与方向文档"构建后静态资源由现有
Workbench 服务提供"一致）。

## 2. GET 端点

| 端点 | 参数 | 返回（顶层键） | 错误 |
| --- | --- | --- | --- |
| `/api/health` | — | workspace、provider/model/key 状态、`provider_notice`、`settings_readiness`、`workspace_risk`、`memory_review` | 通用 |
| `/api/config` | — | `workspace`、`config`（AgentConfig 全键）、`diagnostics`（config 路径、loaded_files、warnings） | 通用 |
| `/api/chats` | — | 会话摘要列表（`session_id`、title、`turn_count`、时间戳） | 通用 |
| `/api/chats/<id>` | path 段 | 单会话详情（turns、`approval_required`、`repair_count` 等） | 通用 |
| `/api/tools` | — | Tool catalog 只读清单 | 通用 |
| `/api/runs` | — | `workspace`、`runs[]`（含 `status`、`risk_level`） | 通用 |
| `/api/runs/<id>` | path 段 | `summary`、`tool_calls`、`snapshots`、`review`、`workflow`、`failure`、`patch_review`、`recovery`、`replay` | 未知 run → 404 |
| `/api/files` | `path`（可选） | 目录清单（workspace 路径策略内） | 越界 → 400 |
| `/api/file` | `path` | 单文件内容 | 越界/非法 → 400 |
| `/api/diff` | `path`、`snapshot` | 快照 diff | 400 |
| `/api/chat/events` | `job_id` | **SSE 流**（见 §4） | 缺 job_id → 400 JSON |
| 其余路径 | — | 静态资源（`index.html` 兜底 `/`） | 404 |

GET 错误映射：`ConfigError`→400、`RunStoreError`→404、
`ValueError`/`SandboxError`→400、`OSError`→500。

## 3. POST 端点

| 端点 | 请求体必填 | 返回 | 特有语义 |
| --- | --- | --- | --- |
| `/api/chat/start` | `message`（非空 str）；`session_id` 可选 | `{"status":"running","job_id","session_id"}` | 启动后台 turn；同 session 已有活跃 turn → 400 `already has an active turn` |
| `/api/chat/turn` | 同步版（旧路径） | 完整 turn payload | 与 start/events 并存；同 session 互斥同上 |
| `/api/chat/approval` | `job_id`（str）、`approve`（bool） | `{"status":"ok","job_id","approved"}` | 无待审批 → 400；已过期 → 400 `chat approval has expired.`（并把 job 标记 timed_out） |
| `/api/chat/rename` | `session_id`、新标题 | 会话摘要 | 同 session 互斥 |
| `/api/chat/delete` | `session_id` | 确认 payload | 同 session 互斥 |
| `/api/config` | 白名单键子集 | config payload + `"status":"ok"` | 键白名单见 `web/settings.py::_validated_config_updates`；`approval=never`、`sandbox=danger-full-access` 拒绝；写入走 `config_write` 原子发布 |
| `/api/snapshot/restore` | snapshot 标识 | 恢复结果 | 走既有 snapshot 安全路径 |
| `/api/file/save` | `path`、内容 | 保存结果 | 走审批 + snapshot 路径；发布失败 → 500 `Could not save project config`（config）/对应消息 |

POST 错误映射：JSON 解析失败→400、`ConfigError`/`ValueError`→400、
`DeepSeekError`→502、`McpRuntimeError`→（config 阶段 400，否则 502）、
`OSError`→500。

## 4. SSE 契约（`/api/chat/events?job_id=...`）

### 封包格式

```
id: <sequence>
event: <event 名>
data: <JSON，含 event/sequence/elapsed_ms 及事件负载>
```

- `sequence` 从 0 递增、无空洞；`elapsed_ms` 相对 job 启动。
- 服务端内部以 10s 间隔 long-poll job 事件缓冲；`done` 后连接关闭
  （`Connection: close`，一次 turn 一条连接）。

### 事件目录（`sse.js` 为旧前端消费面，后端可超集）

| 事件 | 负载要点 | 阶段 |
| --- | --- | --- |
| `chat_started` | `session_id` | 开始 |
| `model_call_start` | 模型调用开始 | 每次调用 |
| `model_stream_start` | 流式开始 | 流式路径 |
| `model_stream_chunk` | `kind`（thinking/content/args）、`text`、`chunk_chars`；**按 64 字符批量合并**（`STREAM_EVENT_BATCH_CHARS`），kind 切换强制 flush | 流式路径 |
| `action_parsed` | 解析出的 action | 每 action |
| `tool_start` | 工具执行开始 | 工具路径 |
| `observation` | 工具结果的 `status`、`summary` 与 action 摘要 | 工具路径 |
| `approval_required` | 待审批 action 详情；**触发服务端 300s 审批倒计时** | 风险动作 |
| `approval_granted` / `approval_denied` / `approval_timed_out` | 审批结局 | 风险动作 |
| `capability_warning` | `requested`、`fallback`（native_tools 降级）；**不在旧前端 sse.js 目录内**——未知事件必须被忽略而非报错，新 Adapter 保持此宽容 | 能力不匹配 |
| `final` | turn 结果 payload | 终态 |
| `error` | `error` 字符串 | 终态 |

旧前端显式注册 13 个消费者事件；后端另发 `capability_warning`，所以当前已知
后端事件总数为 14。真正未知的事件仍必须被宽容忽略。

### 生命周期与恢复语义（新 Adapter 必须遵守）

1. **终态**：`final` 或 `error` 恰好一个；之后 `done=true`，连接关闭。
2. **重连 = 全量重放**：job 事件全程缓存在内存；重新 GET 同一 `job_id`
   会从 sequence 0 重放全部事件。前端用 `sequence` 去重，不假设服务端
   支持 `Last-Event-ID` 续传（当前实现不读取该头）。
3. **unknown job**：job 完成后保留 **300s**（`CHAT_JOB_TTL_SECONDS`），
   之后被 prune；对已失效 job_id 的 SSE 请求，连接建立前抛错 →
   `{"error": "Unknown chat job: ..."}`；连接建立后失效则静默关闭流。
   刷新页面超过 TTL 的 job 无法恢复——前端必须能从 `/api/chats/<id>`
   的持久化 turn 重建 UI。
4. **审批**：`approval_required` 后服务端阻塞等待 `/api/chat/approval`，
   超时 300s 记 `timed_out` 并继续（等价拒绝语义，turn 以
   APPROVAL_DENIED 类终态收尾）；同一 turn 内批准后继续产生后续事件。
5. **同 session 互斥**：一个 session 同时只允许一个活跃 turn/rename/
   delete；违反 → 400。前端应在 UI 层禁用并发发送，但不得依赖 UI 禁用
   作为唯一防线（后端已强制）。

## 5. 新 Adapter 的已知注意点

- `model_stream_chunk` 的 64 字符批量意味着打字机效果的粒度下限；如需更
  细粒度，属后端 Interface 变更，须另写 spec。
- `/api/chat/turn`（同步）与 `start`+`events`（异步）并存；新前端只用异
  步路径，同步路径在旧前端退役前保持不动。
- 静态资源与 API 同源同服务；React 构建产物放入现有静态目录即满足 CSP。
- 所有列表端点无分页；当前数据量下可接受，分页需求属后端 spec。
- 事件负载中的具体字段名以 `agent/core/loop.py` 的 `_emit_event` 调用为
  准；本清单锁定事件名与顺序语义，字段级 schema 在阶段 1 spec 的契约测
  试中逐事件固化。
