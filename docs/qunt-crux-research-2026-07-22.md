# Crux（qunt.in）研究：开源状态、可验证机制与借鉴边界

- 调研日期：2026-07-22
- 范围：仅核对 Crux 官方站点、官方站点所指向的 GitHub 发布仓库及公开发行物元数据；**未下载、安装、运行或反编译桌面二进制**。
- 结论先行：截至调研日，**没有发现可核验的 Crux Agent 开源仓库**。公开的 GitHub 地址是安装包发布仓库，不是源代码仓库；它没有 `LICENSE`，也没有 Agent 源码、依赖清单、构建脚本或架构文档。因此不能把 Crux 当作可复用代码库，也不能据此断言其桌面端技术栈。

## 1. 开源状态：公开发行，不等于开源

| 项目 | 可验证事实 | 结论 |
| --- | --- | --- |
| 官方产品页 | [qunt.in](https://qunt.in/) 宣传 Windows/macOS 下载、local-first、Overlay、Remote 以及多项集成；页脚只有社交与邮件入口，未给出源码仓库。 | 官网不是源码入口。 |
| 官方 GitHub 地址 | [X-ace-V/crux-releases](https://github.com/X-ace-V/crux-releases) 的 README 明确称其为“official Crux release repository”，并反链 `qunt.in`。 | 这是可核验的官方发布地址。 |
| 仓库内容与许可 | 根目录仅有 `README.md` 与 `assets/`；仓库未声明许可证（GitHub 显示 `NOASSERTION`），未包含 Agent 源码。 | 公开的是品牌素材与发行入口，不是 OSS。不能在项目中复制、分发或依赖其代码。 |
| 发行物 | [v0.2.0 release](https://github.com/X-ace-V/crux-releases/releases/tag/v0.2.0) 只提供 Windows 安装程序、macOS DMG/ZIP、blockmap 与自动更新 YAML。 | 可验证其有二进制产品；不能由二进制文件名推断 Electron、Tauri、模型供应商或运行时。 |

补充：官网内出现的 GitHub 图标属于“可接入的工具”展示，不是 Crux 源码链接。营销站 HTML 中的 `/_next/static/...` 与 `turbopack-...` 资产只足以说明**官网**使用 Next.js 构建产物，和桌面 Agent 的实现无关。

## 2. 从公开材料能确认的产品/运行机制

下表将官网直接陈述和由演示界面得到的有限推断分开；后者不是源码事实。

| 层次 | 已证实的公开信息 | 工程含义与不确定性 |
| --- | --- | --- |
| 任务执行 | 官网演示把一次任务展开为 `read → bash → todowrite → write → edit`，并展示文件浏览、修改 diff、生成报告和“5 files”摘要。 | 可确认其产品叙事是“工具调用 + 工作区变更 + 结果复盘”，而非纯聊天。不能确认工具协议、沙箱、审批、回滚或持久化实现。 |
| 多交互表面 | [v0.2.0 发布说明](https://github.com/X-ace-V/crux-releases/releases/tag/v0.2.0) 写明 Overlay 与主窗口同步 selected model、image model、Build/Plan 和 connector/bash 选择。 | 这是“多个 UI 只消费同一会话/运行时状态”的强信号。若以后增加浮层或远程入口，它们应是同一 `ChatRuntime` 的客户端，不能各自持有会话、模型或工具状态。 |
| 模型选择 | 同一发布说明称从已连接 provider 读取模型目录，并显示 reasoning、vision、context、tool、PDF、价格等能力，过滤不能 agentic chat 的模型。 | 该产品设计值得借鉴：后端声明能力，前端据能力过滤/解释；不能由此反推其 provider 协议或实现。 |
| 会话账本 | 同一发布说明称 context compaction 后 session cost 仍正确。 | 如果建设成本展示，应以不可变使用事件累计；压缩只改变送入模型的材料，不能重置会话成本。官网未公开账本代码或计费边界。 |
| 本地与上下文 | 官网称聊天、文件和上下文留在本机；发布 README 同时写有 local、cloud、remote 三种使用方式。 | “local-first”是产品声明，不等于端到端离线、加密或不出网。若引入远程通道，真实数据流和访问控制仍需单独审计。 |
| 覆盖层与辅助 | 官网声明 Windows 为 `Ctrl+Shift+Space`、macOS 为 `Cmd+Shift+Space`；演示包含屏幕标注、语音/屏幕辅助。 | 可确认其采用系统级唤起的交互目标；不能确认是否具备无障碍权限、截屏上传策略、OS hook 实现及失败恢复。 |
| 远程入口 | 官网列出 WhatsApp、Telegram、Discord、Mail，并称可远程驱动 Agent。 | 这是高风险能力：需要身份绑定、通道隔离、工具权限降级、审批转发、审计与撤销。官网未公开这些安全机制。 |
| 集成生态 | 官网展示 GitHub、Notion、Google Workspace、Chrome、Browser Use 等品牌。 | 可借鉴“按用户现有工具组织能力”的产品表达；不应把 logo 展示当作已验证的深度集成或授权范围。 |

## 3. 视觉设计拆解

本节基于官网实际首屏和官网内的产品界面演示，不把静态营销图当作可运行 UI 的证据。

### 营销站：情绪入口与证据入口分离

- **首屏结构：**近黑背景、大幅地球、左侧两行粗体标题“Making AI Personal”、一行产品承诺、一个高对比的系统下载 CTA。视觉焦点只有“身份隐喻 + 一项行动”，信息负担低。
- **色彩与层级：**背景接近纯黑，正文灰白，CTA 为暖白圆角胶囊；地球的蓝绿色是唯一大面积彩色物，承担品牌记忆点，而不是给每个组件加色。
- **导航：**logo 左上，Blog/Research/News 低对比，Download 高对比。高频转化与低频内容的视觉权重正确分开。
- **字体与质感：**可公开读取的[站点 CSS](https://qunt.in/_next/static/chunks/2oscvza5hplzo.css) 使用 `Satoshi`、`GeistMono`，另包含 `Instrument Serif` 等展示字体；同一 CSS 提供可见焦点与 `prefers-reduced-motion` 降级。正文、代码/工具痕迹和叙事标题的字形角色有明确分工。
- **动效边界：**官网脚本可见 WebGL Earth 与滚动 reveal；它适合在营销页建立记忆点。高频 coding 工作台只应保留解释状态变化的动效，避免动画占用阅读与交互带宽。

### 产品演示：让 Agent 的副作用可扫读

- **主视图：**会话、工具轨迹、最终解释处于同一阅读流；工具动作被压缩成短标签，而不是展开原始日志。
- **环境视图：**将文件树、当前文档、diff 和“变更了多少文件”放在一个可连续阅读的任务环境中。用户能把结论追溯到文件副作用。
- **覆盖层：**把“在哪个应用、看到什么、下一步做什么”放在轻量浮层中，适合即时协助；它不适合替代长期、多面板的 coding 工作台。
- **边界：**官网演示的“成功任务”非常干净，未展示工具失败、风险审批、冲突 diff、长输出、断线恢复或远程通道失效；这些状态不能在实现时被其视觉简洁性掩盖。

## 4. 对本项目的可借鉴项与不应照搬项

当前方向已经明确：保留 Python 作为安全语义事实来源，在稳定 HTTP JSON/SSE seam 之上渐进建设 React Workbench；目标右侧工作台已覆盖 Files、Git/Diff、Terminal、Run/Review、Problems 与 Approvals（见 [frontend-vnext-direction.md](frontend-vnext-direction.md)）。因此这里不建议复制 Crux 的完整产品形态或技术栈。

| 优先级 | 可借鉴的最小产品切片 | 与现有方向的结合方式 | 不做什么 |
| --- | --- | --- | --- |
| P0 | **任务内“副作用摘要”**：在流式聊天中以紧凑、可点击的 read/command/write/edit/diff 条目呈现工具过程与最终文件数。 | 复用现有 HTTP/SSE 事件与 approval/snapshot 语义；前端仅做一个 Adapter 和状态呈现，不重新实现工具调度。 | 不伪造成功状态；失败、等待审批、拒绝、恢复必须同样显眼。 |
| P0 | **后端能力清单驱动模型选择**：让模型可用性与 reasoning/vision/tool/context/cost 等能力同源。 | Provider registry 输出机器可读的能力声明，Adapter 只渲染和解释；避免前端硬编码模型名或把不支持工具的模型放进 Agent 任务。 | 不在 UI 层猜测模型能力，也不让 context compaction 篡改会话 usage/cost。 |
| P0 | **结果与证据相邻**：完成回答紧邻变更文件、diff、验证命令与退出状态，形成“结论→副作用→验证”的单任务闭环。 | 把已有 Files、Git/Diff、Run/Review 面板按当前任务上下文联动，而非增加一套平行“Crux Environment”。 | 不从演示图复制数据模型或把一次展示变成新的全局状态层。 |
| P1 | **视觉层级原则**：中性色为底、一个强调色、状态色专用于风险；将品牌插画留在落地页，工作台优先高密度可扫描。 | 这与现有“高密度但不拥挤”“风险与审批优先”的原则一致；可在 vNext 视觉选稿中测试。 | 不复制地球、文案、logo 或品牌色；不让大图挤占 coding 工作区。 |
| P2 | **全局唤起/overlay 的需求验证**。 | 先确认用户是否确有跨应用即时协助需求；若进入 spec，分别定义 OS 权限、截屏/语音数据流、快捷键冲突、关闭/降级与审计。 | 当前阶段不实现系统 hook、屏幕捕捉或常驻进程。 |
| P3 | **消息通道远程触发**。 | 仅在本地单机核心链路成熟后单独立项；把每个远程入口视为不可信外部边界，默认最小权限和显式审批。 | 不在 Workbench 改造中顺带接入 WhatsApp/Telegram/Discord/Mail，也不把“local-first”当作安全证明。 |

## 5. 建议的下一步

最值得落地的是 P0 的“真实工具副作用摘要 + 结果证据联动”，它直接服务当前 Workbench 的可观察性，并且不改变 Python 的安全边界。开始前应单独写阶段 spec，锁定 SSE 事件映射、审批/失败状态、现有面板联动和浏览器验收；不要以 Crux 的静态成功截图作为验收标准。

## 来源

1. [Crux 官方产品页](https://qunt.in/)（产品声明、功能演示、首屏与视觉资产）
2. [Crux 官方发布仓库 README](https://github.com/X-ace-V/crux-releases/blob/main/README.md)（官方仓库身份、下载入口、local/cloud/remote 声明）
3. [Crux v0.2.0 官方发布页](https://github.com/X-ace-V/crux-releases/releases/tag/v0.2.0)（公开发行物范围）
4. [Crux Windows/macOS 官方说明](https://qunt.in/news/crux-on-windows-and-mac)（Desktop、Overlay、Live Assist 的产品声明）
5. [Crux Remote 官方说明](https://qunt.in/research/reach-crux-from-anywhere)（远程入口与记忆连续性的产品声明）
6. [本项目 Frontend vNext 总方向](frontend-vnext-direction.md)（现有架构约束、工作台信息架构与迁移边界）
