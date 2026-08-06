# thinking-orbs 阶段指示器设计

- 日期：2026-08-06
- 状态：用户已批准范围（9 种 orb 状态全部启用，覆盖全部可接待机面），待实施
- 修订：2026-08-06 自审后扩面并修正组件形状，见"自审修正"
- 范围外：按钮内的 busy spinner、64px 尺寸、自绘 orb 状态、后端事件 schema 变更

## 背景

Workbench 现在只有一种"等待"表达：Lucide `LoaderCircle` + CSS 旋转。它在 7 处复用，
既当"模型在思考"，也当"按钮在提交"。用户看不出 agent 是在检索、在写文件、还是在等人批准。

后端其实已经把这些区分好了：`ChatPhase` 有 8 个态，`tool_start` 事件带 `action` 字段，
`model_stream_chunk` 带 `kind`（`thinking` / `content` / `args`）。信息在前端被丢掉了。

## 依赖决策

引入 `thinking-orbs@0.2.0`（MIT，canvas 渲染，npm 解包 47,214 字节）。

- **精确锁版本，无 `^`**，与 `frontend/package.json` 现有全部依赖一致。
- 零运行时依赖；peerDeps `react >= 18`，本项目 19.2.8 满足。
- 取 npm 依赖而非 vendor 源码：仓库已精确锁版本，churn 本就受控；vendor 反而要自行承担
  MIT 声明保留与上游同步。
- 风险记录：上游仓库 2026-07-21 创建，v0.2.0，单人维护。装饰性组件 + 精确锁版本，
  失效时的退路是回退到 `LoaderCircle`，不影响任何功能路径。

## 组件面

两个出口，不是一个：

```ts
// 纯函数，可单测，不碰 DOM
resolveChatOrbState(phase, action, streamKind): OrbState | null

// 薄壳：size=20、theme=resolvedMode、aria-hidden
<Orb state={...} />
```

聊天面 `<Orb state={resolveChatOrbState(...)} />`；工作区各视图没有 `ChatPhase`，
直接 `<Orb state="searching" />`。`state` 为 `null` 时 `<Orb>` 返回 `null`，
调用点不写条件分支。

## 状态映射（9/9 全部使用）

### 聊天面（由 `resolveChatOrbState` 推导）

| Orb 状态 | 触发条件 |
|---|---|
| `solving` | `phase === "thinking"` |
| `weaving` | `phase === "stream"` 且当前 `kind === "thinking"` |
| `composing` | `phase === "stream"` 且当前 `kind ∈ {content, args}` |
| `searching` | `phase === "tool"` 且 `action ∈ {search_files, web_search, list_dir, read_file, read_pdf, read_docx, read_xlsx, read_pptx}` |
| `shaping` | `phase === "tool"` 且 `action ∈ {write_file, apply_patch, write_markdown_report}` |
| `working` | `phase === "tool"` 其余（`run_command`、`git_status`、`git_diff`、`done`、MCP 动态工具） |
| `listening` | `phase === "approval"` |
| `breathing` | `phase === "recovering"` |

`idle` / `final` / `error` 返回 `null`，**不显示 orb**。它们各有终态 UI（空舞台、最终答案、
错误 alert），加待机动画会谎报"还在跑"。

动作名取自 `src/agent/core/actions.py` 的 `ARGS_MODELS`；映射以白名单实现，
未列出的动作（含全部 MCP 工具）落 `working`，上游新增动作不会崩。

### 其余待机面（直接指定 state）

| 位置 | Orb 状态 | 说明 |
|---|---|---|
| `App.tsx:152` StatusMark | `connecting` | health 探测未回 |
| `App.tsx:445` SSE 重连 | `connecting` | **仅 `streamStatus === "retrying"` 分支** |
| `FilesView.tsx:434` 正在打开 | `searching` | |
| `FilesView.tsx:467` 编辑器加载中 | `working` | Monaco 懒加载 Suspense fallback |
| `GitView.tsx:120` Git 状态 | `searching` | |
| `GitView.tsx:201` diff | `searching` | |
| `TerminalView.tsx:182` 读取 Terminal | `connecting` | |
| `SettingsView.tsx` ×5 加载中 | `searching` | readiness / risk / memory / config / tool 目录 |

## 自审修正

初版 spec 有四处问题，本版已改：

1. **组件形状错了。** 初版只给 `<PhaseOrb phase action streamKind>`，工作区视图根本没有
   `ChatPhase`，接不上。改为纯函数 + 薄壳两个出口。
2. **流式态会抖。** 上游 `useEffect` 依赖含 `state`，状态一变就拆掉重建 rAF 循环。
   native tools 模式下 `args` 与 `content` 分片交替到达，若分别映射会逐片重建动画。
   故 `content` 与 `args` **合并映射到 `composing`**，一轮内只发生一次
   `weaving → composing` 切换。
3. **有三处 `role="status"` 不该接。** 盲扫会误伤：
   - `CommandPalette.tsx:133`「没有匹配的命令」是**空状态**，不是等待；
   - `App.tsx:345`「正在执行 ${action}」是**过程日志的行文本**，会累积多行，
     逐行加 orb 等于渲染 N 个画布；阶段级 orb 已覆盖该语义；
   - `App.tsx:445` 第二分支「实时连接不可用，正在读取持久化历史」是**已降级的终态**，
     不是 pending，且与既有 `WifiOff` 图标语义冲突。
4. **并发画布未评估。** 每个 `<Orb>` 自带独立 rAF 循环；`SettingsView` 五个区块首屏可同时
   pending，即 5 个循环并行。本版按每区块一个接上，但把帧开销列为**验收项**：
   实测超标则收敛为区块级单个 orb。不预先优化，也不盲发。

## 主题

**不能用 `theme="auto"`。** 上游的自动检测找 `data-theme="dark|light"`，而本项目
`theme.tsx:29-30` 里 `data-theme` 存的是主题名（三选一）、深浅在 `data-mode`。
自动检测匹配不到会退到 `matchMedia('(prefers-color-scheme: dark)')`，跟随系统而非应用内选择；
系统深色 + 应用内浅色时会浅墨画在浅底上，等于隐形。

`<Orb>` 从 `useTheme()` 取 `resolvedMode`，显式传 `theme={resolvedMode}`。

## 可访问性

canvas 纯装饰：`aria-hidden="true"`。语义仍由既有文案承载，现有 `role="status"` /
`role="alert"` 文本一律保留，不得被 orb 替换，也不新增 live region——这是替换图标，
不是替换文字，屏幕阅读器的播报内容应与改动前完全一致。

reduced-motion 由上游组件自带（命中时只画一帧静态确定性画面），无需本项目额外处理，
但需在验收中实测确认，不能只信 README。

## 视觉基线的确定性

`e2e/workbench.spec.ts:1533` 等截图断言只用了 `animations: "disabled"`。该选项冻结的是
CSS 动画与 Web Animations，**不会停掉 canvas 的 `requestAnimationFrame`**。任何可能拍到
orb 的基线都会逐帧漂移。

规则：能出现 orb 的视觉基线用例必须先 `page.emulateMedia({ reducedMotion: "reduce" })`，
借上游的静态帧路径取得确定性。本次扩面后 `workspaceVisuals` 系列（files / system 状态）
明确落在风险内，必须处理；`visualVariants` 拍的是 `#/new`（`phase === "idle"`），
预期不受影响但需实测复核而非假定。

## 复用（Ponytail 阶梯）

- 不新建动画层：orb 自带 rAF 循环与 `visibilitychange` 暂停。
- 不新建主题层：复用既有 `useTheme()`。
- 不改后端：`phase`、`action`、`kind` 三个字段都已在现有 SSE schema 里，零 schema 变更。
- 不动 `check:ui` 门禁：orb 是 canvas 不是手写 SVG，包名不匹配第二图标源正则，无 emoji。

## 明确不改

- **按钮内的 spinner 保持 `LoaderCircle`**：`App.tsx:408`（批准并继续）、`553`（停止中）、
  `614`（删除/重命名）。那是"按钮在提交"，不是"agent 在活动"，塞 orb 属于语义误用。
- `App.tsx:1031`（正在读取会话历史）同理，属列表数据加载而非 agent 活动。
- 上节"自审修正 3"列出的三处空状态 / 日志行 / 降级终态。

## 验收

- 9 个状态逐个可复现触发，截图留证；`idle`/`final`/`error` 确认不渲染 orb。
- 三主题 × 深浅模式下 orb 墨色与背景对比可见，特别是"系统深色 + 应用内浅色"这一组。
- `prefers-reduced-motion: reduce` 下实测为静止单帧。
- **并发帧开销**：`SettingsView` 首屏 5 个 orb 同时运行时测帧率与 CPU；超标则收敛为
  区块级单个 orb 并在 plan 回报。
- 流式态实测不抖：一轮 native tools 对话中只发生一次 `weaving → composing` 切换。
- 现有 14 张视觉基线复跑；变化的基线需逐张人工确认是预期变化再更新。
- `npm run check`（typecheck / lint / check:ui / vitest / build / e2e）全绿。
- 记录 gzip 后的实际包体增量；超出预期需在 plan 里回报而非默默接受。
- 全量 pytest 不回归（前端改动不应触及，需实证而非假定）。
