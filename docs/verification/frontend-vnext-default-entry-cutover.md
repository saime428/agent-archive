# Frontend vNext 默认入口 Cutover 验收记录

- 日期：2026-07-25
- 状态：已完成（默认入口已切换，可一行回滚）
- 设计：[`2026-07-25-frontend-vnext-default-entry-cutover-design.md`](../superpowers/specs/2026-07-25-frontend-vnext-default-entry-cutover-design.md)
- 计划：[`2026-07-25-frontend-vnext-default-entry-cutover.md`](../superpowers/plans/2026-07-25-frontend-vnext-default-entry-cutover.md)
- 前置：[Readiness 验收记录](frontend-vnext-default-entry-readiness.md)

## 当前结论

Frontend vNext 默认入口已切换。当前工作树的根 `/` 返回 React Workbench，
`/preview/` 返回同一 React 文档，`/legacy/` 继续返回旧 Workbench。

Cutover 工作树门禁、wheel、可见浏览器、真实提交重建与 detached rollback 均已通过。
旧壳尚未退役，Frontend vNext Phase 3 与 Project vNext 核心仍未完成；Phase 4–5
是需求触发项，不属于当前完成门槛。

## 入口矩阵

| URL | 当前文档 | 状态 | 缓存 |
| --- | --- | --- | --- |
| `/` | React `preview/index.html` | 200 | `no-store` |
| `/preview/` | React `preview/index.html` | 200 | `no-store` |
| `/legacy/` | 旧 `index.html` | 200 | `no-store` |
| `/preview?manual=1` | `/preview/?manual=1` | 308 | - |
| `/legacy?manual=1` | `/legacy/?manual=1` | 308 | - |

根入口不重定向；React 静态资源仍从 `/preview/assets/**` 加载。HTTP JSON、SSE、CSP、
Host/Origin 校验、sandbox、approval、snapshot、config 与持久化格式均未改变。

## 实现与聚焦证据

- 生产行为只把 `src/agent/web/server.py::_STATIC_ENTRYPOINTS["/"]` 从
  `index.html` 改为 `preview/index.html`；`/preview/`、`/legacy/` 映射不变。
- Python 根入口红灯：2 条测试在实现前均收到 `legacy != preview`；实现后 **2 passed**。
- Python 实服红灯：实现前根 HTML 与 `/preview/` 字节不同；实现后实服 E2E **1 passed**。
- 实服从根完成 FakeLLM final，打开 System、Files、Runs，经 UI 打开保存、diff 与恢复确认；
  root/preview HTML 字节相等，legacy HTML 保留 `tokenicode-shell`。
- TypeScript typecheck：通过。
- D 盘实服临时目录与 4174/4175 监听：测试后无残留。
- 聚焦回归：`tests/test_web.py tests/test_docs.py` **138 passed**；启动包装器 **4 passed、
  1 skipped（POSIX-only）**；当前实服 E2E **1 passed**。

## 全量、wheel 与可见浏览器证据

- 全量 Python：**1043 passed in 104.57s**。
- 前端 `npm run check`：typecheck、lint、UI policy、生产 build 通过；Vitest
  **17 passed**；Playwright **41 passed、1 skipped**（30 秒录制用例按设计跳过）。
- `agent release doctor --cwd .`：exit 0，`release readiness: complete`。
- wheel：`agent-2.1.0-py3-none-any.whl`，477,231 bytes，SHA-256
  `58a933efe55722d3aa03cc94bc87d49bb5c71e846f6ea08fa6da69e324f15a63`。
  wheel 内 `agent/web/server.py` 与源码逐字节一致，14 个 preview 文件的路径集合和内容
  与 `src/agent/web/static/preview/**` 完全一致。
- 可见 in-app browser：根 `/` 完成 `visible cutover acceptance` FakeLLM final；System
  显示 fake/ready，Files 显示隔离 workspace 的 `README.md`，Runs 显示本次 durable run；
  `/preview/` 显示 React，`/legacy?manual=1` 308 到 `/legacy/?manual=1` 并显示旧 Workbench。
  页面 warning/error 日志为 0。
- 浏览器标签、真实服务、4174 监听和 `D:\CodexScratch\agent-cutover-visible.*` 均已清理。

## 真实提交重建与 Rollback 证据

- 异步 chat 生命周期纠错提交：`1c54690e`；Cutover 实现提交：
  `43069b9e4feb553ce85cad14f527e7072ba7b530`，tree：
  `fd267f3402d278e0b89ce1554f9d3801a968fd61`。
- 从 Cutover 提交在 `D:\CodexScratch` 创建 detached worktree；`npm ci` 与
  `npm run build:preview` 通过，tracked preview 产物相对提交零漂移。
- 提交树聚焦回归：`tests/test_web.py tests/test_docs.py` **138 passed**；真实 Python 实服
  E2E **1 passed**。
- detached worktree 只把 `_STATIC_ENTRYPOINTS["/"]` 反向改为 `index.html` 后，
  `/api/health` 为 200，`/` 与 `/legacy/` 字节一致并返回旧 Workbench，`/preview/`
  继续返回 React。
- rollback 服务、4174 监听、detached worktree 与唯一 D 盘临时目录均已清理；主工作区
  只保留两份原有未跟踪 handoff 文档。

## 审查记录

- 方向审查修正总方向文档的 Phase 0/1/2 状态漂移；随后按个人生产工具定位，
  将 Phase 3 锁定为核心目标，并把 Phase 4–5 收敛为需求触发项。
- spec 审查保持 Readiness 历史记录只读，并增加 wheel 中 `server.py` 与资产闭包校验。
- plan 审查修复 legacy 保留期限、历史/当前文档断言冲突和 detached rollback 位置。
- 测试审查发现 `/api/file/save` 只编辑已存在文件；seed 改由校验过的隔离 workspace
  test harness 创建，没有扩张生产 Interface。
- 实服门禁发现异步新 chat 的 ID 在 `session.json` 首次保存前暴露，详情请求会先 500、
  约 23ms 后才 200。该范围外缺陷已拆到
  [独立 spec](../superpowers/specs/2026-07-25-async-chat-session-visibility-design.md) 与
  [计划](../superpowers/plans/2026-07-25-async-chat-session-visibility.md)，在共享 lifecycle seam
  修复；确定性测试 **2 passed**、`tests/test_web.py` **96 passed**，5 个全新服务连续通过
  原始 E2E。该修复将与 Cutover 分开提交。
- 五轴最终结论：正确性、可读性、架构、安全、性能均无未解决 finding。

## 环境例外

首次运行两条 Python 红灯测试时遗漏 `--basetemp`，pytest 在
`C:\Users\admin\AppData\Local\Temp\pytest-of-admin\pytest-150` 留下约 9 KB 临时目录。
它不包含项目文件，后续测试全部改用 `D:\CodexScratch` 唯一目录。按照项目 C 盘规则，
该目录未被擅自删除，等待用户授权后再精确清理。

## 待完成门禁

- [x] `tests/test_web.py tests/test_docs.py`（138 passed）
- [x] `node --test scripts/start-served-workbench.test.mjs`（4 passed，1 POSIX-only skipped）
- [x] `npm run test:e2e:served`（当前实现 1 passed；竞态修复另有 5 次全新服务连续通过）
- [x] `npm run check`（17 unit；41 E2E passed，1 recording skipped）
- [x] 全量 `pytest -q`（1043 passed）
- [x] `agent release doctor`（exit 0）
- [x] wheel 中 `server.py` 与 preview 路径/字节闭包（14 files）
- [x] 可见浏览器根/preview/legacy 与控制台（0 warning/error）
- [x] 精确提交、真实提交重建、detached rollback 演练

## Rollback

恢复 `src/agent/web/server.py` 根映射为 `index.html` 并重启服务即可。旧 Workbench、
React bundle、`/preview/`、`/legacy/`、会话、run、snapshot、config 和 memory 都没有删除
或迁移。该一行反向变化已在真实 Cutover 提交的 detached worktree 演练通过。
