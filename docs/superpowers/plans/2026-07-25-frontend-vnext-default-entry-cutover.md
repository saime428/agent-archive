# Frontend vNext 默认入口切换实施计划

- 日期：2026-07-25
- 状态：已执行，待提交后重建
- 设计：[Frontend vNext 默认入口切换](../specs/2026-07-25-frontend-vnext-default-entry-cutover-design.md)
- 前置证据：[Readiness 验收记录](../../verification/frontend-vnext-default-entry-readiness.md)

## 目标

在不改变任何 HTTP/SSE、安全或数据语义的前提下，把 `agent start` 的根 `/` 从旧
Workbench 切到已跟踪的 React Workbench；本切片与稳定观察期保留 `/preview/` 与
`/legacy/`，并用
Python HTTP、真实 Python 实服、wheel、可见浏览器和提交后重建证明可用与可回滚。

## 固定边界

- 生产代码只允许改 `src/agent/web/server.py` 的根入口映射和相邻状态注释。
- 不改 React 业务源码、Vite 配置、CLI、HTTP/SSE payload、配置或安全链。
- 不删除旧静态资源，不新增依赖、feature flag、前端选择器或第二份 bundle。
- 两份未跟踪 handoff 文档与本切片无关，任何暂存命令都必须排除。
- 每个任务后立即执行正确性、可读性、架构、安全、性能五轴审查；发现问题先修复再继续。

## Task 1：锁定文档与完成声明契约

### 修改

在 `tests/test_docs.py` 新增独立 Cutover 文档测试：

- Readiness spec/verification 仍包含“根 `/` 未切换”和“需再次授权”的历史事实；
- 新 Cutover spec 与 implementation plan 存在，并分别锁定一行运行时 seam 与真实提交重建；
- 当前 README、CHANGELOG、roadmap、方向文档和新 Cutover 验收记录最终必须声明
  “默认入口已切换”；
- 当前文档不得声明“旧壳已退役”或“Frontend vNext 长期路线完成”。

同时收窄现有
`test_frontend_vnext_default_entry_cutover_readiness_spec_records_boundaries`：继续保护 tracked
runtime asset、Readiness spec/plan/verification 的历史完成边界，但不再要求当前
README、CHANGELOG 与 roadmap 永久停留在“尚未 Cutover”。两条测试分别拥有历史与当前
状态，不建立相互矛盾的断言。

### 红灯

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_docs.py::test_frontend_vnext_default_entry_cutover_docs_record_current_state -q
```

预期：因当前文档仍写 Cutover 未发生、新验收记录不存在而失败。

### 审查

- 断言同时保护历史与当前状态，不篡改 Readiness 记录来制造绿灯；
- 只断言产品事实和完成边界，不绑定 Markdown 行号或无关措辞。

## Task 2：先写根入口 HTTP 与实服契约

### Python HTTP

修改 `tests/test_web.py`：

- `_readiness_static_root` → `_entrypoint_static_root`；
- `test_workbench_serves_readiness_entrypoints` →
  `test_workbench_serves_cutover_entrypoints`；
- 根 `/` 期望从 `legacy` 改为 `preview`；
- 嵌套目录 index 测试的根期望同步改为 `preview`；
- `/legacy/`、308、no-store、未知目录和实际资产逐字节测试保持不变。

### 真实 Python 实服

扩展 `frontend/e2e-served/served-workbench.spec.ts`：

- 保留健康检查和统一浏览器错误收集；
- 从 `/api/health.workspace` 取得路径，校验其父目录等于当前 `tmpdir()` 且目录名以
  `agent-served-workspace-` 开头，再由测试 harness 写 `README.md`；生产
  `/api/file/save` 继续拒绝不存在文件；
- 从 `/` 完成 FakeLLM final，打开 System/Files/Runs；
- 经 UI 打开文件保存确认、diff 与 snapshot 恢复确认；
- 另验 `/preview/` 为 React、`/legacy/` 为旧 Workbench；
- 不复制默认 Vite E2E 的视觉、布局和负向测试。
- 根、preview、legacy 兼容断言与 UI 主流程放在同一测试 worker，避免预期红灯触发 worker
  重启后把 webServer teardown 误报为产品失败。

### 红灯

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_web.py::test_workbench_serves_nested_directory_index `
  tests/test_web.py::test_workbench_serves_cutover_entrypoints -q
```

预期：两条根入口断言均因仍返回 `legacy` 失败。

实服 E2E 使用唯一 D 盘临时目录，把 `TEMP`、`TMP`、`TMPDIR`、
`AGENT_SERVED_CONTROL_DIR` 指向其中，并显式设置：

```powershell
$env:AGENT_EXE = (Resolve-Path '..\.venv\Scripts\agent.exe').Path
npm run test:e2e:served
```

预期：根 `/` 仍是旧 Workbench，React 根入口断言失败；wrapper 必须完成子进程、端口与
临时 workspace 清理。

### 审查

- 测试只跨公开 HTTP/DOM seam，不读取私有映射；
- seed 只写隔离 workspace；所有请求失败、loopback 4xx/5xx、console error 均失败；
- 测试结束后 4174/4175 无 LISTENING，D 盘唯一临时目录已删除。

## Task 3：实施一行 Cutover

### 修改

在 `src/agent/web/server.py`：

```python
_STATIC_ENTRYPOINTS = {
    "/": "preview/index.html",
    "/preview/": "preview/index.html",
    "/legacy/": "index.html",
}
```

同步把相邻注释从 Readiness 状态改为 Cutover/rollback 事实。不动 `_send_static`、别名、
缓存、containment、MIME、gzip 或异常处理。

### 绿灯

重跑 Task 2 两条 Python 测试与 `npm run test:e2e:served`，必须全部通过。

### 审查

- `git diff -- src/agent/web/server.py` 的行为差异只有根映射一行；
- `/legacy/` 与 `/preview/` 映射未改变；
- 无公开 Interface、配置或数据迁移；回滚是同一行反向变化；
- 映射查找仍为 O(1)，无额外请求或 bundle。

## Task 4：同步当前文档并建立验收记录

### 修改

- `README.md`：URL matrix 改为根 React，保留 `/preview/` 与 `/legacy/`；删除
  “Cutover has not happened”，改为准确回滚说明；
- `CHANGELOG.md`：增加默认入口已切换，明确旧壳仍保留；
- `docs/roadmap-progress.md`：把 Cutover 记为完成，Project vNext core 仍为 In progress；
- `docs/project-vnext-direction.md`、`docs/frontend-vnext-direction.md`：当前状态改为根已切换，
  下一切片为稳定观察/旧壳退役判定后进入 Phase 3；
- 新增 `docs/verification/frontend-vnext-default-entry-cutover.md`，记录范围、入口矩阵、
  自动门禁、wheel、实服、浏览器、rollback 和限制；
- Cutover spec 状态改为“已实施，待全量验收”；plan 保持执行中。

Readiness spec 与 `docs/verification/frontend-vnext-default-entry-readiness.md` 不修改。

### 绿灯

重跑 Task 1 文档测试和 `tests/test_docs.py -q`。

### 审查

- 历史证据与当前事实分开；
- 当前文档只声明默认入口已切换；
- Phase 3 与旧壳退役继续明确为核心未完成项；Phase 4–5 明确为需求触发项。

## Task 5：聚焦回归与五轴代码审查

### 门禁

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_web.py tests/test_docs.py -q --basetemp <D盘唯一目录>\pytest
Set-Location frontend
# 先把 TEMP/TMP/TMPDIR 与 Playwright output/control 指到同一 D 盘唯一目录。
node --test scripts/start-served-workbench.test.mjs
npm run test:e2e:served
Set-Location ..
git diff --check
```

### 五轴审查

1. 正确性：入口矩阵、hash 深链、final、System/Files/Runs、保存/恢复确认、404/308/no-store。
2. 可读性：长期测试无 readiness 命名残留，文档无相互矛盾的当前状态。
3. 架构：唯一静态入口 Module，HTTP/SSE 与 React Adapter 不变，无新抽象。
4. 安全：CSP、Host/Origin、sandbox、snapshot、secrets、approval 与临时目录隔离不变。
5. 性能：无重定向、无第二 bundle、哈希资产缓存策略不变。

任何 Required/Critical finding 必须在 Task 6 前解决并重跑对应门禁。

### 实际 finding

实服 E2E 发现异步新 session ID 暴露后、`session.json` 首次保存前的详情读取窗口：同一
URL 先 500（`FileNotFoundError`），约 23ms 后 200。该问题不属于入口映射，已按
[独立 spec](../specs/2026-07-25-async-chat-session-visibility-design.md) 和
[独立计划](2026-07-25-async-chat-session-visibility.md) 在共享 lifecycle seam 修复并单独提交。
确定性回归、`tests/test_web.py` 95 项和 5 个全新实服 E2E 已通过。

## Task 6：全量、wheel、rollback 与可见浏览器验收

### 自动门禁

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp <D盘唯一目录>\pytest
Set-Location frontend
# 先把 TEMP/TMP/TMPDIR 与 Playwright output/control 指到 D 盘唯一目录。
npm run check
node --test scripts/start-served-workbench.test.mjs
npm run test:e2e:served
Set-Location ..
.\.venv\Scripts\agent.exe release doctor --cwd .
git diff --check
```

### wheel

在唯一 `D:\CodexScratch\agent-wheel-cutover-<timestamp>` 中执行隔离 `pip wheel . --no-deps`。
用 Python 标准库 `zipfile` 断言：

- wheel 中 `agent/web/server.py` 与源码逐字节相等；
- `agent/web/static/preview/**` 与源码路径集合相等；
- preview 同名文件逐字节相等。

无论成功失败都恢复 `TEMP/TMP/TMPDIR` 并删除精确临时目录。

### rollback 前置证据

当前工作树只验证 `/legacy/` 可直接加载旧文档，且 API/数据目录未迁移。真正的一行反向
变化在 Task 7 的 detached worktree 演练，避免测试读取或 monkeypatch 私有入口映射，
也不为 rollback 新增生产 Interface。

### 可见浏览器

启动真实 Python Workbench 到隔离 D 盘 workspace/home：

- `/` 显示 React Workbench；完成普通 final，打开 System/Files/Runs；
- `/preview/` 仍显示 React；`/legacy/` 显示旧 Workbench；
- `/legacy?manual=1` 保留 query 并 308 到 `/legacy/?manual=1`；
- warning/error 为 0；停止服务后端口和临时目录清理。

把当前证据写入 Cutover 验收记录，spec 改为“Cutover 门禁通过”，plan 改为“已执行，
待提交后重建”。

### 实际证据

- 全量 Python：**1043 passed**。
- 前端：typecheck、lint、UI policy、build、**17 tests**、**41 E2E passed**，
  **1 个 30 秒录制用例按设计 skipped**。
- `agent release doctor --cwd .`：exit 0，`release readiness: complete`。
- wheel：`agent-2.1.0-py3-none-any.whl`，477,231 bytes，SHA-256
  `58a933efe55722d3aa03cc94bc87d49bb5c71e846f6ea08fa6da69e324f15a63`；
  `server.py` 与源码逐字节一致，14 个 preview 文件路径集合和内容一致。
- 可见浏览器：根完成 FakeLLM final，并打开 System、Files、Runs；`/preview/` 为 React；
  `/legacy?manual=1` 以 308 保留 query 到 `/legacy/?manual=1` 并显示旧 Workbench；页面
  warning/error 为 0。服务、端口、浏览器标签和 D 盘临时目录均已清理。

## Task 7：精确提交与真实提交重建

### 暂存审计

逐个 `git add -- <approved-file>`；禁止 `git add -A`。执行：

```powershell
git diff --cached --name-status
git diff --cached --check
git status --short
```

确认两份 `docs/agent-handoff-*.md` 仍未跟踪且未暂存。提交：

```powershell
git commit -m "feat(web): switch frontend vNext to the default entry"
```

不 push、不把 Draft PR 转 Ready、不合并。

### 真实提交重建

从实际提交在 D 盘创建 detached worktree：

1. `npm ci`；
2. `npm run build:preview`；
3. `git status --porcelain=v1 --untracked-files=all -- src/agent/web/static/preview` 无输出；
4. 根 `/` 实服 E2E 与目标 Python 测试通过；
5. 在 detached worktree 只把根映射反向改回 `index.html`，启动真实服务并断言
   `/` = 旧、`/preview/` = React、`/legacy/` = 旧，API health 仍为 200；
6. 删除 detached worktree 与唯一临时目录。

把真实 commit、tree 与重建证据写回验收记录和 plan，另作只含文档状态的验证提交；再确认
最终 HEAD 相对实现提交只改文档，不影响 bundle 或运行时。最终执行五轴 diff 审查、
`git diff --check`、分支/PR 状态核对。

## 完成门

- spec、plan、实现和验证提交均有审查证据；
- 所有命名测试、全量门禁、wheel、实服、可见浏览器、rollback 与提交后重建均通过；
- 根 `/` 为 React，`/legacy/` 可用，旧资产未删除；
- 未暂存、提交或修改无关 handoff；
- 当前状态只声明 Default Entry Cutover 完成，Project vNext 核心继续进入 Phase 3。

## 计划审查记录

- 结论：通过；任务依赖、红绿门、审查门、提交与回滚顺序可执行。
- 已修正：`/legacy/` 仅承诺在本切片和稳定观察期保留，不预先否定未来旧壳退役。
- 已修正：文档契约只绑定最终事实，不绑定 spec 的中间状态。
- 已修正：rollback 改在提交后的 detached worktree 做真实反向变化，不测试私有映射。
- 已修正：Readiness 测试只保护历史证据，当前状态由独立 Cutover 测试拥有，避免互斥断言。
- 已修正：seed 由校验过的隔离 workspace 测试 harness 创建，不改变 file/save 的既有
  “只编辑已存在文件”Interface；实服断言合并到同一 worker，失败清理仍可靠。
- 已修正：文档自动测试不提前绑定最终门禁状态；spec/plan 只在对应证据完成后更新状态。
