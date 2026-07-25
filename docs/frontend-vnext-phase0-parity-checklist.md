# Frontend vNext 阶段 0：功能等价清单

- 日期：2026-07-23
- 状态：基线快照（对应旧静态 Workbench `d1ab2dc`，v2.0 Tokenicode 形态）
- 用途：新 React 前端的等价验收基线。方向文档规定：达到功能等价前不宣布
  迁移完成，旧前端保持回退路径；等价后一次切换并删除旧壳。
- 旧实现事实来源：`src/agent/web/static/assets/`（app.js、sse.js、state.js、
  api.js 与 render/ 八个模块）。

## 等价矩阵

"目标阶段"对应前端方向文档的分阶段路线：1 = App Shell + Chat 纵切，
2 = 核心功能等价。标 2 的项在阶段 1 期间由旧前端继续承载。

### 会话与聊天（render/chat.js）

| # | 能力 | 后端依赖 | 目标阶段 |
| --- | --- | --- | --- |
| C1 | 会话列表、切换、标签页 | `GET /api/chats` | 1 |
| C2 | 新建会话 + 发送消息 | `POST /api/chat/start` | 1 |
| C3 | SSE 流式渲染（thinking/content/args 三种 kind） | `GET /api/chat/events` | 1 |
| C4 | 工具过程展示（model_call/action/tool_start） | SSE 事件 | 1 |
| C5 | 浏览器内审批面板（approve/deny、超时态） | `POST /api/chat/approval` | 1 |
| C6 | turn 终态渲染（final/error、失败解释） | SSE + `/api/chats/<id>` | 1 |
| C7 | 会话重命名 / 删除 | `POST /api/chat/rename` `/delete` | 1 |
| C8 | 刷新后从持久化 turn 重建历史 | `GET /api/chats/<id>` | 1 |
| C9 | 未知事件宽容（忽略不报错） | SSE 契约 §4 | 1 |

### 文件与编辑（render/files.js、render/editor.js）

| # | 能力 | 后端依赖 | 目标阶段 |
| --- | --- | --- | --- |
| F1 | 文件树浏览（workspace 路径策略内） | `GET /api/files` | 2 |
| F2 | 文件预览 | `GET /api/file` | 2 |
| F3 | 文本编辑与保存（走审批 + snapshot） | `POST /api/file/save` | 2 |
| F4 | Diff 查看（对 snapshot） | `GET /api/diff` | 2 |
| F5 | Snapshot 恢复（带确认） | `POST /api/snapshot/restore` | 2 |

### 运行与复盘（render/runs.js）

| # | 能力 | 后端依赖 | 目标阶段 |
| --- | --- | --- | --- |
| R1 | Run 列表 + 状态/风险过滤 | `GET /api/runs` | 2 |
| R2 | Run 详情：Task Review 面板 | `/api/runs/<id>` `review` | 2 |
| R3 | Workflow Hints（验证命令建议） | 同上 `workflow` | 2 |
| R4 | Failure Summary | 同上 `failure` | 2 |
| R5 | Patch Review Helper | 同上 `patch_review` | 2 |
| R6 | Run Replay（存储时间线，不执行） | 同上 `replay` | 2 |
| R7 | Failure Recovery 指引 | 同上 `recovery` | 2 |
| R8 | Trace/Replay 的 Log Filters（文本+终态） | 前端本地过滤 | 2 |

### 健康与设置（render/health.js、render/diagnostics.js）

| # | 能力 | 后端依赖 | 目标阶段 |
| --- | --- | --- | --- |
| H1 | Status Bar（workspace/provider/model/key/会话/刷新时间） | `GET /api/health` | 1（精简版）/ 2（完整） |
| H2 | Provider Notice（FakeLLM vs 真实 Provider） | 同上 `provider_notice` | 1 |
| H3 | Settings Readiness 检查 | 同上 `settings_readiness` | 2 |
| H4 | Workspace Risk 提示 | 同上 `workspace_risk` | 2 |
| H5 | Memory Review（候选与生效项，只读） | 同上 `memory_review` | 2 |
| H6 | 设置页读取 + 受控写（键白名单） | `GET/POST /api/config` | 2 |
| H7 | Tools 目录只读清单 | `GET /api/tools` | 2 |

### 壳与交互（app.js、state.js、render/ui.js、resources.js）

| # | 能力 | 说明 | 目标阶段 |
| --- | --- | --- | --- |
| S1 | 三栏布局 + 可拖拽调宽 | 新壳重新设计，不逐像素等价 | 1 |
| S2 | 深/浅主题切换 | 同一套语义 token | 1 |
| S3 | 10 秒安全自动刷新 + 手动 Refresh | 不覆盖打开的编辑器/待审批 | 2 |
| S4 | 资源详情面板（resources.js） | 并入新信息架构 | 2 |
| S5 | 基础可访问性（键盘、焦点、标签、reduced-motion） | 新壳按验收护栏做，不低于旧壳 | 1 起持续 |

## 等价判定规则

1. 逐项在新前端可用且走同一后端 Interface，不新增后端能力。
2. "等价"指能力与安全语义等价，不要求视觉与 DOM 结构一致。
3. 异常路径也在清单内：断线、刷新、unknown job、审批超时、保存失败、
   后端不可用（对应验收护栏），在阶段 2 完成前逐项打勾。
4. 本清单只增不删；实际实现发现的旧能力遗漏补录进来，而不是默默丢弃。

## 阶段 1 验收结果（2026-07-24）

| 能力 | 结果 | 证据 |
| --- | --- | --- |
| C1-C9 | 已完成 | 会话 CRUD、typed REST Adapter、14 事件 SSE 解析、sequence 去重、一次重连、历史恢复、审批与终态 E2E |
| H1（精简） | 已完成 | command spine 显示真实 workspace/provider/model/key/session 状态，不猜测 Git branch |
| H2 | 已完成 | Provider Notice 直接消费 `/api/health.provider_notice` |
| S1 | 已完成 | 桌面会话轨道可拖拽并支持键盘方向键/Home/End；移动端变为 modal sheet |
| S2 | 已完成 | A/B/C 三主题各自深浅模式，自动模式与手动选择持久化 |
| S5 | 已完成 | 焦点、ARIA/tooltip、键盘审批、320 px 布局、reduced-motion 静态 Canvas 均有自动或浏览器证据 |

完整证据见 [`verification/frontend-vnext-phase1.md`](verification/frontend-vnext-phase1.md)。

## 阶段 2 验收结果（2026-07-25）

| 能力 | 结果 | 证据 |
| --- | --- | --- |
| F1-F2 | 已完成 | 真实服务目录浏览与文件预览；截断文件强制只读、二进制与缺失文件进入可恢复错误态 |
| F3 | 已完成 | 保存经 sandbox 路径策略 + snapshot + run 记录；确认框写明 path、UTF-8 字节数与「将创建 snapshot」；dirty 缓冲不被自动刷新覆盖，离开前必须确认 |
| F4-F5 | 已完成 | 真实 unified diff（含 truncated / current_exists / snapshot_missing 状态）；恢复二次确认并写明可能删除新建文件，恢复后磁盘内容已核对 |
| R1 | 已完成 | 真实 `/api/runs` 驱动的列表与 status/risk 本地过滤 |
| R2-R7 | 已完成 | Review、Workflow、Failure、Patch Review、Recovery、Replay 全部按明确标签渲染，均标注只读，浏览器不执行 replay 或验证命令 |
| R8 | 已完成 | trace/replay 文本过滤与 All/Terminal 终态过滤 |
| H3-H5 | 已完成 | readiness、workspace risk、memory review 保留 signals 与 checks，未被精简为颜色点；memory 无 accept/reject 动作 |
| H6 | 已完成 | 仅后端白名单键可写、只发送变化键、原子落盘；`approval=never` 与 `sandbox=danger-full-access` 被真实拒绝；无密钥输入框 |
| H7 | 已完成 | Tool catalog 只读，无启用/安装/配置按钮 |
| S3 | 已完成 | 工作台开启且页面可见时 10 秒刷新，`Promise.allSettled` 单资源失败保留其他数据；dirty 编辑器与设置草稿不被覆盖 |
| S4 | 已完成 | 资源详情覆盖 chats/runs/memory/snapshots，点击可跳转真实会话与 Run detail 上下文 |

阶段 2 完成的含义是「新前端覆盖旧 Workbench 核心能力」，**不是** Frontend vNext
长期路线全部完成。根 `/` 仍返回旧 Workbench，`/preview/` 返回 React 工作台；
本阶段不切换默认入口、不删除旧资源。完整证据与已知限制见
[`verification/frontend-vnext-phase2.md`](verification/frontend-vnext-phase2.md)。
