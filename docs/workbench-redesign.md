# Workbench 整体升级

## 设计依据

目标是降低导航与装饰的视觉重量，让对话、审批和结果核对更容易衔接。保留 Geist、Lucide、现有主题与布局偏好，不增加依赖，不改变 API、SSE 或持久化结构。

实施前查看了以下公开图片与源码；借鉴交互层级，没有复制其代码或将图片放入产品：

| 来源 | 实际查看内容 | 本项目采用的设计 |
| --- | --- | --- |
| [Codex 官方介绍](https://openai.com/index/introducing-the-codex-app/)与[官方课程 PDF](https://d2xo500swnpgl1.cloudfront.net/uploads/oaiacademy/Codex-101-Introduction-Demo-32ffbb3c-85da-4da9-973d-5b39ea7d39fd-1773866180169.pdf) | PDF 第 8 页的实际输入区截图；任务、对话与审阅的产品组织方式。没有声称核验当前桌面应用的所有界面 | 安静的导航、集中阅读区、底部输入框，工具与聊天并排 |
| [OpenCode](https://github.com/anomalyco/opencode) | README 的[终端截图](https://raw.githubusercontent.com/anomalyco/opencode/dev/packages/web/src/assets/lander/screenshot.png)，以及提交 `9f8db119fcbd4999379129ac7734375ac23460fb` 的 `packages/app/src/pages/session.tsx` | 面板边界、紧凑控件及会话工作区组织；终端截图不作为桌面截图证据 |
| [Cline](https://github.com/cline/cline) | 历史 v3.50.0 README 的[模型选择截图](https://github.com/user-attachments/assets/3cf21e04-7ce9-4d22-a7b9-ba2c595e88a4)，提交 `2dd8f11ada77947b3a8fb04303ca05b4527f391b` 的 `apps/vscode/webview-ui/src/components/chat/ChatRow.tsx` | 从组件研究工具活动的展开与操作呈现；审批紧邻操作，历史活动默认折叠 |
| [Dyad](https://github.com/dyad-sh/dyad) | README 的[实际界面截图](https://github.com/user-attachments/assets/f6c83dfc-6ffd-4d32-93dd-4b9c46d17790)，提交 `698a76c67c8babc7a441c50318c02c38e2973b89` 的 `src/components/ChatPanel.tsx` | 对话与工作成果分区，输入区稳定，减少动态效果偏好贯穿面板切换 |

## 实现

- 使用现有背景、面板和控件表面形成三级层次，统一圆角、边框、间距及焦点反馈；强调色用于选中项、主要操作和阶段入口。
- 1280px 起右侧工作台为非模态面板，宽度 `clamp(380px, 36vw, 560px)`；更窄时使用模态抽屉。左侧折叠和宽度调节保持原行为。
- 同一个原生 `dialog` 在 `show()` 与 `showModal()` 之间切换，保持 React 子树和轮询生命周期。嵌套确认使用原生模态对话框，避免被抽屉的浏览器顶层遮挡。关闭恢复焦点；编辑器已处理的 Escape 不关闭外层。
- Orb、中文阶段和最近真实活动合成可展开入口，细节仍来自现有 SSE。历史工具记录按需展开，回答与观察摘要分开，运行状态使用真实字段。
- 文件、Git、运行记录、终端及设置复用原组件；右侧窄面板改为上下组织。未保存确认、审批、停止及恢复流程保留。
- 动态背景仅在空闲页低对比显示；工作内容不叠加动画背景。面板过渡遵循减少动态效果偏好。

## 验证

验证使用仓库现有 Playwright API/SSE fixtures，不代表已部署或真实模型调用验证。截图和参考材料保存在 `D:\CodexScratch\workbench-redesign`；纳入 Git 的 PNG 是测试所需视觉基线。

新增验证覆盖桌面聊天与工具同时操作、跨断点聊天和文件草稿保留、编辑器节点保留，以及嵌套确认跨断点后的模态与焦点。现有用例覆盖聊天、审批、恢复、文件读写、Git、终端、设置、错误与禁用状态。

审看 A/B/C 三个主题的深浅模式、320/390px 空闲页、桌面工具面板、窄屏运行失败与终端状态、命令面板和执行审批截图后更新基线。布局检查包含 320、390、1280、1440px。

运行方式（在 `frontend/`，临时目录与 npm cache 指向上述 D 盘目录）：

```powershell
npm run typecheck
npm run lint
npm run check:ui
npm run test:run
npm run build
npm run test:e2e
```

2026-09-10 最终结果：类型检查、lint、UI 规范检查、38 条单元测试、生产构建通过；完整 Playwright 回归 69 条通过，1 条可选的 30 秒性能采样按默认配置跳过。19 张整体界面基线更新后在完整回归中通过，Orb 原有逐状态验证通过。构建仍提示已有编辑器大分包超过 500 kB，没有新增依赖或为此扩大改动范围。

自审重点为非模态桌面焦点、窄屏焦点约束与返回、嵌套弹窗顺序、Escape 消费、草稿持久性和真实结果展示；未发现阻断提交的问题。Orb 功能独立提交为 `a90b18a`，本次整体改版另作提交。
