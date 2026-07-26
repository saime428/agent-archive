# Project vNext Phase 3 方向分析与审查

- 日期：2026-07-25
- 状态：3A Lifecycle 至 3H Command/Layout 已完成；下一切片为 3I Legacy retirement
- 上位方向：[Project vNext 总方向](project-vnext-direction.md)
- 前端子方向：[Frontend vNext 总方向](frontend-vnext-direction.md)

## 结论

Phase 3 是当前最后一个核心建设阶段。按“个人生产工具 + 完整作品”定位，只补真实日常闭环；
Phase 4–5 的分发、远程、社区和统一生态 UI 不进入本阶段，也不预留空壳。

Phase 3 不做一次性大改，固定按以下依赖推进：

1. 可恢复任务生命周期；
2. Memory 修订与删除闭环；
3. 可审计 Automation；
4. 小而稳定的 eval；
5. 编辑器与工作区搜索；
6. Git 工作区与 diff；
7. Terminal 与进程管理；
8. 命令面板与布局持久化；
9. 旧静态壳退役；
10. 最终全链路缺陷清零。

每一项依次经过 spec 审查、implementation plan 审查、实现、五轴审查和真实路径验收；后端
Interface 不存在时先完成后端切片，前端不先造假入口。

当前进度：3A Lifecycle 至 3H Command/Layout 已完成并通过独立验收；3I 与最终全链路缺陷清零仍未完成。

## 当前事实与真实缺口

| 领域 | 当前已有 | Phase 3 仍缺 |
| --- | --- | --- |
| Chat job | Web job 有递增 sequence、SSE poll、approval 5 分钟超时和同 session 并发拒绝 | 用户取消、整轮超时、durable job/event、服务重启后的终态、中断后安全续接、workspace 占用语义 |
| Run loop | 单一权威 loop、Tool 事件、最终 run 日志、Tool 自身超时 | 统一 stop 原因、取消检查、取消/超时终态与摘要；不能靠 UI 丢弃事件冒充取消 |
| Conversation | CLI `--resume` 与 Web session history 可续聊 | interrupted/cancelled/timed-out turn 必须写入历史；续接不得自动重放可能已有副作用的 Tool |
| Memory | candidate accept/reject、并发单终态、可审计 revise/delete 链、current-leaf list/retrieve、source run | 无；3B 已完成，后续切片不扩张 Memory 写界面 |
| Automation | 显式前台 worker、固定间隔定义/启停、幂等 slot claim、同 runtime 执行、取消/恢复与异常通知 | 无；3C 已完成，系统服务、cron、retry 与高风险自动审批仍明确不做 |
| Eval | 4 个内置 FakeLLM case、真实 run loop、完成/错误/Tool/耗时指标、原子本地 report 与稳定 CLI 退出码 | 无；3D 已完成，真实 Provider 只保留为最终可选 smoke，不作为硬门禁 |
| Files | React 文件树、Monaco 多标签、移动 textarea、独立 dirty buffer、递归搜索/行跳转、snapshot 保存 | 无；3E 已完成，后续切片不扩张文件写 Interface |
| Git | Agent Tool 与 Workbench 都有只读 status/diff；3F 已完成仓库根、sandbox、上限、错误态与 staged/unstaged/untracked 闭环 | 无；后续切片不扩张为 commit、push 或 stage UI |
| Terminal | 3G 已完成显式启用、结构化 argv、cursor 输出、line-mode stdin、stop/timeout/close、进程树清理与刷新恢复 | 无；后续切片不扩张为 PTY、shell、后台或多会话 Terminal |
| Product shell | React 已是根入口，legacy 可回滚；3H 命令面板与布局持久化已完成 | 稳定期证据、旧壳和兼容测试删除 |

## 固定语义

### 任务生命周期

- 一个 workspace 同时只运行一个 chat job。个人工具先选安全、可预测的全局占用；若将来出现
  可证明的并行需求，再升级为隔离 workspace/session 调度。
- cancel 是协作式终止：approval 等待和受控子进程应立即唤醒/停止；模型或外部 MCP 调用的
  最坏延迟由其 transport timeout 约束，终态仍必须唯一且可审计。
- 整轮 timeout 与 cancel 使用不同终态；二者都写 durable event、run summary 和 conversation
  turn，不落成模糊的 500。
- resume 不自动重放旧 message 或 Tool。用户提供新的续接消息，系统复用同一 session，并记录
  `resumed_from_job_id`；这样保留上下文，又不重复写文件、执行命令或调用外部 Tool。
- job/event 使用现有 `.agent` 本地存储和原子替换原语；不为单机文件 store 新建数据库层。

### Memory

- revise 创建新 active entry 并 tombstone 旧 entry，保留 `supersedes` 与 source；不原地篡改历史。
- delete 继续写 tombstone；reject 只改变 candidate 状态。所有写操作走已有 user-store 锁和原子替换。
- 检索只返回当前 active 叶节点；被删除或被修订的旧 entry 不再注入模型上下文。

### Automation 与 eval

- Automation 只执行显式本地定义，复用 `run_once`、配置、MCP lifecycle、sandbox、approval 和
  run logs。默认不允许无人值守 approval-required 动作；失败写本地通知事件并返回非零状态。
- 第一版 worker 是显式启动的本地进程，不安装系统服务、不写 C 盘、不注册计划任务。
- 幂等以 automation id + scheduled time slot 占用；同一 slot 只生成一个 attempt。
- eval 使用仓库内稳定 fixture 与 FakeLLM，不用真实 Provider 波动做硬门禁；真实 Provider 仍进入
  最终人工/可选 smoke。

### 开发工作区

- Monaco 只替换现有 textarea editor，继续调用现有安全保存/snapshot Interface；不建立第二条写链。
- 搜索、Git 和 Terminal 分别使用独立后端 Interface 与独立 spec，不塞进文件 API 的隐式参数。
- Git 首切只读；Terminal 是用户直接控制的本地进程，不伪装成 Agent Tool，也不能绕过
  workspace containment、Host/Origin 校验、显式启用和停止/清理语义。
- 命令面板只聚合已存在动作；布局只持久化非敏感 UI 偏好到浏览器 localStorage。

## 切片完成门

| 切片 | 最小可验收闭环 |
| --- | --- |
| 3A Lifecycle | start → durable events → cancel/timeout → 唯一终态 → 重连读取 → 新消息安全 resume；并发占用可解释 |
| 3B Memory | candidate → accept/reject → revise/delete → retrieve 当前叶节点；来源和历史可追踪 |
| 3C Automation | add/enable → due claim → 同 runtime 执行 → durable attempt/notification → cancel/disable；重复 claim 不重跑 |
| 3D Eval | 固定 cases → 执行 → 指标/失败详情 → 稳定退出码；重复运行结果一致 |
| 3E Editor/Search | 多标签打开/编辑/保存/关闭保护 + 递归搜索并跳转；snapshot 与 sandbox 不回归 |
| 3F Git/Diff | 当前工作树 status → 选文件 → staged/unstaged diff；非 Git 与超限状态清晰 |
| 3G Terminal | start → output cursor → input → stop/timeout → 进程树与临时状态清理；刷新可恢复终态 |
| 3H Command/Layout | 键盘打开命令 → 执行真实动作；刷新后布局恢复，窄屏与 focus 正常 |
| 3I Legacy retirement | 稳定回归通过后删除旧壳、`/legacy/` 与双前端测试；wheel/源码/文档一致 |

## 风险与停止条件

- 如果 cancel 只能隐藏 UI、不能停止 approval 或子进程，停止实施，不声明完成。
- 如果 resume 需要自动重放可能已有副作用的 Tool，停止并改为用户消息续接。
- 如果 Automation 需要绕过 approval、安全链或安装系统服务，停止并缩回显式本地 worker。
- 如果 Terminal 无法可靠停止整个进程树，保持 feature disabled，不接入默认 Workbench。
- 如果 Monaco、Terminal 或搜索需要新依赖，分别在对应 spec 锁版本、bundle/包体影响与替代方案。
- 任一新 API 改变 sandbox、snapshot、Host/Origin、redaction 或现有 payload 时，必须单独兼容设计。

## 方向五轴审查

1. 正确性：现状均由当前生产代码、路由和依赖清单核对；未把会话 `resume` 误写成中断任务恢复。
2. 可读性：每个切片只有一个主闭环，完成声明可由外部 Interface 验证。
3. 架构：复用一个 run loop、现有安全链和文件 store；不新增 speculative repository、消息队列或远程层。
4. 安全：禁止 Tool 自动重放、无人值守 approval bypass、Terminal 假清理和浏览器 secrets 持久化。
5. 性能：个人工具默认单 workspace slot；event 采用 append/cursor，搜索和输出必须有界。

审查结论：通过，无未解决 finding。3A Lifecycle 至 3H Command/Layout 已按各自独立设计和验收记录
完成；下一步仅进入 3I Legacy retirement。
