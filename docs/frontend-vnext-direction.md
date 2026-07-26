# Frontend vNext 总方向

- 日期：2026-07-25
- 状态：已确定的大方向，持续补充
- 性质：产品体验子方向，不是项目总规划或实现 spec
- 上级方向：[Project vNext 总方向](project-vnext-direction.md)

当前迁移状态：阶段 0–2、Default Entry Readiness、Cutover 与阶段 3H Command/Layout 已完成；根 `/` 已指向 React Workbench，
`/legacy/` 保留旧 Workbench 回滚入口。阶段 3 是核心目标：3I 与最终缺陷清零仍未完成；
阶段 4–5 是需求触发项，不阻塞 Frontend vNext 核心完成。

## 一句话目标

把当前能用但偏静态、偏工具页的 Workbench，完成为一个成熟、克制、可信的个人 coding agent 工作台：用户可以在同一个工作台里完成会话、工具执行、审批、文件编辑、diff、终端、验证和任务复盘。

对标 [LiveAgent](https://github.com/Stack-Cairn/LiveAgent) 的是产品完整度、信息架构和生态闭环，不复制它的品牌，也不照搬 Tauri、Rust、Go 和远程 Gateway 的整体体量。

## 为什么现在改变方向

[v0.7 Product Shell Decision](v0.7-shell-decision.md) 当时选择静态 HTML/CSS/JS 是正确的：先验证完整工作流，再决定是否引入前端工程。

现在它记录的迁移条件已经出现：

- 状态和渲染逻辑已经分散到多个面板；
- 三栏布局、会话标签、持久化布局和多种详情视图已经形成；
- 当前编辑器仍是单文件 textarea，无法继续承载真正的开发工作台；
- 静态资源已经足够大，继续手写 DOM 的维护成本高于组件化收益；
- 后续 MCP、Skills、Memory、Automation 都需要稳定的产品入口和可复用交互模式。

因此，新方向不是推翻已完成的 Workbench，而是以现有功能和安全语义为基线，渐进替换它的前端实现。

## 产品原则

1. **先闭环，再扩页面。** 完整生态不是功能菜单的数量，而是“发现或安装 → 配置 → 运行 → 观察 → 恢复或复用”的闭环。
2. **本地优先。** 工作区文件、执行记录、配置和敏感信息默认留在本机；远程能力以后按明确需求增加。
3. **安全语义由后端负责。** sandbox、approval、redaction、snapshot、durable log 和路径限制不能被前端绕过，也不能只靠按钮禁用来保证。
4. **界面只展示真实能力。** 后端没有实现的功能不做可点击假入口；规划中的能力可以出现在路线图，不伪装成已可用产品。
5. **高密度但不拥挤。** 它是专业开发工具，不是营销落地页；优先清晰层级、可扫描状态和稳定布局。
6. **渐进迁移。** 新旧前端短期并存用于验收，达到功能等价后一次切换并删除旧壳，不长期维护两套产品。

## 固定的技术方向

### 浏览器优先的前端

- 使用 **React + TypeScript + Vite** 构建单页应用。
- 使用 **Tailwind CSS + Radix UI primitives** 建立一致、可访问的视觉基础。
- 在开发工作区阶段引入 **Monaco Editor**，不在脚手架阶段提前背负编辑器复杂度。
- 默认先使用 React 自身的状态能力；只有出现明确的跨 Module 共享状态问题时，才在阶段 spec 中选择额外状态库。
- 构建后的静态资源继续由现有 Python Workbench 服务提供；最终用户运行产品不应依赖 Node.js 开发服务器。

### 保留 Python 核心

- Python agent runtime、工具、安全链、配置、日志和持久化继续作为事实来源。
- 本轮方向不包含把核心改写为 Rust 或 Go。
- Next.js、SSR 和 SEO 不解决本地工作台的核心问题，因此不进入默认方案。
- Electron、Tauri、安装包和自动更新继续作为浏览器版本稳定后的分发阶段，而不是前端重做的前置条件。

### 前后端 seam

现有 Workbench 的 HTTP JSON 与 SSE 事件协议是前后端的外部 **seam**。Python 实现保留业务真值，React 前端通过一个数据访问 **Adapter** 消费这套 **Interface**，页面不各自散落 `fetch`、事件游标和错误转换逻辑。

这套 Interface 不只包括 URL 和字段，还包括：

- SSE 事件顺序、完成条件、断线恢复和 unknown-job 行为；
- approval 的等待、批准、拒绝和超时语义；
- 文件路径、保存、diff 和 snapshot restore 的安全约束；
- config、session、run 与 review payload 的错误模式。

旧静态前端和新 React 前端在迁移期形成两个真实 Adapter，因此这个 seam 值得先做契约清单和契约测试。前端重做不顺带重写后端；如果 Interface 本身需要调整，单独写后端 spec，并保持迁移期兼容。

## 目标产品壳

### 顶部状态栏

集中显示当前工作区、Git 分支、Provider/Model、运行状态与全局入口。它回答“我现在在哪里、在用什么、系统是否正常”，不堆放低频设置。

### 左侧导航

承载新任务、会话历史、搜索、工作区切换和后续的固定任务。层级稳定，支持折叠和键盘导航。

### 中央工作区

承载最主要的任务流：聊天、流式思考与正文、工具过程、审批，以及后续的多标签编辑器。聊天和代码不是两个割裂产品，而是同一任务的两种主视图。

### 右侧工作台

按上下文组织 Files、Git/Diff、Terminal、Run/Review、Problems 和 Approvals。右侧不是信息垃圾桶；默认只突出当前任务最相关的面板，其余按标签或命令打开。

### 设置与生态中心

低频但系统性的能力进入独立区域：Providers、MCP Servers、Skills、Memory、Automation、Security、Diagnostics。只有对应后端生命周期真实可用时，才开放管理入口。

## 视觉与交互语言

- 桌面开发工具优先，同时保证窄窗口下侧栏可收起、内容不被截断。
- 深色与浅色主题从第一阶段共用同一套语义 token，不分别打补丁。
- 使用克制的中性色、一个主强调色和少量状态色；不复制 LiveAgent 的品牌色。
- 统一圆角、边框、阴影、间距和字体层级，避免每个面板成为不同风格的卡片。
- 动效只解释状态变化、面板切换和流式进度；支持 reduced motion，不用装饰性连续动画。
- 所有核心操作支持键盘、可见焦点、合理对比度和屏幕阅读器名称。
- 工具调用、风险、审批、失败和恢复必须比装饰更醒目，不能为了“干净”而隐藏重要状态。

具体视觉方向、颜色、图标和密度会在第一阶段开工前用少量视觉方案确认，本文件不提前锁定像素级设计。

## 分阶段路线

| 阶段 | 目标 | 主要交付 | 明确不做 |
| --- | --- | --- | --- |
| 0. 设计与契约基线 | 决定长相和迁移接口 | 视觉方向选稿、核心任务流、HTTP/SSE 契约清单、功能等价清单 | 直接替换现网 Workbench |
| 1. App Shell + Chat 纵切 | 证明新架构能跑真实任务 | React 工程、主题与布局、会话列表、真实流式聊天、工具过程、审批、临时预览入口 | Monaco、完整设置中心、桌面壳 |
| 2. 核心功能等价 | 让新前端覆盖当前产品 | sessions、files、settings、runs/review、diff、snapshot、diagnostics、错误与恢复状态 | 新生态能力、远程访问 |
| 3. 开发工作区 | 从聊天页升级为 coding workbench | Monaco 多标签、工作区搜索、Git/diff、真实 terminal、命令面板、布局持久化 | Marketplace、Gateway |
| 4. 生态中心（需求触发） | 在统一管理需求出现后提供产品入口 | Providers、MCP、Skills、Memory、Automation 的发现、配置、状态、诊断与生命周期 UI | 没有后端支持的假管理功能 |
| 5. 分发与远程（需求触发） | 在非开发者安装或跨设备使用需求出现后改善安装和访问 | 安装包、自动更新、签名发布；再评估 desktop shell 与 remote gateway | 为追求技术栈完整而重写核心 |

阶段编号表达依赖顺序，不是一次性版本承诺。阶段 0–3 是核心范围；阶段 4–5 只有触发条件
成立才开工。每个阶段开工前都要独立写 spec，锁定范围、文件、Interface、验证和非目标；
实际发现的新需求优先加入对应阶段，而不是随手扩进当前切片。

## 迁移策略

1. 保留当前静态 Workbench 作为可工作的基线。
2. 新前端通过临时预览入口并行运行，复用同一套 Python HTTP/SSE Interface。
3. 先完成“发起真实任务 → 流式输出 → 工具过程 → approval → final”的纵向切片，再横向补页面。
4. 用功能等价清单逐项验证 sessions、files、settings、runs、review、snapshot 和异常路径。
5. 新前端通过自动门禁和真实 Workbench 验收后，切换 `agent start` 默认入口。
6. 切换稳定后删除旧静态实现和兼容代码，避免长期双维护。

## 验收护栏

- 现有 sandbox、approval、redaction、snapshot、durable log 和 workspace path 语义不回归。
- 真实 Provider 路径验证连续 SSE、thinking/content/args、approval 后同一 turn 续跑、final 和错误恢复。
- 覆盖断线、刷新、unknown job、approval timeout、保存失败和后端不可用等失败路径。
- 前端至少具备 build、lint、类型检查、关键 Module 测试和核心任务流浏览器测试。
- 关键交互具备键盘、焦点、对比度、reduced-motion 和窄窗口验收。
- 阶段 2 完成前，旧前端仍是回退路径；达到等价前不宣布迁移完成。

## 当前核心完成标准

前端 vNext 真正完成，不是“React 页面已经能打开”，而是：

- 用户能在一个工作台内完成真实 coding agent 主循环；
- 每个高风险动作都可理解、可审批、可追踪、可恢复；
- 文件、diff、终端、验证和复盘与会话上下文连在一起；
- 新功能可以通过稳定 Interface 接入，而不需要在多个页面复制状态逻辑；
- 对话、生成、前端、后端/API、CLI、打包和真实浏览器路径均通过最终回归；
- 旧静态壳已经删除，构建与测试路径只有一套。

生态中心只有在现有 CLI 生命周期已不足以支撑日常管理时才触发阶段 4；安装包、自动更新、
desktop shell 或 remote gateway 只有在出现非开发者安装、多机迁移或跨设备使用时才触发阶段 5。
这两阶段未触发时不做占位页面、不加依赖，也不阻塞核心完成。

## 本轮非目标

- 不进行像素级 LiveAgent 复刻或沿用其品牌。
- 不在本轮创建 React 工程或修改运行时代码。
- 不重写 Python agent runtime、工具或安全链。
- 不同时引入 Tauri/Electron、Rust、Go、Gateway、Marketplace 和云协作。
- 不提前决定所有页面、组件、路由、状态库、包管理器和测试工具。
- 不做一次性 big-bang 替换。

## 后续如何补充

本文件只维护长期方向、依赖顺序和重大约束。后续实际开工时：

- 阶段内的新细节进入对应 spec 和实现计划；
- 不改变整体方向的小功能进入 backlog；
- 如果要改变前后端 seam、安全责任、运行形态或阶段依赖，再更新本文件并记录原因；
- 每个阶段结束后补实际结果和下一阶段触发条件，不把未完成能力写成已完成。

阶段 0–2、默认入口 Cutover、3E Editor/Search、3F Git/Diff、3G Terminal 与 3H Command/Layout 已完成，不再重复补脚手架、功能等价、编辑器、Git 只读视图、Terminal 或命令布局。
继续保留 `/legacy/` 完成稳定观察，并为 3I Legacy retirement 锁定 Interface、文件范围、失败语义、验证和非目标。阶段 4–5 继续留在需求池，直到
对应触发条件成立。

## 参考

- [LiveAgent 中文 README](https://github.com/Stack-Cairn/LiveAgent/blob/main/README.zh-CN.md)
- [LiveAgent Architecture Overview](https://github.com/Stack-Cairn/LiveAgent/blob/main/docs/architecture/overview.md)
- [v0.7 Product Shell Decision](v0.7-shell-decision.md)
- [v1.0 Packaging Decision](v1.0-packaging-decision.md)
