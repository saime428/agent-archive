# 设计：Phase 3I Legacy retirement

- 日期：2026-07-25
- 状态：已审查，待实施
- 上位方向：[Phase 3 方向分析与审查](../../project-vnext-phase3-direction-review.md)

## 目标

删除已经由 React Workbench 完整替代的旧静态壳、`/legacy/` 回滚入口和只供旧壳使用的同步
`POST /api/chat/turn` 兼容路径。根 `/` 与 `/preview/` 继续使用同一份已跟踪 React 产物；现行
`POST /api/chat/start`、SSE、审批、恢复、会话、运行记录、配置和数据格式不变。

本切片只完成 3I。Phase 3 与 Project vNext 核心仍需随后执行最终对话、生成、前端、后端、CLI、
package、真实浏览器与缺陷清零矩阵，不能因删除旧代码提前宣告完成。

## 已验证本地事实

- 根 `/` 已在 Cutover 后指向 `preview/index.html`，3A–3H 的源码、wheel、detached 和真实浏览器验收均
  通过；旧壳不再是默认入口。
- 旧壳恰好由 `static/index.html` 与 `static/assets/` 下 13 个文件组成，共 14 个文件；React 产物全部在
  `static/preview/`，两者路径不重叠。
- 旧 `assets/state.js` 是产品代码中 `/api/chat/turn` 的唯一调用者；React 使用
  `/api/chat/start`、`/api/chat/events`、`/api/chat/approval`、cancel 与 resume。
- `build_chat_turn_payload` 和 `ChatRuntime._reserve_turn` 只服务同步兼容路由；
  `load_or_create_chat_state`、`build_chat_turn_response` 与 `_reserve_session` 仍由异步运行时或
  rename/delete 使用，必须保留。

## 最终 Interface 矩阵

| Interface | 3I 后行为 |
| --- | --- |
| `GET /` | 200，React `preview/index.html`，HTML `no-store` |
| `GET /preview/` | 200，同一 React 文档，HTML `no-store` |
| `GET /preview` | 308 到 `/preview/`，保留 query |
| `GET /preview/assets/**` | 继续逐字节提供已跟踪 React 资产 |
| `GET /legacy`、`GET /legacy/` | 404，不重定向、不提供 tombstone 页面 |
| `GET /assets/**` | 旧资产删除后 404 |
| `POST /api/chat/turn` | 404，使用既有 unknown-endpoint JSON；请求体仍按现有上限安全丢弃 |
| async chat、其他 JSON/SSE API | 不变 |

`/legacy/` 和 `/api/chat/turn` 是明确退休的兼容 Interface，不增加 deprecated shim、feature flag、环境变量或
运行时双入口。需要回滚时恢复 Git 提交并重启服务；会话、run、snapshot、config、memory 和 job 数据没有
迁移或删除。

## 删除范围

- 删除 `src/agent/web/static/index.html` 与 `src/agent/web/static/assets/` 全部 13 个旧壳文件。
- `server.py` 删除 `/legacy/` 映射、`/legacy` alias、同步 turn import 与 route。
- `chats.py` 删除无调用者的 `build_chat_turn_payload`、`_approve_once_handler` 和随之失效的 LLM factory import。
- `chat_runtime.py` 删除只为同步兼容路径提供的 `_reserve_turn`。
- 删除旧壳 DOM/JS 字符串测试和同步 turn 专用测试；把仍有产品价值的 final payload、会话投影与审批行为
  保留在 async runtime、core chat 或 React E2E 覆盖中。
- 更新 README、CHANGELOG、当前方向/roadmap 与 served-wheel E2E；历史 Cutover spec 和 verification 作为
  当时事实保留，不回写历史。

## 验收

- 红灯先证明 `/legacy`、`/legacy/`、旧 `/assets/**` 与 `/api/chat/turn` 不符合最终 404 契约；实现后转绿。
- 搜索生产源码不得再出现旧静态文件、`/legacy/`、`build_chat_turn_payload` 或 `/api/chat/turn`；历史文档除外。
- 根与 `/preview/`、query redirect、cache、安全 header、gzip、preview 逐字节闭包和未知路径行为不回归。
- React 全量、Python 全量、CLI/release doctor、detached checkout、wheel 两次确定性构建、wheel-site 实服、
  served Playwright 和可见浏览器全部通过；console/request failure 为零。
- wheel 与源码都只含 React runtime 静态树；删除文件不在 wheel、sdist 或 Git tracked inventory 中。
- 检查 Git index、worktree、端口、进程和临时目录；不纳入两份无关 handoff。

## 非目标

- 不改 React `base=/preview/`，不复制 bundle 到根，不增加 SPA fallback 或通用目录重定向。
- 不删除 `/preview/` 兼容入口，不改现行异步 chat、SSE schema、数据格式、审批、安全或配置语义。
- 不增加 deprecation 页面、telemetry、迁移器、运行时开关、新依赖或新的 rollback UI。
- 不进入阶段 4–5 的生态 UI、分发、远程、账号、社区或商业化能力。
