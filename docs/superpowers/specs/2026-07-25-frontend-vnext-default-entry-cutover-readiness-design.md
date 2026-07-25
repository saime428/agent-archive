# 设计：Frontend vNext 默认入口切换就绪

- 日期：2026-07-25
- 状态：Readiness 门禁通过；根 `/` 未切换
- 上位方向：[Frontend vNext 方向](../../frontend-vnext-direction.md)
- 前置证据：[Frontend vNext 阶段 2 验收记录](../../verification/frontend-vnext-phase2.md)

## 结论

先完成“可发布、可回滚、可验证”，再单独切换默认入口：

1. 把现有 `/preview/` 构建产物变成 Git 与 Python 包都能携带的运行时资产；
2. 保持 `/preview/`，新增 `/legacy/`，让两个前端都有稳定入口；
3. 本切片结束时根 `/` **仍返回旧 Workbench**；
4. 全部门禁通过且用户再次授权后，后续切换提交只把根 `/` 的静态入口映射
   从 `index.html` 改为 `preview/index.html`；
5. 切换后仍保留 `/legacy/`，回滚只需恢复这一处映射，不迁移数据、不重建资产。

不增加运行时 feature flag、配置键、重定向层或第二份 React 构建。现有两个前端
已经是两个真实 Adapter；静态入口映射就是足够小的 seam。

## 背景与代码事实

1. `agent start` 与 `agent ui` 共用 `serve_workbench`；`--open-browser` 打开根 URL，
   因此默认入口由 `src/agent/web/server.py::_send_static` 决定，不在 CLI。
2. 当前 `_send_static("/")` 解析 `src/agent/web/static/index.html`，即旧 Workbench；
   `/preview/` 解析 `preview/index.html`。
3. React 使用 hash 路由（`#/new`、`#/chat/<id>`），不需要 Python SPA fallback；
   在 `/` 与 `/preview/` 下都能复用同一份路由实现。
4. Vite `base` 当前固定为 `/preview/`，生成的 HTML 引用
   `/preview/assets/<hash>.js|css`。Vite 官方说明 `base` 会重写嵌套部署路径的
   资产 URL；因此根 `/` 可以直接提供同一份 HTML，无需再构建一份 `/assets/`
   版本：[Vite public base path](https://vite.dev/guide/build.html#public-base-path)。
5. `npm run build:preview` 将 `frontend/dist/` 复制到
   `src/agent/web/static/preview/`，但后者被 `.gitignore` 排除。干净 checkout
   不具备该目录，直接切根会 404。
6. 本项目使用 Hatchling。Hatch 默认尊重 VCS ignore；被忽略的构建产物只有显式
   配为 artifact/force-include 才会进入构建选择：
   [Hatch file selection](https://hatch.pypa.io/latest/config/build/#file-selection)。
7. Phase 2 已有真实服务、自动化与可见浏览器证据，但其完成声明明确不包含默认入口
   切换、旧壳删除或发布资产策略。

## 目标

1. 干净 checkout 在**不安装 Node、不先运行 npm**的情况下执行 `agent start`，
   仍具备旧、新两个完整前端资产集。
2. 建立唯一静态入口 seam，明确 readiness、cutover、rollback 三种映射结果。
3. 让 React `index.html` 引用的每个本地 JS/CSS/font 资产都可在 Python 静态服务
   与包内容中找到，避免“源码门禁通过、安装后白屏”。
4. 根文档不被陈旧缓存阻碍切换或回滚；HTML 响应使用 `Cache-Control: no-store`。
   RFC 9111 规定 `no-store` 响应不得被缓存复用：
   [RFC 9111 §5.2.2.5](https://www.rfc-editor.org/rfc/rfc9111.html#section-5.2.2.5)。
5. 保持 HTTP/SSE Interface、安全链、工作区数据、会话、run、snapshot 与配置
   语义不变。
6. 把“就绪完成”“默认入口已切换”“旧前端已删除”分成三个不同完成声明。

## 设计

### 1. 静态入口 seam

不新增公开 Interface，也不把入口选择传进 CLI/config。`server.py` 内保留一个私有
入口映射，`_send_static` 继续负责 containment、MIME、gzip 与响应头：

| URL | Readiness 实施完成后 | 后续 Cutover | Rollback |
| --- | --- | --- | --- |
| `/` | `index.html`（旧） | `preview/index.html`（新） | `index.html`（旧） |
| `/preview/` | `preview/index.html`（新） | 同左 | 同左 |
| `/legacy/` | `index.html`（旧） | 同左 | 同左 |
| `/assets/*` | 旧前端资产 | 同左 | 同左 |
| `/preview/assets/*` | React 哈希资产 | 同左 | 同左 |

实施使用现有 `_send_static` 内的一份私有映射，不增加 resolver class、策略对象或
运行时开关。Readiness 与 Cutover 的代码差异应只有根 `/` 对应值的一行变化。

规范入口都带尾斜杠。`/preview` 与 `/legacy` 分别返回 `308` 到 `/preview/` 与
`/legacy/`，保留查询字符串；测试同时覆盖两种无尾斜杠形式，避免手工输入回滚地址时
得到 404。该规范化只处理这两个固定别名，不增加通用目录重定向或 SPA fallback。

`/preview/` 不重定向到 `/`：既有书签、验收脚本与资产 namespace 继续稳定。
`/` 也不 30x 到 `/preview/`：产品 URL 保持根路径，浏览器无需额外往返。继续使用
hash 路由，不增加 history fallback。

### 2. React 产物发布

`src/agent/web/static/preview/` 从临时预览输出升级为**受版本控制的运行时资产**：

- 删除 `.gitignore` 对该目录的排除；`frontend/dist/` 继续忽略；
- `frontend/scripts/stage-preview.mjs` 仍是唯一发布 Adapter，先清理精确 target，
  再复制本次完整构建，避免残留旧 hash 文件；
- `vite.config.ts` 的 `base: "/preview/"` 不变，一份产物同时服务 `/` 与
  `/preview/`；
- Node 只属于开发/构建环境，Python 运行时不调用 npm、不读取 `frontend/`；
- 不新增 Hatch build hook。跟踪后的文件位于 `src/agent` 包目录，沿用现有 Python
  包选择；实现验收再构建 wheel 并检查内容，避免只靠推断。

产物同步门禁分两个上下文：评审通过并获准暂存后，先暂存精确的 `preview/` 文件树，
再运行 `npm run build:preview`；此时
`git diff --exit-code -- src/agent/web/static/preview` 必须为 0，且
`git ls-files --others --exclude-standard -- src/agent/web/static/preview` 必须无输出。
前者检查构建后相对暂存内容没有漂移，后者补上新 hash 文件；`git diff` 不能单独
作为门禁。最终提交的干净 checkout 再运行构建时，
`git status --porcelain=v1 --untracked-files=all -- src/agent/web/static/preview`
必须无输出。porcelain v1 是供脚本消费的稳定格式：
[Git status porcelain](https://git-scm.com/docs/git-status#_porcelain_format_version_1)。

不新增自定义 Vite manifest。`index.html` 只能证明入口 JS/CSS，不能覆盖 CSS 中的
字体等二级引用；资产闭包改由三项现有边界共同证明：构建后 bundle 零状态差异、
Python 实服浏览器 smoke 无失败请求，以及 wheel 内 `preview/` 文件集合与源码目录
完全相等。

### 3. HTML 缓存与安全头

`_send_static` 对 `text/html` 增加 `Cache-Control: no-store`；JSON/SSE 现有策略与
哈希资产传输保持不变。这样入口切换或回滚后刷新会重新取入口文档，同时不把所有
字体、CSS、JS 强行设为 no-store。

CSP、loopback Host 校验、跨源写拒绝、路径 containment、gzip 协商全部沿用现有
实现。切换不新增 inline script、service worker 或跨源资源。

### 4. 测试 seam

测试只跨现有 HTTP Interface 与静态文件 Interface，不测试私有映射实现细节：

1. `tests/test_web.py` 使用临时 `STATIC_ROOT`，在 readiness 状态断言 `/` 与
   `/legacy/` 返回旧文档、`/preview/` 返回新文档，未知目录仍 404；三个 HTML
   响应都有 `Cache-Control: no-store`。另断言 `/preview` 与 `/legacy` 各自以 `308`
   规范化到带尾斜杠 URL，并保留查询字符串。
2. 真正 Cutover 提交把同一测试的根 `/` 期望改为新文档；`/legacy/` 断言不变。
3. `tests/test_web.py` 遍历实际 `STATIC_ROOT/preview/` 文件树，通过 Python handler
   请求每个文件并断言 200；旧 `index.html` 与 `/assets/*` 既有契约测试保留。
4. 现有 `playwright.config.ts` 继续负责 Vite 开发服务器全量门禁，并保持不在本切片
   文件范围内。因此 served spec 不得放进它的 `testDir: "./e2e"`：现有配置没有
   `testMatch`/`testIgnore`，默认 glob 会把 `e2e/` 下任何 `*.spec.ts` 收进
   `npm run test:e2e`，导致 served spec 被对着 Vite dev server 运行并必然失败。
   served 资产改放独立目录：新增 `frontend/e2e-served/served-workbench.spec.ts`、
   `playwright.served.config.ts`（`testDir: "./e2e-served"`）和
   `scripts/start-served-workbench.mjs`。专用配置的
   `webServer` 必须以仓库根为 `cwd`，执行 Node wrapper；
   wrapper 通过环境变量 `AGENT_EXE` 选择可执行文件，未设置时使用 PATH 中的 `agent`，
   为每次运行创建并最终清理独立临时 workspace 与临时 home，并以参数数组和
   `shell: false` 启动
   `<AGENT_EXE> start --cwd <TEMP_WORKSPACE> --host 127.0.0.1 --port 4174 --no-open-browser`。
   子进程环境把 `HOME` 与 `USERPROFILE` 都指向临时 home，隔离 `Path.home()` 读取的
   全局 config、MCP 与 Skills 状态；不得修改父进程环境。为便于 Windows 无 shell 测试，
   wrapper 另接受 `AGENT_EXE_ARGS_JSON` 作为 executable 前置参数数组，生产默认值为空，
   测试用它执行 `node fake-agent.mjs`。Windows 本地验收显式设置
   `AGENT_EXE=.venv\\Scripts\\agent.exe`；配置不得硬编码 Windows 路径。
5. 专用配置必须设置 `reuseExistingServer: false`。Node wrapper 在启动前绑定 4174
   做独占性预检；若端口已占用则非零退出。启动后 wrapper 透传子进程输出，一旦发现
   CLI 的 `Port 4174 is busy; trying 4175.` 退让消息，立即终止子进程并非零退出，覆盖
   预检与实际绑定之间的竞争窗口。测试不得复用已有 Vite/Agent 服务，也不得改测后续
   端口；wrapper 还必须在收到退出信号时终止子进程并清理精确临时 workspace，避免
   泄漏服务器或测试状态。
   `start-served-workbench.test.mjs` 使用 Node 标准库和 fake `AGENT_EXE` 自动验证端口
   占用快速失败、跨 chunk 退让检测、退出码传播、子进程终止和临时 workspace 清理；
   这些负向检查是门禁，不以手工步骤代替。
   smoke 首先请求 `/api/health`，断言响应 `Server` 头以 `AgentWorkbench/` 开头，作为
   服务类型的第二层检查。
6. smoke 从 Python 服务访问 `/preview/`，并对 `requestfailed`、loopback 响应
   `>= 400` 和控制台 error 失败。`npm run test:e2e:served` 固定映射到
   `playwright test --config playwright.served.config.ts`。Playwright 官方支持由
   `webServer.command` 启动被测服务：[Playwright web server](https://playwright.dev/docs/test-webserver)。
7. Cutover 提交只给同一个 Python 实服 smoke 增加根 `/` 场景，覆盖启动、普通
   final 与工作台打开；API 可复用现有 mock，但 HTML 和静态资产必须来自 Python
   服务。不复制现有全量用例，也不把 Vite dev server 当成切换证据。
8. wheel 验收比较完整文件闭包：源码 `src/agent/web/static/preview/**` 中的全部文件，
   必须与归档 `agent/web/static/preview/**` 的路径集合及逐文件字节内容完全相等，
   而不是只检查 `index.html` 的直接引用。该检查不把 binary packaging 纳入本切片。

wheel 构建默认使用仓库现有 pip 的隔离构建，不要求 `.venv` 预装 Hatchling；官方
等价命令是 `pip wheel --no-deps .`：[pip wheel](https://pip.pypa.io/en/stable/cli/pip_wheel/)。
隔离构建会在空 cache 中解析 `[build-system]` 的 Hatchling，因此标准门禁明确要求
Python package index 可达。离线验收只有在当前环境已安装满足 `pyproject.toml` 要求的
Hatchling 时，才可改用 `--no-build-isolation`；验收记录必须注明使用了该等价路径，
不得在失败后静默降级。

Windows 验收先创建唯一的 `D:\CodexScratch\agent-wheel-readiness-<timestamp>`，把
`TEMP`、`TMP`、`TMPDIR` 和 pip cache 都指向该目录，然后执行：

```powershell
$wheelScratch = Join-Path 'D:\CodexScratch' ("agent-wheel-readiness-" + (Get-Date -Format 'yyyyMMddHHmmss'))
$oldTemp, $oldTmp, $oldTmpDir = $env:TEMP, $env:TMP, $env:TMPDIR
$oldErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Stop'
    New-Item -ItemType Directory -Force -Path "$wheelScratch\dist", "$wheelScratch\cache", "$wheelScratch\tmp" | Out-Null
    $env:TEMP = "$wheelScratch\tmp"
    $env:TMP = $env:TEMP
    $env:TMPDIR = $env:TEMP
    .\.venv\Scripts\python.exe -m pip wheel . --no-deps `
      --wheel-dir "$wheelScratch\dist" --cache-dir "$wheelScratch\cache"
    if ($LASTEXITCODE -ne 0) { throw "Wheel build failed with exit code $LASTEXITCODE." }
    $wheel = Get-ChildItem -LiteralPath "$wheelScratch\dist" -Filter '*.whl' -File | Select-Object -First 1
    if (-not $wheel) { throw 'Wheel build produced no archive.' }
    .\.venv\Scripts\python.exe -c 'from pathlib import Path; from zipfile import ZipFile; import sys; src={"agent/"+p.relative_to("src/agent").as_posix() for p in Path("src/agent/web/static/preview").rglob("*") if p.is_file()}; z=ZipFile(sys.argv[1]); packed={n for n in z.namelist() if n.startswith("agent/web/static/preview/") and not n.endswith("/")}; assert src == packed, (sorted(src-packed), sorted(packed-src)); mismatched=sorted(n for n in packed if z.read(n) != (Path("src")/n).read_bytes()); z.close(); assert not mismatched, mismatched' $wheel.FullName
    if ($LASTEXITCODE -ne 0) { throw 'Wheel preview asset paths or contents do not match the source tree.' }
} finally {
    $env:TEMP, $env:TMP, $env:TMPDIR = $oldTemp, $oldTmp, $oldTmpDir
    if (Test-Path -LiteralPath $wheelScratch) {
        Remove-Item -LiteralPath $wheelScratch -Recurse -Force -ErrorAction Stop
    }
    $ErrorActionPreference = $oldErrorActionPreference
}
```

命令用 Python 标准库 `zipfile` 同时断言路径集合相等和逐文件字节相等；无论成功
或失败都恢复临时环境变量并删除这个精确的临时目录。

### 5. 两阶段发布

#### A. Readiness（已通过）

- 跟踪 React 运行时资产；
- 新增 `/legacy/`；
- 增加 HTML no-store 与资产闭包测试；
- 更新开发/发布说明；
- 根 `/` 仍是旧 Workbench；
- 全部门禁通过后，状态只能写“默认入口切换就绪”。

#### B. Cutover（需再次明确授权）

- 仅把根 `/` 映射改为 `preview/index.html`；
- 更新根入口 HTTP 测试、一个根路径 Playwright smoke、README/roadmap/verification；
- 可见浏览器验证 `/` 新前端与 `/legacy/` 旧前端；
- 保留 `/preview/` 和 `/legacy/`，不删除任何旧资产；
- 状态可写“默认入口已切换”，仍不可写“Frontend vNext 全部完成”。

Rollback 不需要新构建：恢复根映射并重启 `agent start`。由于前后端共用同一
HTTP/SSE Interface，回滚不修改会话、run、snapshot、config 或 memory 数据。

## 消费者

| 消费者 | 行为 |
| --- | --- |
| `agent start` / `agent ui` | Readiness 后仍打开旧根；Cutover 后自然打开新根，无 CLI 分支 |
| 既有 `/preview/` 用户与 E2E | URL 与资产路径不变 |
| 回滚用户 | `/legacy/` 始终直达旧 Workbench |
| Python wheel / 干净 checkout | 自带 React 运行时资产，不要求 Node |
| 前端开发者 | 修改源码后必须重新 stage 并提交 bundle |
| 后端 HTTP/SSE | 无 Interface 或行为变化 |

## 预计文件范围

Readiness 实施只允许触及：

- `.gitattributes`
- `.gitignore`
- `src/agent/web/static/preview/**`（生成物）
- `src/agent/web/server.py`
- `tests/test_web.py`
- `frontend/package.json`
- `frontend/tsconfig.json`
- `frontend/playwright.served.config.ts`
- `frontend/scripts/start-served-workbench.mjs`
- `frontend/scripts/start-served-workbench.test.mjs`
- `frontend/e2e-served/served-workbench.spec.ts`
- `README.md`、`CHANGELOG.md`、`docs/roadmap-progress.md`
- `tests/test_docs.py`
- 本 spec 与对应实施计划的状态收口
- 新的 readiness 验收记录

served spec 必须放在 `frontend/e2e-served/`，不得放进 `frontend/e2e/`：现有
`playwright.config.ts` 是 `testDir: "./e2e"` 且无 `testMatch`/`testIgnore`，默认
`**/*.spec.ts` 会把 served spec 一并收进 Vite 门禁并对着 dev server 运行，必然失败。
目录隔离让默认配置无需修改，因此 `frontend/playwright.config.ts` 保持在范围之外。

`frontend/tsconfig.json` 在范围内，因为它的 `include` 是显式白名单
（`src`、`e2e`、`vite.config.ts`、`playwright.config.ts`）。新目录 `e2e-served` 与
`playwright.served.config.ts` 不在其中，`npm run typecheck` 会静默跳过它们，
留下一个本切片依赖的门禁盲区。`eslint.config.js` 用 `**/*.{ts,tsx}` 且只忽略构建
产物目录，已覆盖新路径，保持在范围之外。

Cutover 提交只允许触及：

- `src/agent/web/server.py`
- `tests/test_web.py`
- `frontend/e2e-served/served-workbench.spec.ts`
- `README.md`、`CHANGELOG.md`、`docs/roadmap-progress.md`
- `tests/test_docs.py`
- 本 spec 的状态收口
- readiness 验收记录

若实现需要修改 React 业务状态、HTTP payload、sandbox/snapshot/config 写语义，
停止本切片并另写 spec；那不是入口切换问题。

## 非目标

- 本 spec 提交不实现 Readiness、不切换根 `/`、不删除旧静态 Workbench。
- 不增加用户可配置的 frontend selector、环境变量、cookie、查询参数或灰度系统。
- 不把 Vite `base` 改为 `/`，不维护 root/preview 两份 bundle。
- 不新增 router/state 库、service worker、CDN、远程 host 或跨源部署。
- 不实现 Monaco、真实 terminal、Git 工作区、生态中心或 Phase 3 功能。
- 不引入 Electron/Tauri、签名安装包、自动更新或完整发布流水线。
- 不改变 API、SSE、审批、安全、日志、snapshot、run store 或配置格式。
- 不按时间自动删除 `/legacy/`；删除旧壳必须另有使用证据与明确授权。

## 验收标准

### Readiness 完成门禁

- 干净 checkout 不运行 npm，也存在旧、新两套静态入口文件。
- 获准暂存后重建 bundle，工作树相对暂存内容零差异且无未跟踪 hash 文件；干净
  checkout 重建后的 bundle 路径 porcelain 状态无输出。
- `/` = 旧、`/preview/` = 新、`/legacy/` = 旧；均为 200，HTML 为 no-store；
  `/preview` 与 `/legacy` 以 `308` 保留查询字符串并规范化到带尾斜杠 URL。
- Python 实服 smoke 禁止复用已有服务器；Node wrapper 对 4174 做启动前占用检查并
  拒绝 CLI 端口退让，端口冲突或竞争时快速失败；被测响应确认来自 `AgentWorkbench`，
  加载 `/preview/` 时无失败请求、loopback 4xx/5xx 或控制台 error。
- wheel 中 React 文件的路径集合和逐文件内容均与源码 `preview/` 目录相等；临时输出
  只落 D 盘并清理，隔离构建的联网前提或离线等价路径已记录。
- `npm run check`、全量 `pytest -q`、`agent release doctor`、
  `npm run test:e2e:served`、`git diff --check` 全部通过。
- 可见浏览器检查 `/preview/` 与 `/legacy/`，控制台无新增 warning/error。
- 根 `/` 未切换；没有 feature flag、新依赖或计划外文件。

### Cutover 激活门禁

- 用户在 Readiness 证据通过后再次明确授权。
- `/` 与 `/preview/` 都呈现同一 React Workbench；`/legacy/` 呈现旧 Workbench。
- `agent start --open-browser` 打开根 URL 并进入 React 工作台。
- 根路径完成普通 final、Files、Runs、System、保存确认与恢复确认 smoke；
  `/legacy/` 仍可完成旧前端启动 smoke。
- 根 HTML 刷新不复用旧入口文档；hash 深链在 `/` 与 `/preview/` 均可恢复。
- 全量 Python/前端门禁再次通过，文档只宣告默认入口已切换。

## 完成声明

| 状态 | 允许声明 | 禁止声明 |
| --- | --- | --- |
| 本 spec 仍为草案 | 已起草候选切换设计 | 设计已确认、Readiness 已实现、根已切换 |
| 本 spec 审核通过 | 切换设计已确认 | Readiness 已实现、根已切换 |
| Readiness 门禁通过 | 默认入口切换就绪 | 根已切换、旧壳已退役 |
| Cutover 门禁通过 | 默认入口已切换，可通过 `/legacy/` 回滚 | Frontend vNext 长期路线完成 |
| 未来旧壳删除门禁通过 | 旧前端已退役 | Phase 3-5 已完成 |
