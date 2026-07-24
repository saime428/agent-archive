# 设计：Frontend vNext 阶段 1 —— App Shell 与 Chat 纵切

- 日期：2026-07-23
- 状态：草案（已双轴审查与视觉增补修订，待实施）
- 上位方向：[Frontend vNext 总方向](../../frontend-vnext-direction.md)
- 阶段 0 基线（本 spec 的事实来源，不重复其内容）：
  - [HTTP/SSE Interface 契约清单](../../frontend-vnext-phase0-interface-inventory.md)
  - [功能等价清单](../../frontend-vnext-phase0-parity-checklist.md)
  - [视觉方向选稿](../../design/frontend-vnext-visual-drafts.html)（仅保留主题 token 与
    信息架构参考，不再作为最终布局、图标或动效样式来源）
  - [Spatial 交互视觉原型](../../design/frontend-vnext-spatial-prototype.html)（用于
    感受空间构图与状态叙事，不代表后端已接通或阶段 1 已实施）

## 背景

阶段 0 已交付：19 个端点与 13 个 SSE 事件的契约清单、34 项功能等价矩阵、
视觉方向决议。旧静态 Workbench（`src/agent/web/static/`）继续作为现网基线
与回退路径。本阶段目标：用真实纵切证明新架构能跑完整任务——
发起 → 流式输出 → 工具过程 → 审批 → final——不是搭一个空壳。

视觉决议（2026-07-23，用户定稿）：**三主题可切换，默认 B**。

| 主题 | 气质 | 主强调色 | 原生模式 |
| --- | --- | --- | --- |
| A | 暗色·终端质感 | 青绿 `#2dd4a7` | 深 |
| B（默认） | 中性·IDE 质感 | 蓝紫 `#7c86f5` | 深 |
| C | 纸感冷静（深浅双色） | 琥珀 `#e08b3c` 深 / `#b45309` 浅 | 深 |

每主题含深浅两套值、同一组语义 token 变量名（已在选稿页验证）。上位方向
文档"一个主强调色"按主题内解释：每主题一个强调色，主题间不同。

## 视觉增补决议（2026-07-24）

本节覆盖 2026-07-23 视觉选稿中"中性 IDE 三栏工作台"的表现层决议，不改变
阶段 1 的功能范围、HTTP/SSE Interface、安全链、三主题能力与旧前端回退路径。
选稿页中的固定三栏、普通面板卡片、Unicode 图形符号只视为历史原型，不得直接
产品化。

**Design Read：面向技术用户的 coding agent 产品工作台，以 Awwwards 式实验性
数字画布为视觉语言，采用先锋排版、状态驱动的生成式渲染和物理动效，同时保持
高风险操作的清晰度与可访问性。**

- 设计参数：`DESIGN_VARIANCE 10 / MOTION_INTENSITY 9 / VISUAL_DENSITY 4`。
- 质量目标：以 Awwwards、FWA、CSS Design Awards 每日最佳作品作为对标集；
  对标指内部设计与工程门禁，不宣称或保证获得外部奖项。
- Awwwards 公开权重转成内部评审矩阵：Design 40%、Usability 30%、
  Creativity 20%、Content 10%；目标总分不低于 8.0/10，任何单项不低于
  7.5/10。CSSDA 的 UI、UX、Innovation 各自也不得低于 8.0/10。评分仅是
  项目验收代理，不冒充外部评委结论。
- 三主题保留，但只改变同一视觉系统的色彩、材质与渲染参数，不形成三套互不
  相干的页面。任一时刻全页只有一个主题与一个模式，不做区块级主题反转。
- 默认 B 的蓝紫强调色保留为用户已定稿品牌信号，但只作单一平面强调色，不扩散
  成通用 AI 紫色霓虹、发光按钮或无语义渐变。
- 实验性不能牺牲任务完成率：聊天正文、工具参数、审批、错误与恢复仍由可选择、
  可复制、可键盘操作的真实 DOM 承载；艺术渲染层不承载唯一语义。

## 审查修订记录（2026-07-23）

双轴审查对照代码核实后修订的 5 处，均已并入下文：

1. **CSP 冲突（原 CRITICAL）**：现有 `style-src 'self'` 无 `unsafe-inline`，
   会拦掉 React 与 Radix 运行时注入的 inline style。决策：放宽 `style-src`
   加 `'unsafe-inline'`（仅样式），`script-src` 保持严格 `'self'`。这是本
   阶段**唯一**允许的后端改动（见 §2b），不改任何 API/业务/数据。
2. **SPA 深链 404（原 HIGH）**：`_send_static` 只对 `/` 兜底 index.html。
   采用 **hash 路由**规避，零后端路由改动（§4）。
3. **dev proxy 写保护（原 HIGH）**：`_origin_matches_host` 要求 origin 端口
   == host 端口，proxy 必须 `changeOrigin: false` 保留原始 Host，否则 POST
   全 403（§1）。
4. **Vite base（原 MEDIUM）**：部署在 `/preview/` 下必须设
   `base: '/preview/'`，否则资源 404 白屏（§1）。
5. **会话重建语义（原 MEDIUM）**：`build_chat_payload` 的历史 turns 是
   RunStore 重建的过程摘要+思考文本，非逐 chunk 流式回放；C8 重建终态与
   摘要，不承诺流式回放（§5）。

## 目标

1. 建立 React + TypeScript + Vite 工程（`frontend/`），构建产物由现有
   Python Workbench 服务器同源提供。
2. 主题系统：三主题 × 深浅模式，语义 token 单一来源；默认主题 B，模式跟随
   `prefers-color-scheme`，可手动覆盖，选择持久化于 `localStorage`。
3. App Shell：单行 command spine、左缘会话轨道、中央 Chat 主舞台；右侧工作台
   本阶段只保留 reveal 边界/入口（内容属阶段 2），不渲染空列或假面板。
4. Chat 纵切达到等价清单 C1-C9 + H1（精简）+ H2：会话列表/新建/重命名/删除、
   SSE 流式（thinking/content/args）、工具过程、审批（含超时态）、终态渲染、
   刷新重建、未知事件宽容。
5. 数据访问收敛为一个 Adapter Module：页面不散落 `fetch`、事件游标与错误
   转换（上位方向的前后端 seam 要求）。
6. 旧前端零改动；新前端经**临时预览入口**并行访问。后端仅放宽一处 CSP
   头（§2b），不动任何路由、API、业务逻辑或数据。
7. 图标系统只使用 `lucide-react`：全界面零 emoji、零 Unicode 图形符号代替
   图标、零手写 SVG、零第二图标库。
8. 浏览器作为统一交互画布：用一层原生 Canvas 2D 生成式"上下文场"连接导航、
   对话与任务状态，DOM 交互层用 Motion 的 spring / motion value 实现连续、
   有重量感且不触发 React 每帧重渲染的物理反馈。
9. 把"奖项级"转成可验收门禁：真实浏览器视觉审查、响应式与键盘路径、
   reduced-motion、渲染性能、图标/emoji 静态检查和内部评分矩阵必须全部通过。

## 设计

### 1. 工程与交付形态

- 新目录 `frontend/`：Vite + React 19 + TypeScript strict + Tailwind CSS +
  Radix primitives + Motion + `lucide-react`。包管理器 npm（仓库无既有前端
  约定，取最低摩擦项）。
- 生成式背景优先使用浏览器原生 Canvas 2D，不在阶段 1 引入 Three.js、R3F、
  GSAP 或第二套动画系统。只有 Canvas 2D 经性能与视觉实测无法达到本 spec
  的明确场景时，再为 WebGL 单独写决策；不为"可能更炫"提前增加依赖。
- **Vite `base: '/preview/'`**：产物部署在子路径，base 不设则资源引用
  `/assets/*` 会 404 白屏（审查修订 4）。
- 构建输出 `frontend/dist/` → 复制进 `src/agent/web/static/preview/`
  （`static_file_path` 已允许子目录，核实 `STATIC_ROOT in candidate.parents`
  通过；构建产物**不进 git**，`.gitignore` 增补）。
- 临时预览入口：`http://127.0.0.1:<port>/preview/`。旧前端仍是 `/` 默认；
  Python 端不加路由。
- 开发模式：Vite dev server + `server.proxy` 把 `/api` 代理到 Python 端口，
  **必须 `changeOrigin: false`**（审查修订 3）：后端
  `_origin_matches_host` 要求 Origin 端口 == Host 端口，changeOrigin=true 会
  把 Host 改成后端端口而 Origin 仍是 dev 端口 → POST 全部 403。保留原始 Host
  头 + 同源相对 fetch（`Sec-Fetch-Site: same-origin`）才通过写保护。GET/SSE
  不受写保护影响（只校验 loopback Host）。

### 2. 数据 Adapter（`frontend/src/api/`）

唯一与后端对话的 Module，对外暴露类型化接口：

- `client.ts`：REST 封装。统一错误转换（`{"error"}` → 类型化 `ApiError`
  含 HTTP 状态）；无重试（后端本地、失败即显示）。
- `sse.ts`：`subscribeChatJob(jobId, handlers)`。实现契约清单 §4 全部语义：
  - 按 `sequence` 去重（重连 = 从 0 全量重放）；
  - 终态（`final`/`error`）后关闭；
  - 断线自动重连一次，仍失败则转入"从持久化重建"路径；
  - job TTL 过期（unknown job）→ 回退 `GET /api/chats/<id>` 重建 UI；
  - 未知事件名忽略（`capability_warning` 等透传为通用提示行）。
- `types.ts`：端点 payload 与 13 个 SSE 事件的 TS 类型，字段名以后端为准；
  阶段 1 只精确化 Chat 纵切用到的事件，其余 `unknown` 兜底。

### 2b. CSP 放宽（唯一后端改动）

`src/agent/web/server.py::_send_security_headers` 的 CSP 中，`style-src 'self'`
改为 `style-src 'self' 'unsafe-inline'`。其余指令**全部不动**，尤其
`script-src 'self'` 保持严格。

安全论证：inline **style** 无法执行脚本，不是 XSS 的执行向量；XSS 的主要
执行面是 inline **script**，由保持严格的 `script-src 'self'` 挡住。放宽
style 是业界对 React/Radix 这类运行时定位样式的常见妥协，风险等级远低于放宽
script。Radix 的无障碍（键盘/焦点/ARIA）依赖其 inline 定位，保留它比自建
无障碍组件更可靠（方向文档硬性要求 a11y）。

- 这是本阶段唯一后端改动；改一行响应头，不碰路由、API、业务、数据。
- 回归：旧前端在放宽后的 CSP 下行为不变（它本就不违反 style-src）；
  `tests/test_web.py` / `test_ui.py` 若断言 CSP 原文需同步更新（实施时核对）。
- 记录：本决策的理由写入 CHANGELOG 与本 spec，不埋在代码注释里。

### 3. 主题系统（`frontend/src/theme/`）

- `tokens.css`：从选稿页迁移六组变量（3 主题 × 2 模式），变量名与选稿页
  一致（`--bg`/`--panel`/`--panel-2`/`--border`/`--text`/`--text-dim`/
  `--text-faint`/`--accent`/`--accent-soft`/`--ok`/`--warn`/`--danger`/
  `--chip-bg`），并补齐排版、空间、材质、阴影与渲染参数 token。Tailwind、
  DOM 动效和 Canvas 只读取语义 token，不各自维护第二套色值。
- `<html data-theme="a|b|c" data-mode="dark|light">` 驱动；`ThemeProvider`
  管初始化（localStorage → 系统偏好 → 默认 B/深）与切换。
- 主题切换保留选稿页的功能语义，但按新图标与空间语言重做；**不做切换过渡
  动画**（选稿页教训：过渡冻结计算值；且 reduced-motion 优先）。
- 排版采用一套自托管可变无衬线 display + 一套等宽 code 字体；禁止运行时向
  第三方字体服务发请求。空态与阶段切换可用超大字号、窄宽对比和非对称留白，
  但聊天正文、代码和审批信息保持稳定字号、行长与基线，不做抖动或形变。
- 形状系统固定为"控制件胶囊 / 内容面板 12px / 代码块 8px"三档，除此之外
  不增加任意圆角值；阴影与材质均从主题 token 读取。

### 3b. 图标与可见文案

- 唯一图标源：`lucide-react`。使用具名静态 import，依赖 tree-shaking；禁止
  动态加载整个 icon map，禁止引入其他 icon package，禁止复制 Lucide SVG path。
- 全局图标规格：默认 `size={18}`、`strokeWidth={1.75}`、颜色继承
  `currentColor`；密集状态行可用 16px，主要动作可用 20px，其他尺寸需在
  组件旁说明原因。
- 历史原型中的 `＋ / ⚙ / ⚠ / ✓ / ⏎` 分别改为 `Plus / Settings /
  TriangleAlert / Check / SendHorizontal`；类似符号一律按语义选 Lucide，
  不用字符近似。
- 可见界面、tooltip、toast、空态、错误态、加载态、按钮、标签、会话标题和
  assistive text 中禁止 emoji。标点、数学符号、代码原文不属于图标，但不得
  用 Unicode pictograph 冒充动作或状态图标。
- 禁令针对产品自有 chrome、文案与装饰，不篡改用户输入、模型输出、工具输出
  或文件内容中的原始字符；这些 payload 是数据，不是 UI icon。自动测试必须
  明确排除 payload 容器，避免为了过门禁破坏内容保真。
- 装饰图标保持 Lucide 默认 `aria-hidden`；icon-only 按钮必须把准确的
  `aria-label` 放在 `button` 上并提供 tooltip。审批、危险、失败等关键状态
  始终使用"Lucide 图标 + 明文"，不得只靠颜色或图形表达。
- 品牌 wordmark、Canvas 生成式纹理和纯 CSS 几何背景不是操作图标，不受
  Lucide 形状限制；它们不得模拟另一套可识别的 icon family。

### 4. App Shell（`frontend/src/shell/`）

- **路由：hash 路由**（审查修订 2）。`_send_static` 只对 `/` 兜底
  index.html，history 路由下刷新 `/preview/chat/xxx` 会 404；hash 路由
  （`/preview/#/chat/xxx`）所有深链都落到 `/preview/` 这一个真实文件，零
  后端 fallback。阶段 1 会话不多，hash 足够；如未来需要 history 路由再评估
  后端 SPA fallback（属后端改动，另议）。
- Shell 不是固定 `230px / 1fr / 300px` 的传统三栏。桌面使用非对称 spatial
  stage：会话导航是可展开的左缘轨道，Chat 是有明确阅读锚点但可随上下文偏移的
  主舞台，阶段 2 工作台位置以右缘 reveal handle 预留。区域变化使用弹性边界，
  仍满足 S1 的可折叠与可调宽语义。
- 顶部状态信息压缩成单行 command spine：workspace、分支（`/api/health`
  有则显示）、provider/model、key 状态、主题/模式切换。不可用的设置入口不渲染；
  所有状态图标用 Lucide 并附文字或 accessible name。
- 左缘轨道：新任务、会话搜索（本地过滤）、按日分组会话、重命名/删除。展开时
  显示完整信息，收起时只保留可识别 Lucide 动作与当前会话锚点；409 类错误用
  明文 toast 呈现。键盘顺序始终与视觉顺序一致。
- 中央 Chat 不是卡片瀑布：用户消息、思考、工具过程、审批与 final 形成一条
  可追踪的 kinetic transcript。通过字号、缩进、留白、材质和状态轨迹建立层级，
  只在 elevation 真有语义时使用面板。
- 右缘阶段 1 只渲染可收起的结构边界或 reveal handle，不渲染空列、假 tabs、
  假 Review/Files 卡片。窄窗口下它完全移除，Chat 回到严格单列。
- `< 768px`：左缘轨道变为 modal sheet，command spine 只保留当前任务与
  必要控制，Chat 单列满宽，composer 固定于 safe-area 上方；不缩放桌面构图硬塞。

### 4b. 交互画布与物理动效

- Shell 背后只放**一层**固定 Canvas 2D，视觉概念为"上下文场"：由真实
  `chat_started`、stream、tool、approval、final/error 状态驱动流线密度、
  收束方向、能量与主题色。它连接产品状态，不播放与任务无关的随机粒子秀。
- Canvas 必须 `aria-hidden="true"`、`pointer-events: none`，且不承载文字、
  按钮、状态名或唯一信息。关闭 Canvas 后，完整任务仍可完成。
- Canvas controller 与 React tree 隔离：使用 `requestAnimationFrame` 的
  timestamp 计算 delta，React 只在离散任务状态改变时传入快照；连续 pointer /
  velocity / render 参数不得进入 `useState`。DOM 物理反馈使用
  `motion/react` 的 motion value、transform 和 opacity。
- 动效语法统一：导航展开、面板 reveal、消息阶段进入和按钮按压使用同一组
  spring token；流式正文保持稳定，不做二次打字机、逐字符 scramble 或位移。
  审批卡不做 tilt、magnetic hover 或会削弱风险感知的装饰动画。
- 生命周期与性能：`ResizeObserver` 同步尺寸，device pixel ratio 上限 1.5，
  页面隐藏或 Canvas 不可见时停止循环，unmount 时取消 frame 和 observer。
  绘制数量按 viewport / frame budget 自适应，不在 React render 内创建粒子。
- `prefers-reduced-motion: reduce` 时 Canvas 只绘制一帧静态构图，所有 spring、
  parallax、pointer physics 和自动位移关闭；主题切换继续即时完成。低性能或
  Canvas 初始化失败时回退为同 token 的静态 CSS 材质，不能白屏或阻塞聊天。
- 禁止自定义 cursor、scroll hijacking、音频自动播放和多层全屏 Canvas。
  阶段 1 不做 WebGL/3D；原生 Canvas 2D 是满足需求的最小渲染层。

### 5. Chat 纵切（`frontend/src/chat/`）

事件 → UI 状态机（与旧前端 `render/chat.js` 语义等价，不逐像素等价）：

| 事件 | UI |
| --- | --- |
| `chat_started` | 定位/创建会话，滚动到底 |
| `model_call_start` / `model_stream_start` | "思考中"指示 |
| `model_stream_chunk` | 按 `kind` 分流：thinking 折叠块 / content 正文 / args 工具参数区；64 字符批量粒度直接渲染，不做前端二次打字机动画 |
| `action_parsed` / `tool_start` | 工具行（名称、参数摘要、状态） |
| `approval_required` | 审批卡：action 详情、批准/拒绝、剩余时间倒计时（前端本地推算，以后端超时结果为准） |
| `approval_granted/denied/timed_out` | 审批卡定格为终局态 |
| `final` | 终态块：结果、changed_files、下一步提示 |
| `error` | 错误块 + "从会话历史重建"入口 |

- 发送路径只用异步对（`POST /api/chat/start` + SSE）；同步 `/api/chat/turn`
  不接入（契约清单 §5）。
- 同 session 并发：发送中禁用输入，后端 400 仍会正确显示（不依赖 UI 禁用）。
- loading / empty / disconnected / retrying / unknown-event / approval-timeout /
  final / error 都有完整视觉状态；图形只用 Lucide，关键状态同时显示明文。
- SSE 高频 chunk 只更新 transcript 内容与 Canvas 的聚合能量值，不为每个 chunk
  新建 DOM 动画。画布表达"系统正在工作"，正文表达"系统具体说了什么"。
- 刷新/重建：进入会话先 `GET /api/chats/<id>` 渲染历史 turns，再挂接活跃
  job（如有）。**语义澄清（审查修订 5）**：`build_chat_payload` 的历史
  `turns[]` 是 RunStore 重建的**过程摘要 + 思考文本 + 终态**（`_turn_process`
  / `_turn_thinking_text`），**不是**逐 chunk 的原始流式序列。因此重建视图
  展示"已完成 turn 的摘要形态"，只有**当前活跃 job** 才有逐 chunk 流式效果。
  UI 要区分这两种形态，不承诺对历史 turn 做流式回放。

### 6. 测试与门禁

- 单元：Adapter（SSE 去重/重放/TTL 回退/终态）、主题初始化与持久化、
  chat 状态机各事件转移。Vitest。
- 契约 fixture：从契约清单 §4 的事件目录构造录制序列（含乱序重放、未知
  事件、审批超时），断言状态机终态；fixture 与后端事件名的一致性由一条
  Python 侧测试守护（比对 `sse.js` 事件表或常量清单）。
- 浏览器 E2E（Playwright，仅关键流）：FakeLLM 下发起 → 流式 → final；
  审批批准与拒绝两条路径。真实 DeepSeek 路径为手动验收项。
- 可访问性：键盘遍历壳与审批卡、焦点可见、reduced-motion 无动画、
  320px viewport 下轨道可收起且内容不截断。
- 图标/文案静态门禁：用一个无第三方依赖的 Node 检查扫描 `frontend/src/`
  可见字符串，拒绝 `Extended_Pictographic` 与已知图形字符；同时拒绝
  `lucide-react` 之外的图标依赖、源码手写 `<svg>` 和动态 whole-map import。
  Playwright 再对 payload 容器之外的渲染文本与 accessible name 做同类检查，
  防止运行时漏网。
- 视觉回归：Playwright 截图至少覆盖 B 深桌面 `1440×900`、B 浅桌面、
  B 深 `390×844`、B 深 `320×568`，以及 A/C 两主题各自原生模式的桌面；
  每张图必须人工核对无裁切、无横向滚动、无假入口、无传统等宽三栏退化。
- 交互验收录屏：真实浏览器走"新建 → stream → tool → approval → final"和
  deny/error 两条路径，证明排版、Canvas 与 spring 是同一叙事而非静态效果图。
- 性能：Chrome Performance 记录覆盖 30 秒 stream + pointer + panel reveal；
  参考开发机目标为交互段平均不低于 55 FPS、无持续性 long task，Canvas 不可见
  后无活跃 frame。另跑 Lighthouse，目标 LCP < 2.5s、INP < 200ms、CLS < 0.1。
- 前端门禁：`npm run build`、`tsc --noEmit`、eslint、vitest 全绿；
  图标/文案检查、视觉回归与 Playwright 关键流全绿；Python 侧全量 pytest
  不回归。

## 消费者

| 消费者 | 用到的面 |
| --- | --- |
| 用户 | `/preview/` 并行试用新壳与 Chat 纵切 |
| 阶段 2 | 复用 Adapter、主题、Shell 框架横向补页面 |
| 旧前端 | 不受影响，保持默认入口与回退路径 |

## 非目标

- Monaco、多标签编辑器、文件树、diff、runs/review 页面（阶段 2/3）。
- 设置中心与 config 写 UI；`/api/config` POST 不接入。
- 除 §2b 的一处 CSP `style-src` 放宽外，后端任何路由、API、业务或数据变更
  （含 SSE 批量粒度、分页、Last-Event-ID 续传、SPA history fallback）；需要
  时另写后端 spec。
- 桌面壳、安装包、远程访问、Marketplace。
- 切换 `agent start` 默认入口与删除旧前端（等价达成后另行决定）。
- 状态库（Redux/Zustand 等）；React 自身状态不够用时再在阶段 spec 里引入。
- 为参奖而新增营销落地页、奖项提交物或声称已达到外部评委结论；本阶段只交付
  真实产品工作台与内部对标证据。
- Three.js / R3F / WebGL、GSAP、滚动劫持、自定义 cursor、音频叙事与多 Canvas
  合成；原生 Canvas 2D + Motion 已覆盖阶段 1 的明确需求。

## 兼容与迁移

- Python 代码仅 §2b 一处 CSP 头放宽（`style-src` 加 `'unsafe-inline'`），
  无路由/API/业务/数据改动；`src/agent/web/static/preview/` 是新增静态目录。
- 旧前端行为、`/` 入口、全部 API 契约不变；放宽后的 CSP 不影响旧前端
  （它本就不违反 style-src）。
- 新前端可整体删除而不影响现网（回滚 = 删目录）。
- Node.js 仅为开发/构建依赖，最终用户运行产品不需要（上位方向要求）。

## 验收标准

1. `agent start` 后访问 `/preview/`：三主题 × 深浅切换即时生效、持久化、
   刷新不闪错主题；默认 B 深（无系统浅色偏好时）。
2. FakeLLM：新建会话 → 发送 → 流式渲染 → 工具行 → final，全程无控制台错误。
3. 审批：批准后同 turn 续跑至 final；拒绝显示对应终态；倒计时超时后 UI
   与后端 `approval_timed_out` 一致。
4. 刷新页面：历史 turns 重建；活跃 job 重连后事件不重复渲染（sequence 去重
   生效）；TTL 过期 job 走重建路径且有明确提示。
5. 等价清单 C1-C9、H1（精简）、H2、S1、S2、S5 逐项可勾。
6. 旧前端 `/` 全功能不回归（手动 smoke + Python 全量 pytest）；CSP 放宽后
   `script-src 'self'` 仍严格，浏览器控制台无 CSP 违规报错。
7. 前端四门禁（build/typecheck/lint/vitest）+ Playwright 关键流全绿。
8. dev 模式（Vite proxy）与预览模式（`/preview/` 静态）两条路径下，发消息、
   审批等 POST 均不触发 403；hash 深链刷新不 404。
9. 产品自有源码与真实 DOM（排除原始 payload 容器）检查均为：emoji 0、
   Unicode 图形符号代替图标 0、手写 SVG icon 0、非 Lucide icon package 0；
   icon-only 控件 accessible name 缺失 0。
10. 首屏不是固定三栏 dashboard：左缘轨道、kinetic transcript、右缘 reveal
    结构和上下文场形成统一空间；核心 C1-C9/H1/H2/S1/S2/S5 均可在 Canvas
    关闭时完成。
11. 上下文场至少对 stream、tool、approval、final/error 呈现可辨认但不干扰
    阅读的状态差异；DOM 动效使用统一 spring 语法。reduced-motion 下画布静止、
    自动位移为 0，功能与状态信息无损。
12. §6 的 6 组视觉视口、两条交互录屏、性能 trace 与 Lighthouse 都有可复核
    证据；无横向溢出、文字/CTA 裁切、焦点丢失、Canvas 主线程持续占用。
13. 内部设计审查按 §视觉增补决议矩阵达到：Awwwards proxy 总分 ≥ 8.0，
    各项 ≥ 7.5；CSSDA proxy 的 UI/UX/Innovation 各 ≥ 8.0。未达标则仍是草案，
    不得以"功能已通"宣布视觉完成。

## 判定依据

- Lucide React 官方指南：<https://lucide.dev/guide/react>
- Lucide React 可访问性：<https://lucide.dev/guide/react/advanced/accessibility>
- Motion for React 官方文档：<https://motion.dev/docs/react>
- Canvas API：<https://developer.mozilla.org/en-US/docs/Web/API/Canvas_API>
- `requestAnimationFrame`：<https://developer.mozilla.org/en-US/docs/Web/API/Window/requestAnimationFrame>
- Awwwards Evaluation System：<https://www.awwwards.com/about-evaluation/>
- CSS Design Awards About / Awards：<https://www.cssdesignawards.com/about>
- FWA：<https://thefwa.com/>
