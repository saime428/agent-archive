# thinking-orbs 阶段指示器实施计划

- 日期：2026-08-06
- 对应设计：`docs/superpowers/specs/2026-08-06-thinking-orbs-phase-indicators-design.md`

## 任务

1. `frontend/package.json`：`dependencies` 加 `"thinking-orbs": "0.2.0"`（精确，无 `^`），
   `npm install` 后确认 `package-lock.json` 只新增该包一条、无传递依赖。
2. `frontend/src/chat/state.ts`：`ChatState` 记录 `lastAction`（来自 `tool_start` 的
   `action`）与 `lastStreamKind`（来自 `model_stream_chunk` 的 `kind`）。纯 reducer 改动，
   补 `state.test.ts` 用例。
3. `frontend/src/Orb.tsx`：导出纯函数 `resolveChatOrbState(phase, action, streamKind)`
   与组件 `<Orb state>`。组件 `size={20}`、`theme={resolvedMode}`（取自 `useTheme()`）、
   `aria-hidden`；`state` 为 `null` 时返回 `null`。未知 action 落 `working`；
   `content` 与 `args` 同映射到 `composing`。
4. `frontend/src/Orb.test.tsx`：映射函数单测——8 条聊天规则各命中一次、
   `idle`/`final`/`error` 返回 `null`、未知 action 落 `working`、
   `args` 与 `content` 同态（防流式抖动回归）。
5. 接线聊天面 `App.tsx`：`491`（thinking）与 `152`（StatusMark）改用 `<Orb>`，
   并给 `stream` / `tool` / `approval` / `recovering` 四个此前无指示器的态补上；
   `445` 只接 `retrying` 分支。保留全部既有 `role="status"` / `role="alert"` 文案。
6. 接线工作区：`FilesView` 434/467、`GitView` 120/201、`TerminalView` 182、
   `SettingsView` 五处 `加载中`。不动 `CommandPalette:133`（空状态）与
   `App.tsx:345`（日志行）。
7. e2e：`workspaceVisuals` 与其余能拍到 orb 的基线用例补
   `page.emulateMedia({ reducedMotion: "reduce" })`；复跑 14 张基线，逐张确认差异后再更新。
8. 验收：`npm run check` 全绿；三主题 × 深浅实测（含系统深色 + 应用内浅色）；
   reduced-motion 实测静止；`SettingsView` 首屏 5 orb 并发帧开销实测，超标则收敛为区块级
   单 orb 并回报；native tools 一轮对话实测只切一次 `weaving → composing`；
   记录 gzip 包体增量；全量 pytest 复跑。
9. `README.md` 依赖说明 + `CHANGELOG.md` 条目；提交推送，CI 绿。
