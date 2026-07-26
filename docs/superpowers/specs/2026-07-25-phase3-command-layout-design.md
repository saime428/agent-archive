# 设计：Phase 3H 命令面板与布局持久化

- 日期：2026-07-25
- 状态：已实施并完成独立验收
- 上位方向：[Phase 3 方向分析与审查](../../project-vnext-phase3-direction-review.md)

## 目标

在现有 React Workbench 增加一个只聚合真实动作的命令面板，并把少量非敏感布局偏好保存在当前浏览器。
用户可以用 `Ctrl+K` / `⌘K` 搜索并执行已有动作，刷新页面后恢复会话轨道展开状态与宽度、上下文画布
开关和最后使用的工作台视图。

本切片不增加后端 Interface、依赖、命令注册框架或服务端用户偏好。完成后只允许声明 3H 完成；
Phase 3 与 Project vNext 核心仍需 3I Legacy retirement 和最终全链路缺陷清零。

## 官方语义与本地事实

- [MDN localStorage](https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage)说明数据按 origin
  跨浏览器会话保存，也可能因浏览器策略抛出 `SecurityError`；读取和写入必须失败可退化。
- [WAI-ARIA Modal Dialog Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/)要求打开时焦点进入
  dialog、Tab 保持在 dialog 内、Escape 关闭并把焦点返回合理的调用入口。项目已安装并使用 Radix Dialog，
  继续复用它的 focus trap 与 focus return。
- 当前主题和显示模式已经使用 `localStorage`；会话轨道的展开、宽度、画布开关和工作台最后视图仍只在
  React 内存中。3H 只补这四项，不持久化会话、文件、命令、搜索词或运行状态。

## 命令面板

- 顶部状态栏提供可见“命令”按钮；全局 `Ctrl+K` / `⌘K` 打开或关闭面板。已有 modal 打开时不叠加
  第二个命令面板，避免破坏其 focus trap 和未保存修改保护。
- 面板使用一个自动聚焦搜索框和原生按钮列表；匹配只做 label、detail、keywords 的大小写无关子串
  过滤，不引入 fuzzy-search dependency。
- `ArrowDown` / `ArrowUp` 移动活动项，`Enter` 执行，`Escape` 关闭；没有匹配项时显示明确空态。
- 面板只注册以下已有动作：
  1. 新建任务；
  2. 打开 Files、Git、Terminal、Runs 或 System 工作台视图；
  3. 刷新状态与会话；
  4. 展开/收起桌面会话轨道；
  5. 显示/隐藏上下文画布。
- 执行动作先关闭面板，再调用现有 handler；打开工作台时把命令按钮作为 focus return 入口。命令面板
  不直接 fetch、不复制路由、保存、Terminal 或审批逻辑。

## 布局状态

单一 key `agent.frontend.layout` 保存 JSON：

```json
{
  "railOpen": true,
  "railWidth": 326,
  "canvasEnabled": true,
  "workspaceView": "system"
}
```

- `railWidth` 读取时限制在现有 260–420 px；非有限数值回退 326。
- `workspaceView` 只接受 `files|git|terminal|runs|system`；其他字段必须是对应布尔类型，否则逐项回退。
- JSON 损坏、key 缺失、`getItem`/`setItem` 抛错均静默退回默认布局，不能阻止 Workbench 启动或操作。
- 每次布局状态变化写回；写失败只影响下次刷新恢复，不显示全局错误，也不回滚当前内存布局。
- 不保存 workspace 路径、session/run/file id、编辑 buffer、Terminal argv/output、搜索词、Provider、密钥、
  approval 或任何后端数据。移动端 session sheet、工作台 open 状态和命令 query 也是瞬态。

## React 接线

- 新增一个小型 `CommandPalette`，命令数据由 `App` 传入；不建立全局 command registry 或 context。
- `App` 用一个 layout state 替代四个分散 state，并沿用现有 rail resize、canvas toggle、workspace open、
  `newSession` 与 `refreshGlobal` handler。
- `WorkspacePanel` 的当前 view 改为受控值，但 dirty Files 的 view/close guard 仍在 panel 内，标签切换不能
  绕过未保存修改确认。命令面板只在其他 modal 关闭时打开，因此从命令进入工作台时没有 dirty bypass。
- 保持 320/390/1440 布局、reduced motion、可见 focus、Lucide-only 图标与现有视觉 token。

## 验收

- layout parser 覆盖默认值、损坏 JSON、字段类型、宽度上下界、未知 view 和 storage exception。
- E2E 覆盖按钮与 `Ctrl+K` / `⌘K` 打开、过滤、上下键、Enter、Escape、空态、focus return 和已有 modal
  不叠加。
- 每个命令至少证明一次真实结果；工作台 view、rail 展开/宽度、canvas 在 reload 后恢复，损坏 storage
  不白屏。
- 320/390/1440 无横向溢出；命令列表可滚动，所有按钮有 accessible name，reduced motion 不回归。
- frontend 全量、Python docs/静态资产契约、`build:preview`、真实 served Workbench、wheel、detached、
  可见浏览器、console 与 Git/temp/process 清理全部通过。

## 非目标

- 命令历史、最近使用排序、快捷键自定义、fuzzy ranking、分组 registry、插件命令、VS Code 式 `>` 语法。
- 服务端偏好、账号同步、多 workspace profile、布局拖拽编排、右侧宽度 resize 或面板 docking。
- 新后端 API、设置写白名单、持久化 dirty buffer、Terminal session、聊天 draft 或 modal open 状态。
- 3I 旧壳退役、阶段 4–5 生态/分发/远程需求触发项。
