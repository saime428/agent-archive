# Frontend vNext 阶段 1 App Shell 与 Chat 纵切 Implementation Plan

> **For implementation agents:** 严格按任务顺序执行。每项先建立可观察的失败，再做最小实现，跑完局部与相邻回归后只提交该任务涉及的文件。不要并行改同一文件，不要提前实现阶段 2。

**Goal:** 在不替换旧 Workbench 的前提下，交付可从 `/preview/` 使用的 React 前端，完成真实会话、SSE 流式状态、工具过程、审批、历史重建、主题、空间画布与响应式壳的阶段 1 纵切。

**Architecture:** Python Workbench 继续是唯一业务与安全事实来源；`frontend/src/api/` 是唯一 HTTP/SSE Adapter；聊天用纯 reducer 表达状态机；React 只接收离散状态，Canvas 2D controller 与 Motion values 承担连续帧；Vite 构建到 `frontend/dist/`，再复制到被 Git 忽略的 `src/agent/web/static/preview/`；旧静态前端 `/` 保持回退。

**Design Read:** 面向技术用户的本地 coding-agent 产品工作台，采用实验性空间构图与状态驱动动效，但聊天、审批、错误与恢复仍由真实、可选择、可复制、可键盘操作的 DOM 承载。

**Design Dials:** `DESIGN_VARIANCE 10 / MOTION_INTENSITY 9 / VISUAL_DENSITY 4`。这些值只授权高变化构图和强状态动效，不授权滚动劫持、自定义鼠标、随机粒子秀或牺牲可访问性。

**Tech Stack:** React 19、TypeScript strict、Vite、Tailwind CSS v4、Radix Dialog/Tooltip、Motion、Lucide React、原生 Canvas 2D、Vitest、Playwright、Python 3.11+ 与现有 pytest。npm 是唯一前端包管理器。

**Spec:** `docs/superpowers/specs/2026-07-23-frontend-vnext-phase1-shell-chat-design.md`

**Prototype:** `docs/design/frontend-vnext-spatial-prototype.html`

**状态：** 待执行

## 0. 开工前已核实的事实

- 仓库当前没有 `package.json`，也没有可复用的 React 工程。
- 旧前端位于 `src/agent/web/static/`；`/` 必须继续提供旧 `index.html`。
- `src/agent/web/server.py::_send_static` 当前只把根路径映射到 `index.html`。因此，即使构建文件已经复制，`/preview/` 仍会 404；只有 `/preview/index.html` 能命中文件。这与当前 spec 的验收入口冲突。
- 旧 `assets/sse.js` 注册 13 个消费者事件，其中包含 `observation`；后端 `agent/core/loop.py` 还会额外发 `capability_warning`。实现时应锁定 **14 个已知后端事件**，而不是继续沿用 spec 中的 13 这一过期计数。
- `/api/health` 当前没有 Git branch 字段；`final` payload 当前没有独立的 `changed_files` 与 `next_steps` 字段。界面不得从原型文案或模型正文猜测这些值。
- 后端没有“按 session 查询活跃 job”的端点。刷新恢复只能使用本标签页 `sessionStorage` 中的 `{job_id, session_id}` 尝试重连，失败后回退持久化会话。
- 当前开发机为 Node `25.6.0`、npm `11.18.0`。Vite 8 要求 Node `^20.19.0 || >=22.12.0`，计划将这个范围写入 `engines`。
- 2026-07-24 registry 快照中 TypeScript 最新版为 7.0.2，但 `typescript-eslint@8.65.0` 的 peer 范围是 `<6.1.0`，因此初始工程固定 TypeScript `6.0.3`，不安装不兼容的 7.x。

## 1. Global Constraints

- 旧 `src/agent/web/static/index.html` 与 `src/agent/web/static/assets/` 零改动；阶段 1 不切默认入口、不删除回退路径。
- 后端生产代码只允许两处静态交付调整：
  1. CSP 的 `style-src` 增加 `'unsafe-inline'`，`script-src 'self'` 保持不变；
  2. `_send_static` 对以 `/` 结尾的静态目录路径解析其 `index.html`，使 `/preview/` 可访问。
- 第 2 项是对已核实 404 的必要修正。Task 2 必须同步修订 spec 中“唯一后端改动”的旧表述；不得借机改 API、SSE、业务、数据或 history fallback。
- 前端不得直接调用 `fetch` 或 `EventSource`，只能经 `frontend/src/api/`；测试可注入 transport fake。
- 不引入 React Router、Redux、Zustand、TanStack Query、GSAP、Three.js、R3F、WebGL、第二图标库或 Markdown 渲染依赖。
- Hash 路由使用浏览器原生 `location.hash` 与 `hashchange`；阶段 1 路由只有新任务与 `#/chat/<session_id>`。
- 产品 chrome 只使用 `lucide-react` 的具名静态 import。零 emoji、零 Unicode 图形字符代替图标、零手写 SVG、零 whole-map 动态 import。
- 用户输入、模型输出、工具输出与文件内容必须原样保真；这些 payload 容器用 `data-payload` 标记，不受产品文案 emoji 门禁篡改。
- 不产品化原型中的大圆形鼠标跟随效果；使用系统鼠标。Canvas 只响应规范化指针位置，不绘制 cursor ring。
- 原型中的 `LIVEAGENT / NEXT`、假 branch、假设置、假命令面板、假 Files/Review 入口不得进入成品。只显示现有 API 能证明的能力和状态。
- 主题 token 从 `docs/design/frontend-vnext-visual-drafts.html` 的六组已定稿值迁移；品牌蓝紫只作单一平面强调，不生成通用紫色霓虹。
- 字体通过 `@fontsource-variable/geist` 与 `@fontsource-variable/geist-mono` 自托管打包，不向 Google Fonts 或其他运行时 CDN 发请求。
- 形状规则固定为：交互控制件 pill、内容面板 12px、代码/参数 8px。没有第四套圆角。
- 连续 pointer、velocity、Canvas 粒子与动画进度不得进入 React state；Motion 仅动画 `transform` 与 `opacity`。
- `prefers-reduced-motion: reduce` 时 Canvas 静止，spring/parallax/pointer physics 关闭，所有功能与状态文字保留。
- `frontend/node_modules/`、`frontend/dist/`、Playwright/Lighthouse/trace 临时产物、`src/agent/web/static/preview/` 均不进 Git；`package-lock.json`、视觉基线 PNG 与小型验证摘要进 Git。
- 实施时把 npm cache 与 Playwright 浏览器放到 `D:\CodexScratch`，不要让新依赖缓存默认落到 C 盘；D 盘不可用时先询问用户。项目源码与 `node_modules` 仍留在 F 盘项目内。
- 每个任务完成后运行 `git diff --check`，只暂存任务列出的文件。不得暂存既有未跟踪 handoff。

## 2. 依赖锁定

初始 scaffold 使用 `npm install --save-exact`，提交 lockfile。直接依赖按 2026-07-24 已核实版本锁定：

| 类别 | 包与版本 |
| --- | --- |
| Runtime | `react@19.2.8`、`react-dom@19.2.8`、`motion@12.42.2`、`lucide-react@1.26.0` |
| Radix | `@radix-ui/react-dialog@1.1.21`、`@radix-ui/react-tooltip@1.2.14` |
| Fonts | `@fontsource-variable/geist@5.3.0`、`@fontsource-variable/geist-mono@5.3.0` |
| Build | `vite@8.1.5`、`@vitejs/plugin-react@6.0.4`、`tailwindcss@4.3.3`、`@tailwindcss/vite@4.3.3` |
| Types | `typescript@6.0.3`、`@types/react@19.2.17`、`@types/react-dom@19.2.3`、`@types/node@26.1.1` |
| Quality | `vitest@4.1.10`、`@playwright/test@1.61.1`、`eslint@10.7.0`、`typescript-eslint@8.65.0`、`eslint-plugin-react-hooks@7.1.1`、`eslint-plugin-react-refresh@0.5.3`、`globals@17.7.0` |

不加入 DOM 测试库。Adapter、主题解析、router 与 reducer 设计为纯函数，用 Vitest node 环境覆盖；真实 DOM、焦点与可访问性由 Playwright 覆盖。

---

### Task 1: 建立最小前端工程与可重复门禁

**Files:**

- Modify: `.gitignore`
- Create: `frontend/package.json`、`frontend/package-lock.json`
- Create: `frontend/tsconfig.json`、`frontend/tsconfig.app.json`、`frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`、`frontend/eslint.config.js`、`frontend/index.html`
- Create: `frontend/src/main.tsx`、`frontend/src/App.tsx`、`frontend/src/styles.css`
- Create: `frontend/scripts/stage-preview.mjs`

**Interfaces:**

- Produces: `npm run dev|build|build:preview|typecheck|lint|test|test:run|check`；Task 6 再加入 `check:ui`，Task 10 再加入 `e2e`。
- Produces: Vite `base: '/preview/'`；dev proxy `/api` 到 `VITE_BACKEND_ORIGIN || http://127.0.0.1:8765`，且 `changeOrigin: false`。
- Produces: `stage-preview.mjs` 只允许把 `frontend/dist/` 复制到精确解析后的 `src/agent/web/static/preview/`。

- [ ] **Step 1: 建立失败基线**

Run: `test ! -f frontend/package.json`

Expected: exit 0，证明不是覆盖既有工程。

- [ ] **Step 2: 初始化最小 scaffold**

要求：

1. `package.json` 使用 ESM、`private: true`、Node engine `^20.19.0 || >=22.12.0`。
2. Tailwind v4 使用 `@tailwindcss/vite`，不创建旧式 PostCSS/Tailwind v3 config。
3. `App.tsx` 只提供可访问的加载基线，不提前写假 dashboard。
4. `stage-preview.mjs` 用 Node stdlib `fs.rm`/`fs.cp`；删除前断言目标目录名为 `preview`，父目录精确为仓库的 `src/agent/web/static`，拒绝任意调用方传入的路径。
5. `.gitignore` 增加依赖、构建、报告与 staged preview 目录，保留 lockfile。
6. `test:run` 暂用 `vitest run --passWithNoTests`，让空 scaffold 可验收；后续测试加入后仍执行全部测试。初始 `check` 串行执行 typecheck、lint、test:run 与 build。

依赖安装（PowerShell；缓存放 D 盘）：

```powershell
$env:npm_config_cache = "D:\CodexScratch\npm-cache"
Set-Location frontend
npm install --save-exact react@19.2.8 react-dom@19.2.8 motion@12.42.2 lucide-react@1.26.0 @radix-ui/react-dialog@1.1.21 @radix-ui/react-tooltip@1.2.14 @fontsource-variable/geist@5.3.0 @fontsource-variable/geist-mono@5.3.0
npm install --save-dev --save-exact vite@8.1.5 @vitejs/plugin-react@6.0.4 tailwindcss@4.3.3 @tailwindcss/vite@4.3.3 typescript@6.0.3 @types/react@19.2.17 @types/react-dom@19.2.3 @types/node@26.1.1 vitest@4.1.10 @playwright/test@1.61.1 eslint@10.7.0 typescript-eslint@8.65.0 eslint-plugin-react-hooks@7.1.1 eslint-plugin-react-refresh@0.5.3 globals@17.7.0
```

- [ ] **Step 3: 跑基础门禁**

Run: `cd frontend && npm ci && npm run typecheck && npm run lint && npm run build && npm run test:run`

Expected: 全部 exit 0；`dist/index.html` 资源 URL 以 `/preview/` 开头；仓库无 tracked build output。

- [ ] **Step 4: 验证 dev proxy 配置**

Run: `cd frontend && npm exec vite -- --host 127.0.0.1`

Expected: 启动日志无配置错误；实施时用 curl 或浏览器确认 GET `/api/health` 经代理成功，POST 的 Host/Origin 组合不触发 403。验证后立即停止进程。

- [ ] **Step 5: Commit**

```bash
git add .gitignore frontend/package.json frontend/package-lock.json frontend/tsconfig.json frontend/tsconfig.app.json frontend/tsconfig.node.json frontend/vite.config.ts frontend/eslint.config.js frontend/index.html frontend/src/main.tsx frontend/src/App.tsx frontend/src/styles.css frontend/scripts/stage-preview.mjs
git commit -m "build: scaffold frontend vNext preview"
```

---

### Task 2: 关闭 `/preview/` 静态交付与契约文档矛盾

**Files:**

- Modify: `src/agent/web/server.py`
- Modify: `tests/test_web.py`
- Modify: `docs/frontend-vnext-phase0-interface-inventory.md`
- Modify: `docs/superpowers/specs/2026-07-23-frontend-vnext-phase1-shell-chat-design.md`
- Modify: `CHANGELOG.md`

**Interfaces:**

- Consumes: Task 1 的 staged preview 目录约定。
- Produces: `/preview/` 安全映射到 `preview/index.html`，根 `/` 仍映射旧 `index.html`。
- Produces: CSP 仅增加 style `'unsafe-inline'`，script 仍只有 `'self'`。
- Produces: 文档统一为 14 个后端已知事件，并明确当前 payload 缺失字段。

- [ ] **Step 1: 写失败测试**

`tests/test_web.py` 追加：

- `test_workbench_serves_nested_directory_index`：monkeypatch `STATIC_ROOT` 到临时目录，分别放根与 `preview/index.html`，断言 `/preview/` 返回 preview 内容，`/` 仍返回旧根内容，`/preview/missing/` 404。
- `test_workbench_csp_allows_inline_style_but_not_inline_script`：断言 CSP 含 `style-src 'self' 'unsafe-inline'`，含 `script-src 'self'`，且 `script-src` 指令不含 `'unsafe-inline'`/`'unsafe-eval'`。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_web.py -q -k "nested_directory_index or csp_allows_inline_style"`

Expected: 两条 FAIL，分别暴露 `/preview/` 404 与 CSP 缺少 inline style。

- [ ] **Step 3: 最小生产改动**

1. `_send_static` 仅在 path 为空、为 `/` 或以 `/` 结尾时追加 `index.html`；继续交给 `static_file_path` 做 containment 检查。
2. CSP 只把 `style-src 'self'` 改为 `style-src 'self' 'unsafe-inline'`。
3. 不添加 `/preview` 专用 API route，不添加 history SPA fallback。

- [ ] **Step 4: 同步事实文档**

1. Phase 0 事件目录补 `observation`，说明 legacy 13 + backend-only `capability_warning` = 14。
2. Phase 1 spec 将事件计数改为 14，将允许的后端交付改动改为上述两处。
3. spec 明确 H1 不显示 branch，final 不承诺结构化 `changed_files`/`next_steps`，除非未来另写后端 Interface spec。
4. CHANGELOG 记录 preview 目录 index 与 CSP style 放宽，不宣传阶段 1 已完成。

- [ ] **Step 5: 回归**

Run: `python -m pytest tests/test_web.py tests/test_ui.py tests/test_docs.py -q`

Expected: 全部 passed；旧 `/` 静态行为与 API 安全测试不回归。

- [ ] **Step 6: Commit**

```bash
git add src/agent/web/server.py tests/test_web.py docs/frontend-vnext-phase0-interface-inventory.md docs/superpowers/specs/2026-07-23-frontend-vnext-phase1-shell-chat-design.md CHANGELOG.md
git commit -m "fix: serve frontend preview directory index"
```

---

### Task 3: 固化 Phase 1 REST 与事件契约

**Files:**

- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/client.test.ts`
- Create: `frontend/src/test/fixtures/chat-events.json`
- Create: `tests/test_frontend_contract.py`

**Interfaces:**

- Produces: `ApiError(status, message, payload)` 与可注入 `fetch` 的 `createApiClient`。
- Produces: `getHealth`、`listChats`、`getChat`、`startChat`、`decideApproval`、`renameChat`、`deleteChat`。
- Produces: 14 个已知事件的 discriminated union，加 `UnknownChatEvent` 宽容分支。

- [ ] **Step 1: 建立共享 JSON fixture**

fixture 分开记录：

- `legacy_consumer_events`：`chat_started`、`model_call_start`、`model_stream_start`、`model_stream_chunk`、`action_parsed`、`tool_start`、`approval_required`、`approval_granted`、`approval_denied`、`approval_timed_out`、`observation`、`final`、`error`；
- `backend_additional_events`：`capability_warning`；
- 正常流、全量重放、未知事件、审批批准/拒绝/超时、error 的代表 payload。

- [ ] **Step 2: 写失败测试**

- Vitest：成功 JSON、`{"error"}`、非 JSON 错误、空 body、正确 method/body/header、失败不重试。
- pytest：读取共享 JSON，解析 legacy `assets/sse.js` 的 `CHAT_EVENT_NAMES` 并断言顺序一致；断言 `agent/core/loop.py` 仍发 `capability_warning`；总已知事件数为 14。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd frontend && npm run test:run -- src/api/client.test.ts`

Run: `python -m pytest tests/test_frontend_contract.py -q`

Expected: client 测试因 Module 不存在失败；共享 fixture 已建立后，Python 契约测试应直接通过，证明红灯只来自待实现的前端 Adapter。

- [ ] **Step 4: 最小实现**

- `client.ts` 只做 URL、JSON、错误转换，不做 retry/cache/global toast。
- `types.ts` 的字段以 `settings.py`、`chats.py`、`chat_runtime.py` 与 `loop.py` 为准；未知对象字段保持 `unknown`，不滥用 `any`。
- 不把原型里的 branch、changed files、next steps 伪造进类型。

- [ ] **Step 5: 回归**

Run: `cd frontend && npm run typecheck && npm run lint && npm run test:run`

Run: `python -m pytest tests/test_frontend_contract.py tests/test_web.py -q`

Expected: 全部 passed。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api frontend/src/test/fixtures/chat-events.json tests/test_frontend_contract.py
git commit -m "feat: add typed frontend API contract"
```

---

### Task 4: 实现一次重连的 SSE Adapter

**Files:**

- Create: `frontend/src/api/sse.ts`
- Create: `frontend/src/api/sse.test.ts`

**Interfaces:**

- Consumes: Task 3 的 event union 与 fixture。
- Produces: `subscribeChatJob({ jobId, sessionId, onEvent, onRecover, onStatus }) -> unsubscribe`。
- Guarantees: sequence 去重、终态关闭、手动最多重连一次、第二次失败转历史恢复、已知 warning 透传、真正未知事件静默忽略。

- [ ] **Step 1: 写 transport fake 与失败测试**

覆盖：

1. 正常事件严格按 sequence 一次交付；
2. 重连从 0 全量重放时旧 sequence 不重复；
3. `final`/`error` 后 EventSource 立即 close；
4. 第一次断线创建第二条连接，第二次断线只调用一次 `onRecover(sessionId)`；
5. `capability_warning` 作为通用 notice 交付；未注册事件不抛错；
6. malformed JSON 关闭当前连接并进入同一有限恢复路径；
7. unsubscribe 取消后不再调用 handler。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test:run -- src/api/sse.test.ts`

Expected: FAIL，Module 不存在。

- [ ] **Step 3: 最小实现**

- 原生 EventSource 自动重连必须被 `close()` 接管，避免无限重试。
- 不使用 `Last-Event-ID`；`lastSequence` 只在前端内存持有。
- 由于命名 SSE 的未知 event 不会触发 `onmessage`，只为 14 个已知名注册 listener；其他名字由浏览器自然忽略。
- Adapter 不直接 fetch 历史，只发 `onRecover`，由 chat controller 调用 REST，保持 transport 与产品状态分离。

- [ ] **Step 4: 回归与 Commit**

Run: `cd frontend && npm run check`

```bash
git add frontend/src/api/sse.ts frontend/src/api/sse.test.ts
git commit -m "feat: add resilient chat event adapter"
```

---

### Task 5: 建立纯 Chat reducer 与历史映射

**Files:**

- Create: `frontend/src/chat/state.ts`
- Create: `frontend/src/chat/state.test.ts`
- Create: `frontend/src/chat/history.ts`
- Create: `frontend/src/chat/history.test.ts`

**Interfaces:**

- Consumes: Task 3/4 的 payload、事件与 fixture。
- Produces: `ChatState`、`chatReducer`、`historyToTranscript`。
- Guarantees: 活跃 job 的 chunk transcript 与持久化历史摘要是两种明确形态。

- [ ] **Step 1: 写失败测试**

逐事件覆盖：

- started -> thinking -> stream thinking/content/args -> action/tool -> observation -> approval -> granted/denied/timed_out -> final/error；
- 同 kind chunk 合并到同一 live block，不为每个 chunk 创建动画节点；
- action/approval 以 `action_index` 对应，乱序 resolution 不覆盖其他 action；
- capability warning 变成 notice；未知 event 不改变状态；
- 重复 sequence 幂等；
- history mapper 只映射 user、thinking_text、process、final/status，不伪装成逐 chunk replay。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test:run -- src/chat/state.test.ts src/chat/history.test.ts`

Expected: FAIL，Module 不存在。

- [ ] **Step 3: 最小实现**

- 用 `useReducer` 可直接消费的纯函数与只读类型；不引入状态库。
- transport 负责主去重，reducer 再以 sequence 做幂等防线。
- approval 倒计时不进入 reducer 的每秒 action；组件用本地时间推导显示，后端事件决定终局。

- [ ] **Step 4: 回归与 Commit**

Run: `cd frontend && npm run check`

```bash
git add frontend/src/chat/state.ts frontend/src/chat/state.test.ts frontend/src/chat/history.ts frontend/src/chat/history.test.ts
git commit -m "feat: model frontend chat state machine"
```

---

### Task 6: 主题、字体、图标与产品文案门禁

**Files:**

- Create: `frontend/src/theme/tokens.css`
- Create: `frontend/src/theme/theme.ts`
- Create: `frontend/src/theme/theme.test.ts`
- Create: `frontend/src/theme/ThemeProvider.tsx`
- Modify: `frontend/index.html`、`frontend/src/main.tsx`、`frontend/src/styles.css`
- Create: `frontend/src/ui/IconButton.tsx`
- Create: `frontend/scripts/check-ui-policy.mjs`
- Create: `frontend/scripts/check-ui-policy.test.mjs`

**Interfaces:**

- Produces: `<html data-theme="a|b|c" data-mode="dark|light">` 与无错主题闪烁的启动顺序。
- Produces: 统一 Lucide 默认 `18px / strokeWidth 1.75 / currentColor`，16/20px 只在调用点显式声明。
- Produces: 静态 UI policy 门禁。

- [ ] **Step 1: 写失败测试**

主题测试覆盖：

- storage theme/mode 优先；无手动 mode 时跟随 `prefers-color-scheme`；默认 theme B；
- 无系统浅色偏好时为 B dark；非法 storage 值回退；
- 写入/清除 manual mode；系统偏好变化只在 auto 模式生效。

policy 测试用临时 fixture 证明会拒绝：emoji/Extended Pictographic、`＋/⚙/⚠/✓/⏎` 等图形字符、产品 TSX 内 `<svg>`、第二图标库 import、`import * as Icons from 'lucide-react'`；同时允许 `data-payload` 运行时数据策略与测试 fixture 中的原始 payload。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test:run -- src/theme/theme.test.ts && node --test scripts/check-ui-policy.test.mjs`

Expected: FAIL，主题与 scanner 尚未实现。

- [ ] **Step 3: 最小实现**

1. 从视觉选稿页原样迁移 3×2 色彩 token，再增加字体、空间、圆角、阴影、spring、Canvas 渲染参数。
2. `index.html` 初始 B dark 并隐藏未 ready 的 body；`main.tsx` 在 mount React 前同步应用 storage/system 值并设置 ready，避免 inline script 与 CSP 冲突。
3. Fontsource CSS 由 Vite 打包；`font-display: swap`。
4. 主题切换无 transition；全页同一主题/模式。
5. scanner 扫产品源码，明确排除 `src/test/fixtures/`；运行时 payload 排除由 Task 10 的 Playwright 复核。
6. `package.json` 新增 `check:ui`，并把它加入 `check`；在这一步之前的 `check` 仍只运行 typecheck/lint/test/build。

- [ ] **Step 4: 门禁与 Commit**

Run: `cd frontend && npm run check:ui && npm run check`

```bash
git add frontend/index.html frontend/src/main.tsx frontend/src/styles.css frontend/src/theme frontend/src/ui/IconButton.tsx frontend/scripts/check-ui-policy.mjs frontend/scripts/check-ui-policy.test.mjs frontend/package.json frontend/package-lock.json
git commit -m "feat: add frontend theme and icon policy"
```

---

### Task 7: 产品化 Spatial App Shell

**Files:**

- Create: `frontend/src/shell/hash-route.ts`、`frontend/src/shell/hash-route.test.ts`
- Create: `frontend/src/shell/AppShell.tsx`
- Create: `frontend/src/shell/CommandSpine.tsx`
- Create: `frontend/src/shell/SessionRail.tsx`
- Create: `frontend/src/shell/SessionDrawer.tsx`
- Create: `frontend/src/shell/RightRevealBoundary.tsx`
- Create: `frontend/src/ui/ToastRegion.tsx`
- Modify: `frontend/src/App.tsx`、`frontend/src/styles.css`

**Interfaces:**

- Consumes: REST client、ThemeProvider、Radix Dialog/Tooltip。
- Produces: C1/C7 的会话导航壳、C2 的新任务入口结构、H1/H2 状态脊柱、S1/S2/S5 的结构基线；真正发送在 Task 9 接通。

- [ ] **Step 1: 写失败测试**

`hash-route.test.ts` 覆盖：空 hash、新任务、合法 session id、URL 编码、畸形 hash 回退、route -> hash 序列化。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test:run -- src/shell/hash-route.test.ts`

Expected: FAIL，Module 不存在。

- [ ] **Step 3: 实现 shell**

- command spine 只显示 workspace、provider/model、key 状态、provider notice、真实运行状态、主题/模式/Canvas 控制；不显示 branch 或未实现设置。
- 左缘 rail 提供新任务、搜索、按日分组、切换、重命名、删除；操作错误显示明文 live-region toast。
- 桌面 drawer 宽度用 CSS custom property clamp，并提供 pointer drag；resizer 使用 `role="separator"`、可聚焦、方向键调整。
- `<768px` 用 Radix Dialog 实现 modal sheet，chat 单列，composer 为 safe-area 预留。
- 右侧只画非交互 reveal boundary，`aria-hidden`；没有 Files/Review 假按钮。
- 视觉继承原型的边缘轨道、command spine、非对称留白与 kinetic hierarchy，但品牌改为真实 Agent Workbench。

- [ ] **Step 4: 局部门禁**

Run: `cd frontend && npm run check:ui && npm run check && npm run build:preview`

Expected: 全部 exit 0；`src/agent/web/static/preview/index.html` 生成但被 Git 忽略。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/styles.css frontend/src/shell frontend/src/ui/ToastRegion.tsx
git commit -m "feat: build spatial frontend shell"
```

---

### Task 8: 上下文场与统一物理动效

**Files:**

- Create: `frontend/src/canvas/context-field-controller.ts`
- Create: `frontend/src/canvas/context-field-controller.test.ts`
- Create: `frontend/src/canvas/ContextFieldCanvas.tsx`
- Create: `frontend/src/motion/tokens.ts`
- Modify: `frontend/src/shell/AppShell.tsx`、`frontend/src/styles.css`

**Interfaces:**

- Consumes: 离散 `idle|stream|tool|approval|final|error` 状态快照与主题 CSS variables。
- Produces: 一层 `aria-hidden`、`pointer-events:none` 的 Canvas 2D 上下文场；Motion spring token。

- [ ] **Step 1: 写 controller 失败测试**

用可注入的 RAF、ResizeObserver、document visibility、DPR 与 2D context fake 覆盖：

- DPR 上限 1.5；resize 后画布尺寸正确；
- 相同状态只更新 controller snapshot，不触发 React render API；
- hidden、disabled、not-intersecting、reduced-motion 停止循环；
- reduced-motion 只绘一帧；destroy 取消 frame/disconnect observer/remove listeners；
- context 获取失败返回 CSS fallback 状态，不抛到 App。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test:run -- src/canvas/context-field-controller.test.ts`

Expected: FAIL，Module 不存在。

- [ ] **Step 3: 最小渲染实现**

- 用 rAF timestamp 计算 delta，数量按 viewport 与最近 frame budget 自适应。
- pointer listener 只更新 controller 内普通对象；不绘制圆环，不修改 cursor。
- stream 提高流线密度，tool 形成短促定向脉冲，approval 收束并降低漂移，final/error 分别稳定/断开；变化可辨认但不盖住正文。
- DOM 面板只用共享 spring token与 transform/opacity；审批卡不 tilt、不 magnetic。
- CSS fallback 使用同主题 token 的静态材质，Canvas off 时功能完整。

- [ ] **Step 4: 门禁与 Commit**

Run: `cd frontend && npm run check`

```bash
git add frontend/src/canvas frontend/src/motion frontend/src/shell/AppShell.tsx frontend/src/styles.css
git commit -m "feat: add state-driven context field"
```

---

### Task 9: 接通真实 Chat 纵切

**Files:**

- Create: `frontend/src/chat/useChatController.ts`
- Create: `frontend/src/chat/useChatController.test.ts`
- Create: `frontend/src/chat/ChatStage.tsx`
- Create: `frontend/src/chat/ChatTranscript.tsx`
- Create: `frontend/src/chat/HistoryTurn.tsx`
- Create: `frontend/src/chat/LiveTurn.tsx`
- Create: `frontend/src/chat/ToolStep.tsx`
- Create: `frontend/src/chat/ApprovalCard.tsx`
- Create: `frontend/src/chat/Composer.tsx`
- Modify: `frontend/src/App.tsx`、`frontend/src/shell/AppShell.tsx`、`frontend/src/styles.css`

**Interfaces:**

- Consumes: REST/SSE Adapter、Chat reducer、hash route、shell、context field。
- Produces: C1-C9、H1 精简、H2 的完整真实纵切。

- [ ] **Step 1: 写 controller 失败测试**

把副作用切成可注入 client/stream/storage，覆盖：

- 新会话 start 后写 hash 与 `sessionStorage` active job；
- 发送中禁止二次发送，但后端 400 仍转可见错误；
- 进入会话先加载持久化历史，再挂当前 tab 的 active job；
- final/error 清理 active job；重连失败调用 history rebuild 并清理 stale job；
- rename/delete 成功刷新列表，冲突错误不丢当前 transcript。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm run test:run -- src/chat`

Expected: controller 测试 FAIL，UI Module 尚未实现；已有 reducer/history 测试保持绿。

- [ ] **Step 3: 实现完整状态 UI**

- loading、empty、streaming、retrying、disconnected、approval、final、error 都有明文与 Lucide 状态。
- thinking 可折叠；content 稳定追加；args/tool output 用可横向滚动的 `pre/code`；不做逐字符二次动画。
- phase 1 不新增 Markdown 依赖。模型正文用安全纯文本与 `white-space: pre-wrap`，结构化代码/参数由事件字段决定。若未来要富 Markdown，单独列为等价项。
- approval 使用 Lucide + 明文、action/args/reason、批准/拒绝与本地推算倒计时；后端 `approval_*` 事件是唯一终局事实。
- 原始用户/模型/工具输出容器标 `data-payload`，不清洗 emoji。
- composer 支持 IME；Enter 发送、Shift+Enter 换行；发送时 disabled 并保留可见 focus。
- 新消息自动滚动只在用户本就接近底部时发生，用户向上阅读时不抢滚动。
- 结构化 final 只渲染现有 payload 提供的 final/status/process/error 字段，不猜 branch/changed files/next steps。

- [ ] **Step 4: 门禁与手动 API smoke**

Run: `cd frontend && npm run check && npm run build:preview`

Run: `python -m pytest tests/test_web.py tests/test_frontend_contract.py -q`

Expected: 全部 passed。启动真实 Workbench 后，从 `/preview/` 用 fake provider 完成一次普通 final；console 无 fetch/SSE/CSP 错误。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/styles.css frontend/src/chat frontend/src/shell/AppShell.tsx
git commit -m "feat: connect frontend chat vertical slice"
```

---

### Task 10: 浏览器 E2E、视觉、可访问性与性能证据

**Files:**

- Create: `tests/support/frontend_preview_server.py`
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/chat-flow.spec.ts`
- Create: `frontend/e2e/shell-accessibility.spec.ts`
- Create: `frontend/e2e/visual.spec.ts`
- Create: `frontend/e2e/ui-policy.spec.ts`
- Create: `frontend/e2e/__screenshots__/` 中 6 组批准后的 PNG baseline
- Create: `docs/verification/frontend-vnext-phase1.md`
- Modify: `.gitignore`、`frontend/package.json`、`frontend/package-lock.json`

**Interfaces:**

- Produces: test-only Python server，复用真实 handler/ChatRuntime，但注入 deterministic streaming/approval FakeLLM；不改生产依赖注入面。
- Produces: 可重复 Playwright 关键流与 6 视口视觉 baseline。

- [ ] **Step 1: 先写浏览器失败测试**

关键流：

1. 新建 -> stream thinking/content/args -> tool -> final，无 console error；
2. approval approve 后同 turn 续跑到 final；
3. approval deny 显示拒绝终态且文件未写；
4. 刷新后 history 重建；active job 全量重放不重复；stale job 转历史恢复；
5. dev proxy POST 与 staged `/preview/` POST 均不 403；`#/chat/<id>` 刷新不 404；
6. 主题 A/B/C 与 auto/light/dark 切换、持久化、无错主题闪烁；
7. 键盘打开/关闭 sheet、遍历审批按钮、操作 rail resizer，focus 可见且不丢失；
8. reduced-motion 下 Canvas 为静态、DOM 无自动位移；Canvas disabled 后主流程仍完成；
9. 320×568 与 390×844 无横向滚动、CTA/文本不裁切、composer 位于 safe area 上方；
10. 运行时产品 chrome/accessible names 零 emoji/图形代图标，`[data-payload]` 被明确排除。

- [ ] **Step 2: 建立 deterministic test server**

- test helper 根据消息场景返回固定 stream、tool 与 write approval 序列；沿用现有 policy/sandbox/ChatRuntime，不 mock HTTP/SSE 封包。
- 端口由 `FRONTEND_E2E_PORT` 控制，默认 8767；workspace 用测试临时目录，进程退出清理。
- Playwright 配置两个 webServer：Python helper 在 8767 提供 staged `/preview/`，Vite 在 4173 以 `VITE_BACKEND_ORIGIN=http://127.0.0.1:8767` 提供 dev proxy；两者都用 health URL 作为 ready check。测试分 staged/dev 两个 project，避免把一种交付路径的通过误当成另一种。

首次运行前只安装 Chromium 到 D 盘。预计占用数百 MB，可复用，实际以安装输出为准；不写 C 盘默认 browser cache：

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "D:\CodexScratch\ms-playwright"
$env:npm_config_cache = "D:\CodexScratch\npm-cache"
Set-Location frontend
npx playwright install chromium
```

- [ ] **Step 3: 跑 E2E 确认从红到绿**

Run: `cd frontend && npm run e2e`

Expected: 初次因 UI/selector/flow 缺口 FAIL；修复产品代码后全部 passed，不放宽断言绕过问题。

- [ ] **Step 4: 生成并审查视觉 baseline**

必须覆盖：

- B dark 1440×900；B light 1440×900；
- B dark 390×844；B dark 320×568；
- A dark 1440×900；C light 1440×900。

人工逐张确认：无传统固定等宽三栏、无假入口、无横向溢出、无文字/CTA 裁切、主题层级一致、审批高于装饰、Canvas 不抢正文。

- [ ] **Step 5: 性能与交互证据**

- Chrome Performance：30 秒 stream + pointer + rail reveal；交互段平均目标 ≥55 FPS，无持续 long task；Canvas off/hidden 后无活跃 frame。
- Lighthouse：LCP <2.5s、INP <200ms、CLS <0.1。开发机波动指标记录实测值，不用修改测试数据伪造达标。
- 两条录屏：approve -> final；deny/error。重型 trace/video 放 `D:\CodexScratch\agent-frontend-vnext-phase1-evidence-<timestamp>\`，验证文档记录路径、SHA-256、时间与生成命令；6 张视觉 baseline 和小型结果摘要保留在项目。
- 内部评分表逐项给证据与分数：Awwwards proxy Design/Usability/Creativity/Content；CSSDA proxy UI/UX/Innovation。未达 spec 阈值不得标完成。

- [ ] **Step 6: Commit**

```bash
git add .gitignore frontend/package.json frontend/package-lock.json frontend/playwright.config.ts frontend/e2e tests/support/frontend_preview_server.py docs/verification/frontend-vnext-phase1.md
git commit -m "test: add frontend vNext browser acceptance"
```

---

### Task 11: 阶段验收、旧前端回归与文档收口

**Files:**

- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/roadmap-progress.md`
- Modify: `docs/frontend-vnext-phase0-parity-checklist.md`
- Modify: `docs/superpowers/specs/2026-07-23-frontend-vnext-phase1-shell-chat-design.md`
- Modify: `docs/superpowers/plans/2026-07-24-frontend-vnext-phase1-shell-chat.md`
- Modify: `docs/verification/frontend-vnext-phase1.md`
- Test: `tests/test_docs.py`（仅在现有文档断言需要时最小追加）

**Interfaces:**

- Consumes: Task 1-10 全部产物与证据。
- Produces: 可复核的阶段 1 交付说明；不切换默认前端。

- [ ] **Step 1: 跑完整自动门禁**

```powershell
$env:npm_config_cache = "D:\CodexScratch\npm-cache"
$env:PLAYWRIGHT_BROWSERS_PATH = "D:\CodexScratch\ms-playwright"
Set-Location frontend
npm ci
npm run check:ui
npm run typecheck
npm run lint
npm run test:run
npm run build:preview
npm run e2e
Set-Location ..
python -m pytest -q
git diff --check
```

Expected: 全部 passed；测试完成后 `git status --short` 不出现 build/report 临时产物。

- [ ] **Step 2: 双入口手动 smoke**

- `/`：旧会话、文件、设置、runs/review 核心入口可打开；console 无 CSP 回归。
- `/preview/`：普通 final、approve、deny、刷新恢复、主题/模式、mobile sheet、Canvas off 全部通过。
- Vite dev 模式重复一次 POST start/approval，确认 `changeOrigin:false` 未触发 403。

- [ ] **Step 3: 按矩阵收口文档**

- 只在证据已通过后把 C1-C9、H1（精简）、H2、S1、S2、S5 标为阶段 1 complete。
- README 增加开发、构建、staging、`/preview/` 与回退说明；明确最终用户运行不需要 Node。
- CHANGELOG 描述真实完成能力与两处静态交付调整。
- spec 与本 plan 状态改为已执行，记录日期和验证摘要。
- roadmap 只把阶段 1 标完成，阶段 2 保持未开始；不宣布前端迁移完成。

- [ ] **Step 4: 最终 diff 审计**

Run: `git diff --stat && git diff --check && git status --short`

逐项确认：无旧静态前端改动、无 tracked build output、无第二图标库、无手写 SVG、无假 route/设置入口、无 backend API/业务漂移、无 unrelated handoff staged。

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md docs/roadmap-progress.md docs/frontend-vnext-phase0-parity-checklist.md docs/superpowers/specs/2026-07-23-frontend-vnext-phase1-shell-chat-design.md docs/superpowers/plans/2026-07-24-frontend-vnext-phase1-shell-chat.md docs/verification/frontend-vnext-phase1.md tests/test_docs.py
git commit -m "docs: close frontend vNext phase 1"
```

## 3. 明确非目标

- Monaco、文件树、diff、terminal、runs/review、完整 settings、Providers/MCP/Skills/Memory/Automation 管理面。
- 默认入口切换、旧前端删除、桌面壳、安装包、远程访问、Marketplace。
- 后端事件 schema 新字段、Last-Event-ID、分页、按 session 查询 active job、history route fallback。
- 富 Markdown、语法高亮、结构化 changed files/next steps。需要时先更新等价矩阵或写独立 Interface spec。
- WebGL/3D、GSAP、滚动劫持、自定义 cursor、音频、多 Canvas、装饰性持续动画。
- 外部奖项提交、获奖声明或营销落地页。

## 4. 完成定义

只有以下条件同时满足，阶段 1 才可标为完成：

1. `/` 旧 Workbench 与 `/preview/` 新纵切同时可用；
2. C1-C9、H1 精简、H2、S1、S2、S5 有自动或人工证据；
3. build/typecheck/lint/Vitest/Playwright/pytest 全绿；
4. 图标与文案门禁零违规，payload 保真；
5. 六组视觉基线、两条交互路径、reduced-motion、320px、性能与内部评分均达 spec；
6. Git 只包含源码、测试、lockfile、必要基线与验证摘要，不包含依赖、构建目录、重型临时证据或无关文件；
7. 旧前端仍是默认入口，阶段 2 尚未被误报为完成。
