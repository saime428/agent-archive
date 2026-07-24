# Frontend vNext 阶段 2 核心功能等价实施计划

> 本计划同时承担阶段 2 的设计锁定与执行编排。执行时严格按任务顺序推进；发现后端 Interface 缺口时先停止并补独立后端 spec，不在前端猜字段或制造假能力。

**Goal:** 在保留旧 Workbench 根入口作为回退的前提下，把当前只完成聊天纵切的 /preview/ 扩展为覆盖文件、编辑、diff、snapshot、runs/review、health、settings、tools 与资源详情的真实工作台，完成阶段 0 清单中的 Phase 2 功能等价。

**Architecture:** Python Workbench 继续是业务与安全事实来源；frontend/src/api/ 保持唯一 HTTP Adapter。当前 App Shell 与聊天状态机不重写，右侧不可交互的 PHASE 02 / WORKSPACE 提示升级为真实空间工作台。WorkspacePanel 作为一个有深度的产品 Module，内部按 Files、Runs、System 三个业务概念拆分实现；页面不直接 fetch，不增加第二套状态库或路由库。

**Design Read:** 延续阶段 1 的先锋空间语言、实验性排版与状态驱动动效，但核心数据使用可选择、可复制、可键盘操作的 DOM。视觉目标以 Awwwards、FWA、CSS Design Awards 日站级别作为内部设计代理，不宣称获得外部奖项或认证。

**Tech Stack:** 沿用已锁定的 React、TypeScript、Vite、Tailwind CSS、Radix Dialog/Tooltip、Motion、Lucide React、Canvas 2D、Vitest、Playwright 与现有 Python pytest；不增加依赖。

**Inputs:**

- docs/frontend-vnext-direction.md
- docs/frontend-vnext-phase0-interface-inventory.md
- docs/frontend-vnext-phase0-parity-checklist.md
- docs/verification/frontend-vnext-phase1.md
- 当前后端实现 src/agent/web/files.py、runs.py、settings.py、server.py
- 当前旧前端 src/agent/web/static/assets/render/

**状态：** 待执行，已完成代码与接口审查

## 0. 已核实事实与审查结论

1. 阶段 1 已完成 C1-C9、H1 精简版、H2、S1、S2、S5；/preview/ 目前不是完整前端，只是可运行的 App Shell 与 Chat 纵切。
2. 当前 frontend/src/App.tsx 第 917 行的 workspace-reveal 只是 aria-hidden 的视觉提示，不是按钮或页面入口。这是用户看到“只有一个页面”的直接原因，不是最终信息架构。
3. Phase 2 唯一范围是 F1-F5、R1-R8、H3-H7、S3-S4；这些能力目前仍由旧根入口承载。
4. 所需 HTTP 端点已经存在：/api/files、/api/file、/api/file/save、/api/diff、/api/snapshot/restore、/api/runs、/api/runs/<id>、/api/health、/api/config、/api/tools。当前没有证据要求修改后端生产代码。
5. 文件保存的真实语义是：旧前端先显示浏览器确认面板，确认后调用 /api/file/save；后端执行 workspace 写路径限制、创建 snapshot、写文件并记录 run。它不进入 chat approval 队列。实现必须保留显式确认，但不得把它描述成后端审批。
6. /api/file 可能返回 truncated=true。截断内容绝对不能进入可保存编辑态，否则会用不完整内容覆盖原文件；Phase 2 对截断文件只提供预览。
7. /api/diff 的查询参数是 path 与 snapshot；/api/snapshot/restore 的请求体是 path 与 snapshot_path。恢复结果可能是 restored，也可能删除由原 run 新建的文件。
8. Run replay、workflow、patch review 与 recovery 全部是只读解释数据；浏览器没有重放执行或执行验证命令的后端能力。
9. 浏览器设置写入只允许 provider、model、mode、sandbox、approval、dry_run、web_search_enabled、computer_read_enabled、native_tools、default_skills。后端拒绝 approval=never 与 danger-full-access，不接收密钥，也不允许修改 allowed_commands。
10. 旧根入口与 /preview/ 已经是同一 HTTP Interface 的两个真实 Adapter；因此继续扩展现有 frontend/src/api/ 是真实 seam，不创建按页面分散的请求层。
11. staged preview 与 frontend/dist/ 都被 Git 忽略；实现提交源码、测试、视觉基线和验证摘要，不提交生成物。
12. 当前已有 Lucide-only 与零产品 emoji 静态门禁。新增 workspace 源码自动落入同一扫描范围，不需要再造图标检查脚本。

## 1. 范围锁定

| 清单 | Phase 2 交付 | 产品位置 |
| --- | --- | --- |
| F1-F2 | 目录浏览、路径回退、文本文件预览、截断与二进制错误态 | Files |
| F3 | 文本编辑、dirty 状态、保存确认、snapshot-backed 保存结果 | Files |
| F4-F5 | unified diff、截断提示、恢复确认、恢复后资源刷新 | Runs 中的 Snapshots 与 Files 上下文 |
| R1 | Run 列表、状态和风险本地过滤、更新时间 | Runs |
| R2-R7 | Review、Workflow、Failure、Patch Review、Replay、Recovery | Run detail |
| R8 | trace/replay 文本过滤与终态过滤 | Run detail |
| H3-H5 | Settings Readiness、Workspace Risk、Memory Review 只读视图 | System |
| H6 | 设置读取与白名单字段受控写入 | System / Settings |
| H7 | Tool catalog 只读目录 | System / Tools |
| S3 | 10 秒安全自动刷新与手动刷新 | WorkspacePanel 顶栏 |
| S4 | summary、chats、runs、memory、snapshots 的资源详情 | System / Overview |

阶段 2 完成的含义是“新前端覆盖当前旧 Workbench 核心能力”，不是 Frontend vNext 长期路线全部完成。Monaco、真实 terminal、Git 工作区和生态中心仍属于后续阶段。

## 2. 交互与视觉锁定

### 2.1 空间工作台

- 把当前右侧 workspace-reveal 替换为真实 button，使用 Lucide PanelRightOpen 图标和明确的“打开工作台”名称。
- 桌面端从右侧展开一张 56-68vw 的工作平面；聊天舞台保留上下文并做受控位移/降噪，不卸载当前会话，不把产品退化为传统固定三栏。
- 工作平面顶部只保留 Files、Runs、System 三个稳定入口，以及 Refresh、Close。二级内容在平面内部切换，不制造十几个一级导航按钮。
- 移动端使用 Radix Dialog 的全高 sheet；关闭后焦点回到打开按钮，Escape 可退出，背景不可误操作。
- 首次打开默认进入 System Overview，展示真实 health、run、chat、snapshot 与 memory 摘要；不使用演示数字或假入口。
- 面板切换使用 transform 与 opacity 的短 spring；prefers-reduced-motion 下立即切换。Canvas 不承载文字、表单、diff 或任何关键状态。

### 2.2 信息表达

- Files 使用大路径标题、窄目录轨道与主编辑平面，避免把每个文件做成通用卡片。
- Runs 使用按时间排列的索引与可展开诊断轨迹；风险、失败、恢复和 snapshot 操作优先于装饰。
- System 使用一张连续状态版面组织 readiness、risk、memory、settings 和 tools，不复制传统“卡片墙”。
- 文件内容、diff、summary、tool trace 均使用 data-payload 标记并保真展示；产品 chrome 继续禁止 emoji。
- 所有图标只从 lucide-react 具名静态导入。无手写 SVG、Unicode 图形替代图标、第二图标库或自定义鼠标圈。
- 状态不只靠颜色；必须同时有文字标签。危险操作的确认文案必须写出 path 和 snapshot。

## 3. Module 与依赖方向

### 3.1 唯一外部 seam

frontend/src/api/types.ts 定义 transport payload；frontend/src/api/client.ts 负责 URL 编码、JSON、错误转换与 GET/POST。App、WorkspacePanel 和三个业务视图只消费 ApiClient，不允许直接 fetch。

计划扩展的方法：

- listFiles(path?)
- getFile(path)
- saveFile(path, content)
- getDiff(path, snapshot)
- restoreSnapshot(path, snapshotPath)
- listRuns()
- getRun(runId)
- getConfig()
- saveConfig(updates)
- listTools()

不引入通用 repository、service factory、query cache 或 runtime schema 库。现有可注入 fetcher 已经是生产 HTTP 与测试 fake 的两个 Adapter。

### 3.2 前端 Module

| Module | 责任 | 不负责 |
| --- | --- | --- |
| App | Chat 生命周期、Shell、打开或关闭 WorkspacePanel、把全局刷新结果回写 command spine | 文件、run、settings 业务细节 |
| WorkspacePanel | 三个视图的导航、10 秒刷新时钟、分资源错误、dirty 刷新保护、资源摘要 | 解析具体诊断字段或编辑文件 |
| FilesView | 目录、预览、编辑 buffer、dirty、保存确认 | run review、snapshot 恢复 |
| RunsView | runs 过滤、详情、trace/replay、diff、restore | 执行 replay 或验证命令 |
| SettingsView | readiness、risk、memory、config allowlist、tools、资源详情 | 密钥、任意配置键、生态生命周期 |
| api | HTTP Interface 与错误映射 | UI 状态和产品文案 |

文件布局：

- Modify frontend/src/App.tsx
- Modify frontend/src/styles.css
- Modify frontend/src/api/types.ts
- Modify frontend/src/api/client.ts
- Modify frontend/src/api/client.test.ts
- Create frontend/src/workspace/WorkspacePanel.tsx
- Create frontend/src/workspace/FilesView.tsx
- Create frontend/src/workspace/RunsView.tsx
- Create frontend/src/workspace/SettingsView.tsx

不要为了测试建立一层空 hook 或 store。可观察交互通过 Playwright 测 WorkspacePanel 接口；纯 HTTP 行为通过 client.test.ts 测 ApiClient 接口。

### 3.3 刷新规则

WorkspacePanel 打开且 document.visibilityState 为 visible 时，每 10 秒刷新 health、config、tools、runs 与 chats 摘要。使用原生 Promise.allSettled，单个资源失败保留上一次成功数据并显示局部错误，不清空其他面板。

安全保护固定如下：

- 文件编辑 dirty 时，不重新请求或覆盖当前文件 content；允许刷新目录、runs、health 与其他资源。
- 设置表单 dirty 时，不用 GET /api/config 覆盖表单；仍可刷新 health、tools、runs 与摘要。
- 打开的确认 Dialog、chat approval 与进行中的 SSE 不被定时刷新关闭或重置。
- 手动 Refresh 遵守同一 dirty 规则，并明确显示“编辑内容未覆盖”或“设置草稿未覆盖”。
- 页面隐藏时不累积定时请求；重新可见后立即执行一次安全刷新。
- 每次 mutation 成功只刷新相关资源，再触发一次全局 health/runs 摘要刷新，不重新挂载整个 App。

## 4. 执行任务

### Task 1：固化 Phase 2 HTTP 契约

**Files**

- Modify frontend/src/api/types.ts
- Modify frontend/src/api/client.ts
- Modify frontend/src/api/client.test.ts
- Create frontend/src/test/workbench-payloads.json
- Modify tests/test_frontend_contract.py

**步骤**

1. 先在 workbench-payloads.json 固化 files、file、save、diff、restore、runs、run detail、health、config、tools 的最小真实样本和必需键。
2. 扩展 HealthPayload，准确表达 settings_readiness、workspace_risk、memory_review；新增 Files、Runs、Config、Tools payload 类型。复杂诊断对象只定义实际消费字段，不建立万能 Record UI。
3. 在 createApiClient 内加入上述九个方法，查询字符串统一用 URLSearchParams，路径段继续 encodeURIComponent。
4. client.test.ts 先写失败用例：空格和 Unicode 路径编码、snapshot 参数名、restore 的 snapshot_path、config allowlist payload、统一 ApiError。
5. tests/test_frontend_contract.py 调用现有 Python payload builder，对共享 JSON fixture 的关键字段与只读 mode 进行契约检查；不启动第二个服务器。
6. 不为响应增加新的 runtime validator 依赖；类型检查、fixture 与 Python builder 测试共同守护当前 seam。

**局部门禁**

    cd frontend && npm run test:run -- src/api/client.test.ts
    .venv/Scripts/python.exe -m pytest tests/test_frontend_contract.py tests/test_ui.py -q
    cd frontend && npm run typecheck

**提交**

    git commit -m "test: lock frontend phase 2 contracts"

### Task 2：把右侧提示升级为真实 WorkspacePanel

**Files**

- Modify frontend/src/App.tsx
- Modify frontend/src/styles.css
- Create frontend/src/workspace/WorkspacePanel.tsx
- Modify frontend/e2e/workbench.spec.ts

**步骤**

1. 先写 E2E 失败断言：workspace reveal 可聚焦并打开、三个真实入口存在、关闭后焦点返回、移动端为 modal sheet。
2. 在 App 中只增加 workspace open/close 状态与刷新回调；当前 sessionId、chat、activeJob 与 SSE subscription 保持挂载。
3. WorkspacePanel 首次加载真实 health/config/tools/runs/chats 数据；默认显示 System Overview，不渲染未实现的按钮。
4. 实现 10 秒安全刷新控制器与手动 Refresh，并对每个资源保留 last-success、loading、error。
5. 桌面 workplane、移动 sheet、键盘 focus trap 与 reduced-motion 使用现有 Radix/Motion，不加入路由库或状态库。
6. 删除 aria-hidden 的 PHASE 02 占位文案；它不能与真实入口并存。

**局部门禁**

    cd frontend && npm run typecheck
    cd frontend && npm run lint
    cd frontend && npm run test:e2e -- --grep "workspace shell"

**提交**

    git commit -m "feat: open frontend workspace plane"

### Task 3：完成 Files 浏览、预览与安全编辑

**Files**

- Create frontend/src/workspace/FilesView.tsx
- Modify frontend/src/workspace/WorkspacePanel.tsx
- Modify frontend/src/styles.css
- Modify frontend/e2e/workbench.spec.ts

**步骤**

1. 用 route mock 写失败流程：打开根目录、进入子目录、返回父目录、打开文本文件、处理 API 错误。
2. 目录只展示后端 entries；父路径由当前 payload.path 计算，所有请求仍由 ApiClient 编码。搜索只过滤当前已加载目录，不伪装递归 workspace 搜索。
3. 文件首次打开进入 preview；用户显式选择 Edit 才进入 textarea。二进制、越界、缺失等后端错误原样进入可恢复错误态。
4. truncated=true 时强制只读并显示截断原因；不提供 Edit 或 Save。包含替换字符的内容显示编码风险提示，不能静默宣称无损。
5. 编辑 buffer 与最后成功加载内容比较得到 dirty。关闭文件、切目录或关闭 WorkspacePanel 时若 dirty，显示保留/丢弃确认。
6. Save 先显示 path、UTF-8 byte count 与“将创建 snapshot”的确认；确认后调用 saveFile。失败时保留 buffer 和 dirty，成功时更新 baseline，并提供“查看对应 run”动作。
7. 自动或手动刷新不得覆盖 dirty buffer。未编辑且当前文件仍打开时，手动刷新可以显式重新读取。

**局部门禁**

    cd frontend && npm run test:e2e -- --grep "files"
    cd frontend && npm run typecheck && npm run lint

**提交**

    git commit -m "feat: add snapshot-backed file editor"

### Task 4：完成 Runs、Review、Diff 与 Restore

**Files**

- Create frontend/src/workspace/RunsView.tsx
- Modify frontend/src/workspace/WorkspacePanel.tsx
- Modify frontend/src/workspace/FilesView.tsx
- Modify frontend/src/styles.css
- Modify frontend/e2e/workbench.spec.ts

**步骤**

1. 写失败流程覆盖 run 列表、status/risk 组合过滤、选择详情、空 run、未知 run 与局部错误。
2. Run detail 直接渲染 summary、review、workflow、failure、patch_review、recovery、replay 与 tool_calls；数组保留顺序，对象字段使用明确标签，不用通用 JSON dump 取代产品界面。
3. Replay 明确标记 read-only。提供文本过滤，以及 All/Terminal 两种终态过滤；过滤只作用于已加载 replay/tool trace。
4. snapshots 显示 path 与 snapshot_path。Show diff 调用 getDiff，以可复制 unified diff 展示；truncated、current_exists、snapshot_missing 都有文字状态。
5. Restore 采用二次确认，明确目标 path、snapshot_path，以及结果可能为恢复旧内容或删除 run 新建文件。确认后才 POST。
6. Restore 成功后刷新 run detail、run list、health 和当前相关文件；失败时 diff 与上下文保持不变。
7. 不加入 Run Again、Execute、Run command 或 terminal 输入框；Workflow Hints 只允许复制命令。

**局部门禁**

    cd frontend && npm run test:e2e -- --grep "runs|snapshot|diff"
    cd frontend && npm run typecheck && npm run lint

**提交**

    git commit -m "feat: add run review and snapshot recovery"

### Task 5：完成 System、Settings、Tools 与资源详情

**Files**

- Create frontend/src/workspace/SettingsView.tsx
- Modify frontend/src/workspace/WorkspacePanel.tsx
- Modify frontend/src/App.tsx
- Modify frontend/src/styles.css
- Modify frontend/e2e/workbench.spec.ts

**步骤**

1. 写失败流程覆盖 readiness、workspace risk、memory review、settings load/save、server validation error、tools 与资源详情。
2. System Overview 使用 health 的真实 signals、checks、pending/active counts；memory 仅展示候选与生效项，不增加 accept/reject 管理动作。
3. Settings 表单仅包含后端写白名单。base_url、allowed_commands、loaded files、warnings 和 key 状态只读展示；没有密码输入框。
4. 如果当前全局 approval 是 never，显示只读警告并在 POST 中省略该值；可选的新值只有 risky-confirm 与 always。sandbox 只提供 read-only 与 workspace-write。
5. saveConfig 只发送发生变化的白名单键。服务端错误原样显示并保留 dirty 表单；成功后用响应 payload 建立新 baseline，并刷新 command spine 的 provider/model/key 状态。
6. Tools 只读显示 name、category、dry_run 等真实字段。没有启用、安装或配置按钮。
7. Resource detail 覆盖 summary、chats、runs、memory、snapshots；点击 chat 返回对应会话，点击 run 打开 Runs detail，点击 snapshot 进入 diff/restore 上下文。

**局部门禁**

    cd frontend && npm run test:e2e -- --grep "system|settings|resources"
    cd frontend && npm run typecheck && npm run lint
    .venv/Scripts/python.exe -m pytest tests/test_ui.py -q

**提交**

    git commit -m "feat: add frontend system workspace"

### Task 6：视觉、可访问性、响应式与性能收口

**Files**

- Modify frontend/src/styles.css
- Modify frontend/e2e/workbench.spec.ts
- Update frontend/e2e/workbench.spec.ts-snapshots/
- Modify frontend/scripts/check-ui-policy.mjs only if真实漏检被测试证明

**步骤**

1. 为 workspace 打开态增加确定性视觉基线：1440px desktop dark、1440px desktop light、390px、320px；至少覆盖 Files 编辑、Run attention、System readiness 三种状态。
2. 自动断言无横向滚动、无遮挡 CTA、diff 可滚动但不撑破页面、长 Windows 路径与长 run id 可断行或省略并保留 title。
3. 键盘覆盖：打开/关闭 panel、三入口切换、目录/文件选择、保存确认、run filter、diff/restore、settings submit；所有图标按钮有可访问名称和 Tooltip。
4. reduced-motion 下 workplane 无 spring 位移，Canvas 保持阶段 1 静态策略；功能和状态文字不减少。
5. npm run check:ui 必须继续报告 Lucide-only 且产品 emoji 为零。Payload 内用户内容不被改写。
6. 复跑现有 30 秒流式性能用例，并增加 workspace 打开与 run filter 的交互预算：无 long task 大于 100ms，不持续触发 layout thrashing。
7. 人工视觉审查只记录代理评分与证据，不写“Awwwards/FWA/CSSDA 获奖”。

**局部门禁**

    cd frontend && npm run check
    cd frontend && npm run test:e2e -- --update-snapshots
    git diff --check

**提交**

    git commit -m "test: verify frontend phase 2 workspace"

### Task 7：真实服务验收与阶段收口

**Files**

- Modify docs/frontend-vnext-phase0-parity-checklist.md
- Create docs/verification/frontend-vnext-phase2.md
- Modify CHANGELOG.md
- Modify docs/frontend-vnext-direction.md only if事实边界发生变化

**步骤**

1. npm run build:preview，用现有 Python Workbench 同源提供 /preview/；不提交 dist 或 staged preview。
2. 在真实服务验证文件浏览、保存、run 生成、diff、restore、config 写入、10 秒刷新、错误保留与旧根入口。
3. 对 config 与文件 mutation 使用专用临时 workspace；记录原文件、snapshot、恢复后内容和 project config 原子写证据，不污染仓库配置。
4. 完整回归后，逐项把 F1-F5、R1-R8、H3-H7、S3-S4 标为已完成，并链接验证文档；任何未通过项保持未完成，不用“基本完成”替代。
5. 验证文档记录自动门禁、浏览器矩阵、性能、视觉代理评分、已知限制与 rollback。
6. 根 / 仍返回旧 Workbench，/preview/ 返回 React 工作台。阶段 2 不切默认入口、不删除旧资源。

**最终门禁**

    cd frontend && npm ci && npm run check
    .venv/Scripts/python.exe -m pytest tests/test_frontend_contract.py tests/test_web.py tests/test_ui.py tests/test_docs.py -q
    .venv/Scripts/python.exe -m pytest -q
    git diff --check
    git status --short

**提交**

    git commit -m "docs: verify frontend vNext phase 2"

## 5. 验收矩阵

| Gate | 必须观察到的结果 |
| --- | --- |
| 入口 | 根 / 旧 Workbench 可用；/preview/ 工作台可打开且不是单页聊天孤岛 |
| 文件 | 目录、预览、编辑、dirty、确认保存、错误保留真实可用；截断文件不可保存 |
| 安全 | 越界路径由后端拒绝；保存有 snapshot；restore 二次确认；config 不能禁用审批或写密钥 |
| Runs | R1-R8 全部由真实 /api/runs 数据驱动；replay 与 workflow 明确只读 |
| Health | readiness、risk、memory 不被精简成一个颜色点，信号与检查项可读 |
| Refresh | 10 秒刷新不覆盖 dirty editor、dirty settings、确认 Dialog、chat approval 或 SSE |
| 资源 | chats/runs/memory/snapshots 可打开详情并跳转到真实上下文 |
| 可访问性 | 键盘、焦点、Dialog、标签、对比度、reduced-motion、320px 全通过 |
| 图标 | Lucide-only；产品界面零 emoji、零手写 SVG、零 Unicode 图形替代 |
| 性能 | 阶段 1 流式性能不回归；workspace 交互无大于 100ms long task |
| 回归 | npm 完整门禁、Python 全量 pytest、git diff --check 全通过 |
| 状态 | 只宣布 Phase 2 功能等价，不宣布长期 Frontend vNext 全部完成 |

## 6. 明确非目标

- 不切换 agent start 的默认根入口，不删除旧静态 Workbench。
- 不实现 Monaco、多标签编辑器、递归 workspace 搜索、Git 工作区、真实 terminal 或命令执行。
- 不实现 Provider 密钥输入、base_url 写入、allowed_commands 写入或任意 config editor。
- 不实现 MCP、Skills、Memory、Automation 的管理生命周期或生态 Marketplace。
- 不实现 replay 执行、run retry、浏览器验证命令执行或自动修复。
- 不改后端 HTTP schema、SSE、sandbox、snapshot、run store、config write 或安全责任。
- 不引入 React Router、TanStack Query、Redux、Zustand、Monaco、Markdown renderer、第二图标库、WebGL 或新依赖。
- 不恢复原型的大圆鼠标跟随效果，不添加常驻装饰动画。
- 不承诺 Awwwards、FWA、CSS Design Awards 的真实评审结果。

## 7. 停止条件与后续切换

出现以下任一情况时停止当前任务并补独立后端 spec：

- 现有 payload 缺少实现清单能力所必需的字段；
- 前端必须绕过 workspace path、snapshot 或 config allowlist 才能工作；
- 需要新增 mutation、执行 replay、写密钥或改变恢复语义；
- 必须改变旧 Adapter 才能让新 Adapter 工作。

Phase 2 全部验收后，只产出“默认入口切换准备就绪”结论。切换根入口、观察稳定期和删除旧壳是后续单独计划，需要用户再次明确授权。
