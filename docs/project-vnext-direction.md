# Project vNext 总方向

- 日期：2026-07-25
- 状态：项目级北极星，持续补充
- 性质：总方向文档，不是版本承诺或实现 spec

## 一句话目标

把当前可靠的本地 coding agent，完成为一个**安全、本地优先、开放扩展、可验证的个人生产工具与完整作品**。CLI、Workbench、Providers、Tools、MCP、Skills、Memory 和 Automation 围绕同一套 Agent 核心与安全语义生长；分发、远程和社区能力只在真实需求触发后扩展。

对标 [LiveAgent](https://github.com/Stack-Cairn/LiveAgent) 学的是能力闭环和依赖顺序，不是照搬 React + Tauri + Rust + Go 的仓库体量。

## 规划口径

- 现有 v0.x 至 v3.1 工作构成“可用的本地基线”；阶段 0–3 是当前核心目标。
- 阶段 4–5 是需求触发项，不阻塞 Project vNext 核心完成，也不为未出现的需求提前搭壳。
- 本文件决定长期方向、Module 职责、seam 和阶段依赖；每个阶段开工前仍要单独写 spec。
- 版本号、工期、具体文件和第三方库在阶段 spec 中决定，不在总方向里虚构精度。
- 已完成能力继续复用；没有触发条件的远期能力只记录，不提前搭壳。
- [Frontend vNext 总方向](frontend-vnext-direction.md) 是本文件的产品体验子方向，不再代表整个项目路线。

## 当前基线

| 领域 | 已有能力 | 下一层缺口 |
| --- | --- | --- |
| Agent runtime | 结构化 action、多轮 loop、native/JSON tool calling、流式事件、错误反馈与预算控制 | 取消、恢复、长任务与并发语义仍需逐步收口 |
| Providers | Fake、DeepSeek、OpenAI-compatible、显式能力声明与带 auth/smoke 元数据的注册表 | 模型级能力目录、模型选择、更多协议 Adapter 与 Workbench 能力暴露 |
| Tools 与安全 | Filesystem、Shell、Git、Web、Documents 与 stdio MCP；统一 catalog、schema 校验、sandbox、approval、redaction、snapshot、durable logs | 后续扩展仍必须无例外地接入同一安全链与 trace |
| 扩展底座 | stdio MCP 动态 Tool 与 managed 配置/启停/live doctor、Skills 三来源与用户级 install/update/package/remove、共享用户存储事务层、Memory、Hooks、Tool catalog | 仍缺自动重连、远程来源、registry 与 Workbench 写接口 |
| 产品入口 | CLI、Python stdlib Workbench、HTTP JSON/SSE、会话与运行记录；Frontend vNext Phase 1/2 与 Default Entry Cutover 已完成 | 仍缺真正的编辑/终端工作区、统一生态管理入口和旧壳退役证据 |
| 质量与运维 | pytest、doctor、release doctor、真实 Provider/Workbench 验收经验 | 稳定 eval 集、跨 Interface 契约门禁、CI 发布与安装包闭环 |
| 分发与远程 | 本地源码/包运行、`agent start` | 签名安装包、自动更新、Gateway、远程身份与社区 registry 均为需求触发项 |

结论：项目已经有核心和安全底座，接下来先完成阶段 3 的个人生产力闭环和最终全链路缺陷清零，不应重新造一个 Agent runtime，也不应让商业化分发或社区能力阻塞核心完成。

## 能力闭环地图

1. **任务闭环**：提出任务 → 模型推理 → 工具执行 → 风险审批 → 验证 → 复盘与恢复。
2. **扩展闭环**：发现或导入 → 校验 → 启用 → 受控运行 → 诊断 → 更新或卸载。
3. **知识闭环**：会话与运行产生候选 → 人工确认或策略筛选 → 检索复用 → 过期、修订与删除。
4. **质量闭环**：变更 → 自动测试/eval → 真实 Provider 与产品路径验收 → 回归证据 → 发布门禁。
5. **分发闭环**：安装 → 初始化 → doctor → 升级 → 配置迁移 → 失败回滚。
6. **远程与社区闭环**：安全配对 → 远程运行/审批 → 断线恢复与审计 → 权限撤销 → 扩展分享。

某个页面或命令只有进入闭环才算产品能力；只有“按钮存在”或“能调用一次”不算完成。
前四个闭环属于阶段 0–3 的核心完成范围；分发、远程与社区闭环分别归入阶段 4–5，
只有触发条件成立后才进入实施范围。

## 目标架构

以下是职责地图，不要求为每一行新建类或目录：

| Module | 职责 | 对外 Interface |
| --- | --- | --- |
| Experience | CLI、Workbench、未来 Remote UI | task/session/run 命令与统一 Run Event |
| Application orchestration | job、session、approval、cancel/resume、事件游标 | 可恢复的任务生命周期 |
| Agent runtime | 上下文、模型循环、工具选择、观察反馈、Skills/Memory 注入 | 一次 turn/run 的输入、事件与结果 |
| Capability | Provider、内置 Tools、MCP Tools、Hooks | 模型能力与 Tool catalog |
| Trust and state | sandbox、approval、secrets、config、run/session/memory store、snapshot、redaction | 受控执行与可恢复持久化 |
| Operations | doctor、eval、发布、安装、升级、未来 Gateway | 健康、兼容性与发布契约 |

### 必须做深的 seam

| seam | 当前事实 | 长期方向 |
| --- | --- | --- |
| Provider Interface | 已有三个 Adapter，是真实 seam | Provider 声明 streaming、native tools、reasoning、auth 等能力；runtime 不写 provider 特判 |
| Tool Interface | 内置 Tool 与 stdio MCP Tool 已共用 catalog、参数校验、policy、approval、redaction、observation 与 trace | 后续 transport 与 Tool 来源继续复用该 Interface，不建立第二条执行链 |
| Run Event Interface | CLI 与 Workbench 已经是两个消费者 | 固定事件顺序、错误、游标、重连、取消和终态，未来 Remote 复用 |
| Extension Lifecycle Interface | MCP 与 Skills 已有本地 validate/enable/disable/diagnose/remove 闭环，Skills 另有 install/update/package，二者共用同一套锁、原子发布与事务恢复原语 | 远程来源、registry、签名与 Workbench 写接口仍未开始 |
| Experience HTTP/SSE seam | Workbench 正在使用 | React 前端通过单一数据 Adapter 接入，详见前端子方向 |

当前只有文件型 store，不为了“以后也许换数据库”先建通用 repository 层；等本地与远程/同步出现两个真实 Adapter 时再建立持久化 seam。

## 九条长期方向

### 1. Agent 核心：可靠性先于更高自治

- 保持一个权威 run loop，先补取消、超时、恢复、并发占用和长任务生命周期。
- 上下文压缩、工具反馈和失败恢复继续集中在 runtime，不散落到 CLI 或 UI。
- Sub-agent、并行任务和 worktree 编排等到单任务的隔离、取消、审计与合并语义稳定后再做。

### 2. 模型与协议：能力协商，不堆 Provider 分支

- Provider Adapter 明确声明 streaming、native tools、reasoning、上下文和鉴权能力。
- OpenAI-compatible 覆盖通用兼容端点；只有协议或能力确实不同才新增专用 Adapter。
- 逐步补连接复用、重试/退避、错误分类、模型诊断和按任务选择模型，不把路由逻辑塞进界面。

### 3. Tools 与安全：只有一条执行链

- 内置 Tool 与 stdio MCP Tool 已经过同一 catalog、policy、approval、trace 与 redaction；未来 transport、自动化任务和远程请求也必须复用这条链。
- Tool 结果统一为可观察、可截断、可恢复的 observation；危险能力默认拒绝或要求明确批准。
- 真实终端、常驻进程和隧道在产品流程需要时再加，并先定义停止、超时和清理语义。

### 4. MCP、Skills 与 Hooks：先本地生命周期，再做商店

- 第一切片 **stdio MCP + 动态 Tool 注册 + 现有安全链** 已完成并通过 CLI、Chat、Workbench 真实验收；仍不包含 registry、远程 transport 和 Hub UI。
- 随后补 MCP 配置、启停、健康、重连与诊断，并让 Skills 具备 install、validate、enable、disable、update、package、remove。
- Hooks 只暴露稳定的生命周期事件和受控输入；不要演变成绕过 policy 的第二套工具系统。
- Marketplace/社区 Hub 必须等本地导入、校验、版本、来源、更新和卸载都可靠后再做。

### 5. Context、Memory 与 Automation：可控的长期智能

- 先改善检索相关性、候选确认、来源、修订、删除与备份，再考虑更复杂的向量或数据库实现。
- 会话压缩与长期 Memory 分工明确：压缩维持当前任务，Memory 跨任务复用稳定事实。
- Automation 复用同一 run lifecycle、安全链、凭据策略和审计；没有取消、幂等与失败通知前，不开放无人值守高风险写操作。

### 6. 产品体验：CLI 与 Workbench 同等真实

- CLI 保持可脚本化、可诊断、无图形界面依赖，是核心能力的第一验收面。
- Workbench 按 [Frontend vNext 总方向](frontend-vnext-direction.md) 渐进迁移到 React，不顺带重写 Python 核心。
- Settings、MCP/Skills Hub、Memory、Automation 和 Diagnostics 只展示后端真实生命周期，不做空壳导航。

### 7. 质量、可观测性与 Evals：用证据决定是否升级

- 保留单元/集成测试，增加 Provider、Tool、Run Event 和扩展生命周期的契约测试。
- 建立小而稳定的参考任务集，衡量完成率、错误恢复、工具次数、token/耗时和安全拒绝，不追求虚荣分数。
- 每个发布候选都经过真实 Provider、CLI、Workbench streaming/approval、文件/diff/恢复路径验收。
- trace 默认本地、可脱敏、可导出；遥测只能显式 opt-in。

### 8. 分发与运维：先可重复，再做桌面壳

- 先固定版本、配置迁移、备份/回滚、doctor 和可重复构建。
- 有非开发者安装需求后，再增加 CI、签名安装包、校验和升级通道。
- Desktop shell 只包装稳定的浏览器产品，不承担重写 runtime 的职责；自动更新必须可回滚。

### 9. Remote 与社区：最后开放最宽的攻击面

- Gateway 先定义身份、设备配对、权限、远程 approval、事件续传、断线恢复、审计和撤销。
- Gateway 只中继受控能力，不成为绕过本地 policy 或持有工作区秘密的云端 Agent。
- 社区 registry 先解决扩展身份、来源、版本、签名/校验、兼容性和下架，并公开扩展格式、示例和兼容矩阵，再开放发布与评分。

## 分阶段路线

| 阶段 | 主线 | 可并行产品线 | 完成门槛 |
| --- | --- | --- | --- |
| 0. 契约基线 | 记录 Provider、Tool、Run Event、配置与安全不变量 | 前端视觉方向、HTTP/SSE 清单 | 当前行为有契约和真实验收基线 |
| 1. 开放扩展内核 | stdio MCP、动态 Tool 注册、policy/approval/trace 接线（MCP 后端切片已完成） | Frontend vNext App Shell + Chat 纵切（已完成） | MCP Tool 与内置 Tool 同安全、同 trace；新前端能跑真实 turn |
| 2. 可管理生态 | MCP 管理/诊断、Skills 本地生命周期与 Provider 能力声明（均已完成） | 前端功能等价、Readiness 与 Default Entry Cutover（已完成） | 安装到卸载闭环可测；新前端为默认入口且旧入口可回滚 |
| 3. 持久生产力 | Memory 生命周期、Automation、取消/恢复、稳定 eval | Monaco、Git/diff、Terminal、任务复盘 | 长任务可控、知识可修订、自动化可审计 |
| 4. 分发闭环（需求触发） | CI、可重复构建、安装包、签名、升级与回滚 | 生态中心、Onboarding、迁移与发布状态 UI | 出现非开发者安装、多机迁移或持续发布需求后，才要求新机器可安装、诊断、升级和回退 |
| 5. 远程与社区（需求触发） | Gateway、设备身份、远程事件/审批、registry | Remote WebUI 与生态发现 | 出现跨设备远程使用或第三方扩展分发需求后，才要求安全模型、断线恢复、撤销和供应链验证通过 |

安全、兼容性、文档和 eval 是每一阶段的门禁，不是最后单独补的阶段。

## 当前执行顺序（2026-07-25 审查）

1. 阶段 0–2 已完成：契约基线、stdio MCP 动态 Tool、MCP/Skills 本地生命周期、Provider
   能力声明、扩展管理收尾，以及 Frontend vNext App Shell、Chat、核心功能等价和默认入口
   Readiness 均不再列为待实现项。
2. Frontend Default Entry Cutover（已完成）：根 `/` 使用 React，`/preview/` 保持兼容，
   `/legacy/` 保留旧 Workbench 回滚入口；旧壳删除必须等待稳定期证据并另行审查。
3. 阶段 3 主线先收口可恢复任务生命周期：取消、超时、恢复、并发占用和 Run Event
   契约；随后完善 Memory 修订/删除/来源、Automation 幂等/通知和稳定 eval。没有可取消、
   可审计的任务生命周期前，不开放无人值守高风险自动化。
4. Frontend Phase 3 按独立纵切推进：编辑器与搜索、Git/diff、真实 Terminal 与进程管理、
   命令面板和布局持久化。每个纵切只消费已经存在且有契约的后端 Interface；缺少后端
   语义时先写独立后端 spec。
5. 阶段 0–3 全部闭环后运行最终测试矩阵，覆盖对话、生成、前端、后端/API、CLI、
   打包和真实浏览器；修复全部可复现缺陷并整套复跑后，才允许宣告 Project vNext 核心完成。
6. 阶段 4 只有在出现非开发者安装、多机迁移、签名发布、自动升级或统一生态管理的
   真实需求时启动；届时 UI 仍不得先于后端生命周期闭环。
7. 阶段 5 只有在出现跨设备远程使用或第三方扩展发布需求时启动。Gateway 只做认证与
   中继，不直接执行本地 Tool、不持有工作区秘密；registry 必须先解决来源、版本、校验、
   兼容性、撤销和下架。阶段 4–5 未触发时保留为需求池，不阻塞 Project vNext 核心完成。

## 全局护栏

- 不削弱 sandbox、approval、command policy、redaction、snapshot、secrets 和 durable logs。
- 不做 Python → Rust/Go 的大重写；新语言必须由分发或 Gateway 的真实约束触发。
- 不一次性引入 Desktop、Gateway、Marketplace、Automation 和多 Agent。
- 不为一个 Adapter 创建抽象，不为未知规模提前引入数据库、消息队列或微服务。
- 不破坏 CLI、配置文件、run/session 数据和现有 HTTP/SSE 行为；必要变化要有迁移与兼容窗口。
- 不把 roadmap、静态页面或未接线配置写成“已实现”。
- 所有高风险外部输入、扩展安装和远程请求都在信任 seam 校验来源、权限和路径。

## 当前核心完成标准

阶段 0–3 是核心目标。只有以下条件同时满足，才可把 Project vNext 作为个人生产工具与
完整作品标记为完成：

- 阶段 0–2 的契约、扩展内核、可管理本地生命周期、Frontend 功能等价和默认入口均有当前证据；
- 阶段 3 的任务取消/超时/恢复/并发、Memory 修订与删除、Automation 审计、稳定 eval，
  以及编辑器、搜索、Git/diff、Terminal、命令面板和布局持久化均形成可验收闭环；
- 用户能从 CLI 或 Workbench 完成真实 coding 任务，全程有诊断、审批、恢复和复盘路径；
- Provider、内置 Tools、MCP、Skills、Memory 与 Automation 共享核心安全和运行语义；
- 扩展可以安全安装、校验、启停、更新、打包和卸载；
- CLI 与 Workbench 是同一能力的两个 Adapter，不产生两套业务规则；
- 对话、生成、前端、后端/API、CLI、打包和真实浏览器测试全部通过，全部可复现缺陷已修复，
  并在修复后完成整套复跑；
- 旧静态壳退役，当前源码、构建产物、wheel、文档与 Git 提交证据一致。

阶段 4–5 是需求触发项。未出现明确的非开发者分发、跨设备远程或第三方社区需求时，
它们不进入当前完成定义；触发后必须另写 spec 和计划，并重新执行相应安全与发布门禁。

## 本轮非目标

- 本轮先完成阶段 0–3；阶段 4–5 只保留触发条件，不提前实施。
- 不把所有阶段拆成 issue 或承诺发布日期。
- 不立刻建设 Marketplace、Gateway、桌面壳、云服务、向量数据库或多 Agent swarm。
- 不推翻已经通过真实验收的本地 Workbench 和 Python runtime。

## 文档关系与更新方式

- 本文件是未来项目级方向的入口。
- [Frontend vNext 总方向](frontend-vnext-direction.md) 维护产品体验子方向。
- [Agent Roadmap Progress](roadmap-progress.md) 保留已经完成的历史里程碑和实际进度。
- 每个实施阶段另建 spec 和 plan，锁定范围、Interface、文件、验证、迁移与非目标。
- 只有产品定位、核心 seam、阶段依赖或全局护栏变化时才修改本文件；实施细节留在阶段文档。

## 参考

- [LiveAgent 中文 README](https://github.com/Stack-Cairn/LiveAgent/blob/main/README.zh-CN.md)
- [LiveAgent Skills 与 MCP](https://github.com/Stack-Cairn/LiveAgent/blob/main/docs/features/skills-and-mcp.md)
- [LiveAgent Architecture Overview](https://github.com/Stack-Cairn/LiveAgent/blob/main/docs/architecture/overview.md)
- [Frontend vNext 总方向](frontend-vnext-direction.md)
- [stdio MCP + 动态 Tool 注册 + 现有安全链设计 spec](superpowers/specs/2026-07-17-stdio-mcp-dynamic-tools-design.md)
- [stdio MCP + 动态 Tool 注册 implementation plan](superpowers/plans/2026-07-17-stdio-mcp-dynamic-tools.md)
- [可管理的本地 MCP 与 Skills 生命周期](superpowers/specs/2026-07-18-managed-extension-lifecycle-design.md)
- [Provider 能力声明](superpowers/specs/2026-07-22-provider-capability-declaration-design.md)
- [扩展管理面收尾](superpowers/specs/2026-07-23-extension-management-closeout-design.md)
- [v1.0 Packaging Decision](v1.0-packaging-decision.md)
