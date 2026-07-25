# Frontend vNext 默认入口切换 Readiness 实施计划

> 本计划只执行已批准设计中的 Readiness 阶段。根 `/` 在本阶段结束时仍返回旧 Workbench；Cutover 必须在全部证据通过后再次获得明确授权。

**Goal:** 把 React `/preview/` 从开发预览升级为 Git 与 Python wheel 均携带的运行时资产，增加稳定的 `/legacy/` 回滚入口，并建立 Python 实服、生成物一致性和 wheel 内容闭包门禁。

**Architecture:** 继续由 `src/agent/web/server.py` 作为唯一静态服务 Adapter；不把入口选择传入 CLI 或配置。Readiness 使用私有静态入口映射保持 `/` 为旧前端、`/preview/` 为 React、`/legacy/` 为旧前端。现有 Vite `base: "/preview/"` 和 `stage-preview.mjs` 保持不变，只维护一份 React bundle。

**Tech Stack:** 现有 Python `BaseHTTPRequestHandler`、pytest、React、TypeScript、Vite、Playwright、Node 标准库、Hatchling 和 pip；不增加依赖。

**状态：** 已执行，仅完成 Readiness；根 `/` 未切换。

Task 1-7 均已执行并通过对应门禁。验证使用独立候选 index/tree object，不修改真实
index，也不创建正式提交；根 `/` 仍返回旧 Workbench，默认入口 Cutover 仍需再次明确授权。

所有仓库级命令先设置 `$repository = 'F:\codex project\agent'` 并用
`Push-Location $repository` / `Pop-Location` 包裹；候选 worktree 命令显式使用
`$candidateRoot`。任何命令块都不得依赖上一个步骤遗留的当前目录。

## 0. 范围与保护规则

### 0.1 本阶段交付

- Git 跟踪 `src/agent/web/static/preview/**` 完整运行时资产。
- `/` → 旧 `index.html`。
- `/preview/` → React `preview/index.html`。
- `/legacy/` → 旧 `index.html`。
- `/preview`、`/legacy` 使用 308 规范化到带尾斜杠 URL，并保留查询字符串。
- HTML 响应增加 `Cache-Control: no-store`；JS、CSS、font 等资源维持现有策略。
- Python handler、真实 Python 服务和 wheel 都证明 preview 资产闭包完整。
- 文档最终只允许声明“默认入口切换就绪”。

### 0.2 明确排除

- 不把根 `/` 切换到 React。
- 不删除旧静态 Workbench。
- 不增加 feature flag、环境配置键、cookie、查询选择器或重定向层。
- 不修改 React 业务状态、HTTP/SSE payload、sandbox、snapshot、config 或 run store。
- 不修改 Vite `base`，不生成第二份 root bundle。
- 不增加依赖、Hatch build hook 或 binary packaging 工作。

### 0.3 批准的文件范围

除原设计范围外，本计划落实审查后已在 spec 中明确加入：

- `.gitattributes`：禁止 Git 在 Windows checkout 改写 Vite HTML 输入与 preview bundle 字节；
- `frontend/scripts/start-served-workbench.test.mjs`：wrapper 自动化负向测试；
- `tests/test_docs.py`：设计与完成声明契约；
- 本 spec 与本实施计划：批准/完成状态收口。

不得触及此范围之外的生产模块；若 wheel 实测要求修改 `pyproject.toml`，先停止并重新审核。

### 0.4 保护当前工作树

当前已有用户未提交改动，实施时必须：

1. 开始前记录 `git status --short` 及相关文件 diff。
2. 不执行 `git reset --hard`、`git clean` 或覆盖式 checkout。
3. 不使用 `git add -A`；共享文档只按精确 hunk 暂存。
4. 未经用户要求不 commit、不 push。
5. 若现有 hunk 无法与本任务安全分离，停止对应文档步骤并报告，不夹带提交。

## 1. Task 1：同步设计批准状态（已完成 2026-07-25）

**Files:**

- Modify: `docs/superpowers/specs/2026-07-25-frontend-vnext-default-entry-cutover-readiness-design.md`
- Modify: `docs/roadmap-progress.md`
- Modify: `tests/test_docs.py`

### Step 1：更新文档契约测试

将现有“草案、under review”断言改为：

- 设计已审核通过；
- 只授权 Readiness；
- 根 `/` 仍是旧 Workbench；
- Cutover 仍需再次明确授权。

### Step 2：运行 RED

```powershell
$repository = 'F:\codex project\agent'
Push-Location $repository
try {
    .\.venv\Scripts\python.exe -m pytest tests/test_docs.py `
      -k "frontend_vnext_default_entry_cutover_readiness" -q
    if ($LASTEXITCODE -ne 0) { throw 'Target documentation test failed.' }
} finally {
    Pop-Location
}
```

预期：在 spec 和 roadmap 状态尚未更新时失败。

### Step 3：最小更新状态文字

- spec 状态改为“审核通过，待实施；仅授权 Readiness，不授权切换根 `/`”。
- roadmap 改为设计已批准、Readiness 待实施。
- 不提前宣告 Readiness 已完成。

### Step 4：运行 GREEN

重新运行目标文档测试并确认通过。

## 2. Task 2：TDD 建立静态入口 seam（已完成 2026-07-25）

**Files:**

- Modify: `tests/test_web.py`
- Modify: `src/agent/web/server.py`

### Step 1：先写入口行为测试

使用临时 `STATIC_ROOT` 创建旧、新文档及一个非 HTML 资产，断言：

- `GET /` → 200、旧文档、HTML `no-store`。
- `GET /preview/` → 200、新文档、HTML `no-store`。
- `GET /legacy/` → 200、旧文档、HTML `no-store`。
- `GET /preview?from=bookmark` → 308，`Location: /preview/?from=bookmark`。
- `GET /legacy?from=rollback` → 308，`Location: /legacy/?from=rollback`。
- 未知目录仍为 404。
- 非 HTML 资源不带本次新增的 `no-store`。

建议拆成三个聚焦测试：入口映射、别名规范化、HTML 缓存策略。

### Step 2：运行 RED

```powershell
$repository = 'F:\codex project\agent'
Push-Location $repository
try {
    .\.venv\Scripts\python.exe -m pytest tests/test_web.py `
      -k "readiness_entrypoints or normalizes_stable_entrypoint_aliases or only_disables_caching_for_html" -q
} finally {
    Pop-Location
}
```

预期：`/legacy/`、308 和 HTML `no-store` 断言失败。

### Step 3：实现最小私有映射

在 `server.py` 中：

1. 增加模块私有入口映射：
   - `/` → `index.html`
   - `/preview/` → `preview/index.html`
   - `/legacy/` → `index.html`
2. 在现有 `urlparse` 路径分派中只处理 `/preview` 和 `/legacy` 两个固定别名。
3. 使用 `HTTPStatus.PERMANENT_REDIRECT`，`Location` 只由固定本地路径与原查询字符串组成。
4. 重定向响应使用空 body 与 `Content-Length: 0`。
5. `_send_static` 先应用入口映射，再沿用 containment、MIME、gzip 和安全头逻辑。
6. 仅当最终 MIME 为 `text/html` 时增加 `Cache-Control: no-store`。
7. 根 `/` 必须继续映射旧 `index.html`。

不新增 resolver class、策略对象、CLI 参数或通用目录重定向。

### Step 4：运行 GREEN 与回归

```powershell
$repository = 'F:\codex project\agent'
Push-Location $repository
try {
    .\.venv\Scripts\python.exe -m pytest tests/test_web.py -q
    if ($LASTEXITCODE -ne 0) { throw 'Static entry regression failed.' }
} finally {
    Pop-Location
}
```

## 3. Task 3：把 React bundle 升级为运行时资产（已完成 2026-07-25）

已删除精确忽略规则、重建 14 个 preview 文件，并通过资产闭包、候选 tree object
与 `tests/test_web.py` 回归。真实 index 未修改，候选 index 代替暂存门禁完成验证。

**Files:**

- Add: `.gitattributes`
- Modify: `.gitignore`
- Add: `src/agent/web/static/preview/**`
- Modify: `tests/test_web.py`

### Step 1：先增加资产闭包测试和缺失目录测试

新增两个测试：

1. 使用真实 `server.STATIC_ROOT / "preview"` 遍历全部 regular files，在同一个测试服务
   生命周期中请求每个相对 URL，断言 200 且未压缩响应 body 与源文件字节一致。
2. 临时 monkeypatch 到不含 `preview/` 的 `STATIC_ROOT`，断言 `/preview/` 为 404；证明
   测试确实能捕获运行时资产缺失，而不是依赖开发机残留目录假通过。

第一个属于发布资产验收测试；第二个提供明确的负向行为，不伪称生成物步骤本身为 TDD。

### Step 2：解除精确忽略规则并重建

只删除：

```text
src/agent/web/static/preview/
```

继续忽略 `frontend/dist/`。`.gitattributes` 对 `frontend/index.html` 与 preview 完整
文件树设置 `-text`，避免 Windows checkout 的 CRLF 转换改变 Vite HTML 输出或 bundle
字节；不修改现有
`frontend/scripts/stage-preview.mjs`，它已经先清理精确 target 再复制完整构建。

```powershell
$repository = 'F:\codex project\agent'
Push-Location "$repository\frontend"
try {
    npm run build:preview
    if ($LASTEXITCODE -ne 0) { throw 'Preview build failed.' }
} finally {
    Pop-Location
}
```

生成物不得手工编辑。

### Step 3：运行资产测试

```powershell
$repository = 'F:\codex project\agent'
Push-Location $repository
try {
    .\.venv\Scripts\python.exe -m pytest tests/test_web.py `
      -k "staged_preview_asset or missing_preview_assets" -q
    if ($LASTEXITCODE -ne 0) { throw 'Preview asset closure tests failed.' }
} finally {
    Pop-Location
}
```

### Step 4：执行生成物同步门禁

本轮未修改真实 index；Task 6 使用从 `HEAD` 初始化的独立候选 index 加入 `.gitignore`
与完整 preview 文件树，并在 detached worktree 重建后检查零漂移。正式提交获准后，再对
真实 index 运行以下等价检查：

```powershell
$repository = 'F:\codex project\agent'
Push-Location $repository
try {
    git diff --exit-code -- src/agent/web/static/preview
    if ($LASTEXITCODE -ne 0) { throw 'Preview bundle differs from staged assets.' }

    $untracked = git ls-files --others --exclude-standard -- src/agent/web/static/preview
    if ($untracked) { throw "Untracked preview assets remain:`n$untracked" }
} finally {
    Pop-Location
}
```

两项必须同时无输出；单独 `git diff` 不能发现新 hash 文件。

## 4. Task 4：增加 Python 实服 Playwright smoke（已完成 2026-07-25）

**Files:**

- Modify: `frontend/package.json`
- Modify: `frontend/tsconfig.json`
- Add: `frontend/playwright.served.config.ts`
- Add: `frontend/scripts/start-served-workbench.mjs`
- Add: `frontend/scripts/start-served-workbench.test.mjs`
- Add: `frontend/e2e-served/served-workbench.spec.ts`

served spec 必须放在新的 `frontend/e2e-served/`，不得放进 `frontend/e2e/`。现有
`playwright.config.ts` 是 `testDir: "./e2e"` 且没有 `testMatch`/`testIgnore`，默认 glob 会把
`e2e/` 下任何 `*.spec.ts` 收进 `npm run test:e2e`；served spec 一旦落在那里，就会被
`npm run check` 对着 Vite dev server 运行，`/api/health` 与 `Server: AgentWorkbench/` 断言
必然失败。而 `playwright.config.ts` 不在批准文件范围内，不能靠改它绕过。

### Step 1：先建立独立 served 测试入口

`package.json` 增加：

```json
"test:e2e:served": "playwright test --config playwright.served.config.ts"
```

专用配置必须：

- `testDir` 为 `./e2e-served`，与默认配置的 `./e2e` 完全隔离；
- `baseURL` 为 `http://127.0.0.1:4174`；
- `webServer.url` 为 `/api/health`；
- `reuseExistingServer: false`；
- `cwd` 为仓库根；
- 启动 Node wrapper，而不是 shell 拼接 Agent 命令；
- 使用独立测试输出目录。

同时把 `frontend/tsconfig.json` 的 `include` 从
`["src", "e2e", "vite.config.ts", "playwright.config.ts"]`
扩展为追加 `"e2e-served"` 与 `"playwright.served.config.ts"`。该 `include` 是显式白名单，
不扩展则 `npm run typecheck`（`tsc --noEmit`）根本不会检查新增的 served spec 与专用配置，
门禁会在一个它其实没看过的文件上"通过"。`eslint.config.js` 用
`files: ["**/*.{ts,tsx}"]` 且只忽略构建产物目录，已覆盖 `e2e-served/`，无需改动。

### Step 2：编写 served smoke

测试顺序：

1. 请求 `/api/health`，断言 200。
2. 断言 `Server` 头以 `AgentWorkbench/` 开头。
3. 注册 `requestfailed`、loopback 响应 `>= 400` 和 console error 收集器。
4. 加载 `/preview/`。
5. 断言 React Workbench 的稳定可访问元素可见。
6. 断言错误集合为空。

本阶段不增加根 `/` React 场景，也不复制现有 Vite 全量交互用例。

### Step 3：先写 wrapper 自动化负向测试

`start-served-workbench.test.mjs` 使用 Node 内置 `node:test`、临时目录和 fake
`AGENT_EXE`，先覆盖：

- 4174 已占用时 wrapper 在限定时间内非零退出；
- fake executable 把退让文案拆成多个 stdout/stderr chunk 时仍能被检测；
- fake executable 的非零退出码被传播；
- POSIX 上 wrapper 收到终止信号后 fake 子进程被终止；Windows 的 Node 信号为强制终止，
  因此用可等待 `done` 的显式控制握手验证相同清理语义；
- fake 子进程看到的 `HOME`、`USERPROFILE` 均为本次临时 home，且用户 home 中的
  sentinel config 不可见；
- 每条路径结束后精确临时 workspace 与临时 home 被删除；
- 4174/4175 均未留下本测试进程。

先运行并确认因 wrapper 尚未实现而失败：

```powershell
$repository = 'F:\codex project\agent'
Push-Location "$repository\frontend"
try {
    node --test scripts/start-served-workbench.test.mjs
    if ($LASTEXITCODE -eq 0) { throw 'Wrapper tests unexpectedly passed before implementation.' }
} finally {
    Pop-Location
}
```

### Step 4：实现 Node wrapper

只使用 Node 标准库：

1. wrapper 自行定位仓库根。
2. 为每次启动创建唯一临时 workspace 与临时 home；只把 workspace 传给 `--cwd`。
3. 子进程环境把 `HOME` 与 `USERPROFILE` 都指向临时 home，隔离 `Path.home()` 读取的
   全局 config、MCP 与 Skills；不修改父进程环境。
4. 从 `AGENT_EXE` 读取 executable，未设置时使用 PATH 中的 `agent`；另解析
   `AGENT_EXE_ARGS_JSON` 为 executable 前置参数数组，生产默认值为空。测试使用
   `AGENT_EXE=<node executable>` 与 `AGENT_EXE_ARGS_JSON=["<fake-agent.mjs>"]`，从而在
   Windows 上继续保持 `shell: false`。
5. 使用参数数组和 `shell: false` 启动，支持路径中包含空格。
6. 启动前尝试独占绑定 `127.0.0.1:4174`；占用则明确报错并非零退出。
7. 关闭探测 listener 后启动：

```text
<AGENT_EXE> start --cwd <TEMP_WORKSPACE> --host 127.0.0.1 --port 4174 --no-open-browser
```

8. 透传 stdout/stderr，并使用滚动缓冲检测跨 chunk 的：

```text
Port 4174 is busy; trying 4175.
```

9. 一旦检测到 CLI 端口退让，立即终止子进程并非零退出。
10. 转发退出信号并清理子进程；传播异常退出码。
11. 所有正常、异常和信号路径都只删除本次创建的精确临时 workspace 与临时 home。

### Step 5：运行 GREEN 与真实服务 smoke

```powershell
$repository = 'F:\codex project\agent'
Push-Location "$repository\frontend"
try {
    node --test scripts/start-served-workbench.test.mjs
    if ($LASTEXITCODE -ne 0) { throw 'Wrapper integration tests failed.' }
    $env:AGENT_EXE = (Resolve-Path "$repository\.venv\Scripts\agent.exe").Path
    npm run test:e2e:served
    if ($LASTEXITCODE -ne 0) { throw 'Python-served Playwright smoke failed.' }
} finally {
    Remove-Item Env:AGENT_EXE -ErrorAction SilentlyContinue
    Pop-Location
}
```

自动化 wrapper 测试承担 occupied-port、跨 chunk、退出码、清理和残留端口断言；不以
一次手工占端口操作代替。

## 5. Task 5：验证 wheel 资产闭包（已完成 2026-07-25）

**Files:** 默认不修改生产文件；结果写入 readiness 验收记录。

### Step 1：隔离构建 wheel

使用唯一的：

```text
D:\CodexScratch\agent-wheel-readiness-<timestamp>
```

把 TEMP、TMP、TMPDIR、pip cache 和 wheel 输出全部指向该目录。标准路径运行：

```powershell
$repository = 'F:\codex project\agent'
Push-Location $repository
try {
    .\.venv\Scripts\python.exe -m pip wheel . --no-deps `
      --wheel-dir "$wheelScratch\dist" `
      --cache-dir "$wheelScratch\cache"
    if ($LASTEXITCODE -ne 0) { throw 'Wheel build failed.' }
} finally {
    Pop-Location
}
```

`pip wheel .` 与后续字节比较脚本中的 `src/agent/web/static/preview` 都是仓库根相对
路径，必须在 `$repository` 下执行，否则会构建或比较错误项目。

隔离构建要求 Python package index 可达。只有当前环境已安装满足 `pyproject.toml` 要求的 Hatchling 时，才可明确选择 `--no-build-isolation`；验收记录必须注明，不得失败后静默降级。

### Step 2：比较路径和字节

使用 Python 标准库 `zipfile`：

- 源码 `src/agent/web/static/preview/**` 文件路径集合与 wheel 中 `agent/web/static/preview/**` 完全相等；
- 每个同名文件字节完全相等。

finally 恢复环境变量，并只删除本次创建的精确 scratch 目录。

### Step 3：失败策略

若 wheel 未包含 preview 文件：

1. 停止 Readiness；
2. 检查文件是否已被 Git 跟踪及 Hatchling file selection；
3. 只有实测证明默认选择不足时，另行提出最小 `pyproject.toml` 变更；
4. 不预先增加 Hatch build hook。

## 6. Task 6：验证干净 checkout 与重建确定性（已完成 2026-07-25）

普通 `git worktree add ... HEAD` 不包含未提交候选变更，禁止用它冒充 Readiness
验证。该门禁分为两个时点：

### Step 1：实施期间验证候选 index

本轮未获准修改真实 index，因此直接从 `HEAD` 初始化独立 `GIT_INDEX_FILE`，只加入本任务
批准文件并执行以下验证：

1. 强制使用独立 `GIT_INDEX_FILE`，从 `HEAD` 初始化临时 index；不得读取或修改真实
   index，也不得采用“保存当前 index 状态”的替代路径。
2. 只向临时 index 应用本任务精确 patch/文件；对生成物使用精确路径加入临时 index。
3. 检查临时 index 的 `git diff --cached --name-only` 与批准文件清单完全一致；出现任何
   用户原有 staged hunk 或计划外文件立即停止。
4. 对临时 index 执行 `git write-tree`，再以当前 `HEAD` 为 parent 用 `git commit-tree`
   创建仅用于验证的临时 commit object；不移动任何 branch，不创建正式提交。
5. 从该临时 commit 创建 detached 临时 worktree，并再次检查候选文件范围。

若无法把用户 hunk 与本任务 hunk 安全分离，则跳过实施期间 clean-checkout 声明，保留
为正式提交获准后的门禁；不得改用旧 `HEAD`。

### Step 2：无 Node 资产检查

在候选 worktree 中不执行 npm，断言存在：

- `src/agent/web/static/index.html`
- `src/agent/web/static/preview/index.html`

### Step 3：候选树重建零漂移

`$candidateRoot` 是 Step 1 创建的 detached 临时 worktree 绝对路径，例如
`D:\CodexScratch\agent-readiness-candidate-<timestamp>`；不得指向 `$repository`，否则
会在当前工作树上重建并污染用户改动。

```powershell
$candidateRoot = 'D:\CodexScratch\agent-readiness-candidate-<timestamp>'
if (-not (Test-Path -LiteralPath "$candidateRoot\.git")) {
    throw 'Candidate worktree path is not a git worktree.'
}

Push-Location "$candidateRoot\frontend"
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed in candidate worktree.' }
    npm run build:preview
    if ($LASTEXITCODE -ne 0) { throw 'Preview rebuild failed in candidate worktree.' }
} finally {
    Pop-Location
}

$status = git -C $candidateRoot status --porcelain=v1 --untracked-files=all -- `
  src/agent/web/static/preview
if ($status) { throw "Candidate rebuild changed preview assets:`n$status" }
```

预期无输出。完成后只移除本次 detached worktree；不移动当前分支，不使用 `git clean`
或 `reset --hard`。

### Step 4：正式提交后的最终门禁

如果用户之后授权提交，必须再从真实提交创建全新 clean checkout 重复 Step 2-3；只有
这次结果才能写作“提交后的干净 checkout 证据”。未授权提交时，验收记录明确写成
“候选 tree object 验证”，不得冒充提交后证据。

## 7. Task 7：文档与验收记录收口（已完成 2026-07-25）

**Files:**

- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap-progress.md`
- Modify: `tests/test_docs.py`
- Add: `docs/verification/frontend-vnext-default-entry-readiness.md`
- Modify: `docs/superpowers/plans/2026-07-25-frontend-vnext-default-entry-readiness.md`
- Modify: `docs/superpowers/specs/2026-07-25-frontend-vnext-default-entry-cutover-readiness-design.md`

### Step 1：先更新文档契约测试

断言最终状态：

- README 说明 tracked runtime assets 与重建流程；
- roadmap 和 verification 只声明“默认入口切换就绪”；
- 根 `/` 仍为旧前端；
- Cutover 仍需再次明确授权；
- 不存在“默认入口已切换”或“旧壳已退役”的完成声明；
- 本计划最终为“状态：已执行，仅完成 Readiness”，且不保留未完成 checklist；
- spec 最终状态只到“Readiness 门禁通过”，不写 Cutover 已完成。

### Step 2：更新 README

记录：

- Node 只属于开发/构建环境，Python runtime 不调用 npm；
- `/`、`/preview/`、`/legacy/` 当前入口矩阵；
- 修改前端源码后必须运行 `npm run build:preview` 并提交完整 bundle；
- bundle 同步检查方法；
- Cutover 尚未发生。

### Step 3：更新 CHANGELOG 与 roadmap

只允许声明：

> Frontend vNext 默认入口切换就绪。

同时明确根 `/` 仍为旧 Workbench、`/legacy/` 保留、旧前端未删除、Cutover 仍需再次授权。

### Step 4：新增 readiness 验收记录

沿用现有 verification 文档结构，记录本次实际证据：

1. 范围和排除项；
2. 入口矩阵；
3. Git bundle 零漂移；
4. Python HTTP 测试；
5. Python 实服 Playwright；
6. 端口冲突快速失败；
7. wheel 路径与字节闭包；
8. 干净 checkout 与重建零漂移；
9. 全量门禁；
10. 可见浏览器检查；
11. rollback；
12. 仅 Readiness 的完成声明。

所有通过数量和输出必须来自本次实际运行，不复制旧记录。

### Step 5：最后收口 spec 与 plan 状态

只有全部自动化、wheel、候选 clean tree 和可见浏览器门禁通过后：

- spec 状态改为“Readiness 门禁通过；根 `/` 未切换”；
- 本计划状态改为“已执行，仅完成 Readiness”；
- 将完成标准转换为已验证结果，不能保留未勾选项；
- 文档测试断言上述状态。

任何门禁未通过时保持“执行中/受阻”，不得提前收口。

## 8. 最终验证顺序

1. Python 目标测试、全量测试与 release 检查（同一仓库根上下文）：

```powershell
$repository = 'F:\codex project\agent'
Push-Location $repository
try {
    .\.venv\Scripts\python.exe -m pytest tests/test_web.py tests/test_docs.py -q
    if ($LASTEXITCODE -ne 0) { throw 'Targeted Python tests failed.' }

    .\.venv\Scripts\python.exe -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Full Python test suite failed.' }

    .\.venv\Scripts\agent.exe release doctor --cwd $repository
    if ($LASTEXITCODE -ne 0) { throw 'Release doctor failed.' }
} finally {
    Pop-Location
}
```

`release doctor` 使用绝对 `$repository` 而不是 `--cwd .`，避免从其他目录执行时诊断错误
workspace。

2. 前端全量 Vite 门禁：

```powershell
$repository = 'F:\codex project\agent'
Push-Location "$repository\frontend"
try {
    npm run check
    if ($LASTEXITCODE -ne 0) { throw 'Frontend check failed.' }
} finally {
    Pop-Location
}
```

3. wrapper 自动化负向门禁与 Python 实服门禁：

```powershell
$repository = 'F:\codex project\agent'
Push-Location "$repository\frontend"
try {
    node --test scripts/start-served-workbench.test.mjs
    if ($LASTEXITCODE -ne 0) { throw 'Wrapper tests failed.' }
    $env:AGENT_EXE = (Resolve-Path "$repository\.venv\Scripts\agent.exe").Path
    npm run test:e2e:served
    if ($LASTEXITCODE -ne 0) { throw 'Served E2E failed.' }
} finally {
    Remove-Item Env:AGENT_EXE -ErrorAction SilentlyContinue
    Pop-Location
}
```

4. wheel 路径集合与逐字节比较（Task 5）。
5. 候选 tree object 的无 Node 资产检查与重建零漂移检查（Task 6）。
6. 空白与范围检查：

```powershell
$repository = 'F:\codex project\agent'
Push-Location $repository
try {
    git diff --check
    if ($LASTEXITCODE -ne 0) { throw 'Whitespace check failed.' }
    git status --short
    git diff --name-only
    git diff --cached --name-only
} finally {
    Pop-Location
}
```

确认无 `frontend/src/**`、CLI、API、配置或计划外改动，也没有夹带用户原有 staged hunk。

7. 最终检查根 `/` 映射仍为旧 `index.html`：

```powershell
$repository = 'F:\codex project\agent'
Push-Location $repository
try {
    Select-String -Path 'src\agent\web\server.py' -Pattern '"/"\s*:\s*"preview/index.html"'
} finally {
    Pop-Location
}
```

该检查必须无匹配，作为禁止 Cutover 的自动化守卫。

## 9. 可见浏览器验收

启动真实 Python Workbench 后检查：

1. `/preview/`：React Workbench 正常加载；Files、Runs、System 可打开；无失败资源、loopback 4xx/5xx 或新增 console warning/error。
2. `/legacy/`：旧 Workbench 正常显示。
3. `/`：仍为旧 Workbench，作为禁止 Cutover 的最终人工门禁。
4. `/preview?manual=1` 与 `/legacy?manual=1`：308 到带尾斜杠地址且查询字符串保留。

## 10. 代码审查与质量门禁

代码完成后：

1. 使用 `code-reviewer` 审查实际 diff；修复所有 CRITICAL/HIGH。
2. 变更超过 30 行时运行项目规定的 `/ccg:verify-change` 与 `/ccg:verify-quality`。
3. 文件系统、HTTP 输入或外部进程相关变更按规则执行安全复核。
4. 修复后重新运行受影响测试及最终门禁。

执行记录：当前环境未提供 `/ccg:verify-change` 或 `/ccg:verify-quality` 的可调用工具，
仓库内也没有同名命令；没有伪造通过结果。实际使用 `code-review-and-quality` 五轴审查、
HTTP/进程/文件清理安全复核、全量 Python/前端门禁和候选树重建替代。

## 11. 逻辑批次

实施按以下批次推进；除非用户另行要求，不创建提交：

1. 设计批准状态与文档契约同步。
2. 静态入口 seam 与 Python HTTP 测试。
3. tracked preview bundle 与完整资产树测试。
4. Python-served Playwright 配置、wrapper 自动化负向测试和 smoke。
5. wheel、候选 tree object、文档与 readiness 证据收口。

## 12. 已验证结果

- `/` 仍返回旧 Workbench；`/preview/` 返回 React Workbench；`/legacy/` 返回旧 Workbench。
- `/preview` 和 `/legacy` 均以 308 保留查询字符串。
- 三个 HTML 入口均为 `Cache-Control: no-store`，非 HTML 资源未被统一设置为 `no-store`。
- preview 完整文件树进入候选 Git tree，并可由 Python handler 访问。
- Python 实服 smoke 确认服务来自 `AgentWorkbench`。
- wrapper 自动化测试覆盖 4174 占用、跨 chunk CLI 退让、异常退出、隔离和清理；Windows 使用显式 stop/done 控制握手，POSIX 另有信号转发用例。
- served smoke 使用独立临时 workspace 与 home，不读取仓库、用户 workspace 或用户级 config/MCP/Skills 状态。
- wheel 中 preview 路径集合和逐文件字节与源码完全一致。
- 候选 tree object 不执行 npm 也包含新旧入口，重建 bundle 后 porcelain 状态为空；获准提交后再重复真实 clean checkout。
- Python、frontend、release doctor、served E2E、wheel、diff 和可见浏览器门禁全部通过。
- 没有新增依赖、feature flag、配置键、第二份 bundle 或计划外文件。
- 文档只声明“默认入口切换就绪”，不声明 Cutover 或旧前端退役。
- 用户已有工作树改动未被覆盖、删除或夹带提交。
