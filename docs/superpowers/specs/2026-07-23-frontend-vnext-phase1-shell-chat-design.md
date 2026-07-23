# 设计：Frontend vNext 阶段 1 —— App Shell 与 Chat 纵切

- 日期：2026-07-23
- 状态：草案（待审查）
- 上位方向：[Frontend vNext 总方向](../../frontend-vnext-direction.md)
- 阶段 0 基线（本 spec 的事实来源，不重复其内容）：
  - [HTTP/SSE Interface 契约清单](../../frontend-vnext-phase0-interface-inventory.md)
  - [功能等价清单](../../frontend-vnext-phase0-parity-checklist.md)
  - [视觉方向选稿](../../design/frontend-vnext-visual-drafts.html)

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
| C | 浅色·纸感冷静 | 琥珀 `#b45309` | 浅 |

每主题含深浅两套值、同一组语义 token 变量名（已在选稿页验证）。上位方向
文档"一个主强调色"按主题内解释：每主题一个强调色，主题间不同。

## 目标

1. 建立 React + TypeScript + Vite 工程（`frontend/`），构建产物由现有
   Python Workbench 服务器同源提供（契约清单 §1：CSP `script-src 'self'`）。
2. 主题系统：三主题 × 深浅模式，语义 token 单一来源；默认主题 B，模式跟随
   `prefers-color-scheme`，可手动覆盖，选择持久化于 `localStorage`。
3. App Shell：顶部状态栏、左侧会话导航、中央 Chat 工作区；右侧工作台本阶段
   只保留占位框架（内容属阶段 2）。
4. Chat 纵切达到等价清单 C1-C9 + H1（精简）+ H2：会话列表/新建/重命名/删除、
   SSE 流式（thinking/content/args）、工具过程、审批（含超时态）、终态渲染、
   刷新重建、未知事件宽容。
5. 数据访问收敛为一个 Adapter Module：页面不散落 `fetch`、事件游标与错误
   转换（上位方向的前后端 seam 要求）。
6. 旧前端零改动；新前端经**临时预览入口**并行访问。

## 设计

### 1. 工程与交付形态

- 新目录 `frontend/`：Vite + React 19 + TypeScript strict + Tailwind CSS +
  Radix primitives。包管理器 npm（仓库无既有前端约定，取最低摩擦项）。
- 构建输出 `frontend/dist/` → 复制进 `src/agent/web/static/preview/`
  （构建脚本完成，产物**不进 git**；`.gitignore` 增补）。
- 临时预览入口：`http://127.0.0.1:<port>/preview/`。旧前端仍是 `/` 默认；
  Python 端零路由改动（静态文件服务已按路径透传，契约清单 §2）。
- 开发模式：Vite dev server + `server.proxy` 把 `/api` 代理到 Python 端口。
  直连会触发跨源写保护（`Sec-Fetch-Site: cross-site` → 403，契约清单 §1），
  代理使请求同源化——这是硬约束，不是偏好。

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

### 3. 主题系统（`frontend/src/theme/`）

- `tokens.css`：从选稿页迁移六组变量（3 主题 × 2 模式），变量名与选稿页
  一致（`--bg`/`--panel`/`--panel-2`/`--border`/`--text`/`--text-dim`/
  `--text-faint`/`--accent`/`--accent-soft`/`--ok`/`--warn`/`--danger`/
  `--chip-bg`）。Tailwind 通过 CSS 变量引用 token，不产生第二套色值。
- `<html data-theme="a|b|c" data-mode="dark|light">` 驱动；`ThemeProvider`
  管初始化（localStorage → 系统偏好 → 默认 B/深）与切换。
- 主题切换按钮在顶部状态栏（选稿页交互原样产品化）；**不做切换过渡动画**
  （选稿页教训：过渡冻结计算值；且 reduced-motion 优先）。

### 4. App Shell（`frontend/src/shell/`）

- 顶部状态栏：workspace、分支（`/api/health` 有则显示）、provider/model、
  key 状态点、主题/模式切换、设置占位（无假入口——不可用即不渲染按钮）。
- 左侧导航：新任务、会话搜索（本地过滤）、按日分组会话列表、重命名/删除
  （复用后端互斥语义，409 类错误 toast 显示）。可折叠；键盘可达。
- 中央：Chat 视图（见 §5）。
- 右侧：空占位列（阶段 2 填充 Files/Review），可整体收起；不渲染假面板。

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
- 刷新/重建：进入会话先 `GET /api/chats/<id>` 渲染历史 turns，再挂接活跃
  job（如有）。

### 6. 测试与门禁

- 单元：Adapter（SSE 去重/重放/TTL 回退/终态）、主题初始化与持久化、
  chat 状态机各事件转移。Vitest。
- 契约 fixture：从契约清单 §4 的事件目录构造录制序列（含乱序重放、未知
  事件、审批超时），断言状态机终态；fixture 与后端事件名的一致性由一条
  Python 侧测试守护（比对 `sse.js` 事件表或常量清单）。
- 浏览器 E2E（Playwright，仅关键流）：FakeLLM 下发起 → 流式 → final；
  审批批准与拒绝两条路径。真实 DeepSeek 路径为手动验收项。
- 可访问性：键盘遍历壳与审批卡、焦点可见、reduced-motion 无动画、
  320px 宽侧栏可收起不截断。
- 前端门禁：`npm run build`、`tsc --noEmit`、eslint、vitest 全绿；
  Python 侧全量 pytest 不回归（后端零改动，应天然绿）。

## 消费者

| 消费者 | 用到的面 |
| --- | --- |
| 用户 | `/preview/` 并行试用新壳与 Chat 纵切 |
| 阶段 2 | 复用 Adapter、主题、Shell 框架横向补页面 |
| 旧前端 | 不受影响，保持默认入口与回退路径 |

## 非目标

- Monaco、多标签编辑器、文件树、diff、runs/review 页面（阶段 2/3）。
- 设置中心与 config 写 UI；`/api/config` POST 不接入。
- 后端任何 Interface 变更（含 SSE 批量粒度、分页、Last-Event-ID 续传）；
  需要时另写后端 spec。
- 桌面壳、安装包、远程访问、Marketplace。
- 切换 `agent start` 默认入口与删除旧前端（等价达成后另行决定）。
- 状态库（Redux/Zustand 等）；React 自身状态不够用时再在阶段 spec 里引入。

## 兼容与迁移

- Python 代码零改动；`src/agent/web/static/preview/` 只是新增静态目录。
- 旧前端行为、`/` 入口、全部 API 契约不变。
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
6. 旧前端 `/` 全功能不回归（手动 smoke + Python 全量 pytest）。
7. 前端四门禁（build/typecheck/lint/vitest）+ Playwright 关键流全绿。
