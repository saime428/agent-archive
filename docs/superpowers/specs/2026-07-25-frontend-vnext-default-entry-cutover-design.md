# 设计：Frontend vNext 默认入口切换

- 日期：2026-07-25
- 状态：已完成（Cutover、真实提交重建与 detached rollback 均通过）
- 上位方向：[Frontend vNext 总方向](../../frontend-vnext-direction.md)
- 前置设计：[默认入口切换就绪设计](2026-07-25-frontend-vnext-default-entry-cutover-readiness-design.md)
- 前置证据：[Readiness 验收记录](../../verification/frontend-vnext-default-entry-readiness.md)

## 授权与结论

用户已明确要求继续完成 Project vNext；当前完成定义以阶段 0–3 为核心，阶段 4–5 为
需求触发项。既有 Readiness 门禁已通过，因此本切片激活前置设计中的 Cutover 阶段：

1. 根 `/` 从旧 `index.html` 切换到已跟踪的 `preview/index.html`；
2. `/preview/` 继续返回同一 React 入口，`/legacy/` 继续返回旧 Workbench；
3. 不改 CLI、HTTP/SSE Interface、React 业务状态、Vite `base`、配置或安全语义；
4. 本切片完成后只允许声明“默认入口已切换”，不宣告旧壳退役或 Frontend vNext 完成；
5. 回滚只恢复根入口映射，不迁移或删除会话、run、snapshot、config、memory 或静态资产。

## 当前事实

- `agent start` 与 `agent ui` 最终都由 `serve_workbench` 提供根 URL；CLI 不选择前端。
- `src/agent/web/server.py::_STATIC_ENTRYPOINTS` 是唯一入口 seam；Readiness 已把根、preview、
  legacy 三个入口集中在这一份私有映射。
- `src/agent/web/static/preview/**` 已受版本控制并进入 wheel；Python 运行时不调用 Node。
- React HTML 的资源 URL 仍使用 `/preview/assets/**`，因此根 `/` 与 `/preview/` 可复用同一
  HTML 和同一 bundle。
- Readiness 已验证 HTML `no-store`、别名 308、资产闭包、wheel 内容、实服加载与回滚入口。

## 行为差异

| URL | Cutover 前 | Cutover 后 |
| --- | --- | --- |
| `/` | 旧 `index.html` | React `preview/index.html` |
| `/preview/` | React `preview/index.html` | 不变 |
| `/legacy/` | 旧 `index.html` | 不变 |
| `/preview` | 308 → `/preview/` | 不变 |
| `/legacy` | 308 → `/legacy/` | 不变 |
| HTTP JSON / SSE | 现有行为 | 不变 |

根 `/` 不重定向到 `/preview/`。浏览器地址保持产品根路径，React 继续使用 hash 路由，
静态资源继续从 `/preview/assets/**` 加载。`/preview/` 保留给既有书签和验收；
`/legacy/` 是稳定回滚入口。

## 实现 seam

运行时代码只改一行：

```python
_STATIC_ENTRYPOINTS = {
    "/": "preview/index.html",
    "/preview/": "preview/index.html",
    "/legacy/": "index.html",
}
```

不新增 resolver、feature flag、配置键、环境变量、cookie 或第二份 bundle。两个真实前端
Adapter 已由同一静态入口 Module 隔离；再增加公开 Interface 只会扩大回滚面。

## 测试设计

### Python HTTP 契约

`tests/test_web.py` 通过现有 HTTP seam 证明：

- `/` 与 `/preview/` 都返回 React 文档，`/legacy/` 返回旧文档；
- 未知目录仍为 404；三个 HTML 入口仍为 `Cache-Control: no-store`；
- `/preview`、`/legacy` 的 308 与查询字符串保持不变；
- 嵌套目录 index 测试不再把根旧文档当作默认入口；
- 实际 tracked preview 文件树仍逐文件通过 Python handler 原字节返回。

测试 helper 从 `_readiness_static_root` 重命名为 `_entrypoint_static_root`，避免把已完成的
阶段名称留在长期测试 Interface 中。

### Python 实服 Cutover smoke

扩展现有 `frontend/e2e-served/served-workbench.spec.ts`，仍由专用 wrapper 启动隔离的
真实 Python Workbench，禁止复用已有服务：

1. `/api/health` 为 200 且 `Server` 以 `AgentWorkbench/` 开头；
2. 从 health 读取 workspace，严格校验它位于当前 `tmpdir()` 且目录名以
   `agent-served-workspace-` 开头，再由测试 harness 写 seed 文件；后续 UI 保存为它创建
   snapshot。生产 `/api/file/save` 继续拒绝不存在的文件；
3. 从根 `/` 加载 React，完成一个 FakeLLM 普通 final；
4. 从根入口打开 System、Files、Runs，验证 seed 文件可读；
5. 经 UI 打开保存确认，经 run snapshot 打开 diff 与恢复确认；
6. `/preview/` 仍可加载 React，`/legacy/` 仍返回旧 Workbench；
7. 全程没有 request failure、loopback 4xx/5xx 或 console error。

seed 只写入 wrapper 创建并清理的临时 workspace；不得写当前仓库。该 smoke 只覆盖入口
切换影响面，不复制默认 Vite E2E 的全部布局、视觉和失败路径用例。

### 文档契约

`tests/test_docs.py` 同时保护两段历史：

- Readiness 文档继续证明“当时根 `/` 未切换”；
- 新 Cutover spec、README、CHANGELOG、roadmap 与新验收记录证明“当前默认入口已切换”；
- 所有当前文档继续禁止“旧壳已退役”和“Frontend vNext 长期路线完成”。

## 允许文件

- `src/agent/web/server.py`
- `tests/test_web.py`
- `frontend/e2e-served/served-workbench.spec.ts`
- `README.md`
- `CHANGELOG.md`
- `docs/project-vnext-direction.md`
- `docs/frontend-vnext-direction.md`
- `docs/roadmap-progress.md`
- `docs/verification/frontend-vnext-default-entry-cutover.md`
- `tests/test_docs.py`
- 本 spec 与对应 implementation plan

若实现需要修改上述范围外的生产代码，或改变 API/SSE、sandbox、approval、snapshot、
config、run store、静态资产内容或 Vite 配置，停止并另写 spec。

实服门禁发现的异步新会话首次详情 500 已按该停止条件拆到
[独立纠错 spec](2026-07-25-async-chat-session-visibility-design.md)；它不是 Cutover 入口实现，
必须独立审查和提交。

## 验收门

- spec 与 plan 分别通过正确性、可读性、架构、安全、性能五轴审查；
- 目标 Python HTTP 测试先因根仍为 legacy 失败，再以一行映射变化转绿；
- `node --test scripts/start-served-workbench.test.mjs` 通过；
- `npm run test:e2e:served` 从根路径通过；
- `npm run check`、全量 `pytest -q`、`agent release doctor`、`git diff --check` 通过；
- 在 D 盘临时目录重建 wheel，确认 wheel 中 `agent/web/server.py` 与源码逐字节相等，
  preview 资产路径集合与逐文件内容仍与源码完全相等；
- 可见浏览器确认 `/` 为 React、`/legacy/` 为旧 Workbench，控制台零 warning/error；
- 当前 Git index 不夹带两份未跟踪 handoff 文档或其他无关文件；
- 正式提交后从真实提交重建 preview bundle，路径与字节零漂移；
- 回滚演练证明只恢复根映射即可，不需要重建或迁移数据。

## 非目标

- 不删除或改写旧 Workbench 资产；不把 `/legacy/` 设为临时或自动过期。
- 不实现 Monaco、workspace 搜索、Git、Terminal、命令面板或 Phase 3 功能。
- 不新增依赖、状态库、router、service worker、CDN、desktop shell 或远程访问。
- 不改变 Provider、MCP、Skills、Memory、Automation 或 Gateway 生命周期。
- 不把本切片包装为灰度发布系统；本地回滚入口已足够。

## 完成声明

| 证据状态 | 允许声明 | 禁止声明 |
| --- | --- | --- |
| spec 已审核、plan 未审核 | Cutover 设计已通过 | Cutover 已批准实施、默认入口已切换 |
| spec 与 plan 已审查 | Cutover 已批准实施 | 默认入口已切换 |
| 全部门禁通过 | 默认入口已切换，`/legacy/` 可回滚 | 旧壳已退役、Frontend vNext 完成 |

## 设计审查记录

- 结论：通过；正确性、可读性、架构、安全、性能五轴无未解决 finding。
- 已修正：Readiness 验收记录保持历史只读，不列入 Cutover 修改范围。
- 已补强：wheel 门禁同时比较 `server.py` 与完整 preview 资产闭包。
- 已修正：实服 seed 由验证过的隔离 workspace 测试 harness 创建，不扩张 file/save Interface；
  入口兼容断言与主流程保持在同一测试 worker，失败时仍能可靠停止服务。
- 设计保持一行私有入口 seam，无新依赖、公开 Interface、运行时选择器或数据迁移。
