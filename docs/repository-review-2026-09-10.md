# 全仓库分块审查

起始提交：`c991da8`。审查范围覆盖全部自有源码、测试、构建与发布配置、实际 Web 入口和文档契约，不局限于最近 diff。所有子代理使用 GPT-5.6 Sol 分块检查与修复；主代理在每块结束后交由 Astra 集中复审。

## 最终状态

| 块 | 范围 | 状态 | 结论/证据 |
| --- | --- | --- | --- |
| 1 | 构建、打包、CI、实际 Web 入口、文档契约 | 已审 | tracked React bundle 与实际入口一致；CI 增加生产 build 门禁；打包策略和当前文档契约已核对 |
| 2 | HTTP 路由、请求验证、文件/Git/终端 API | 已审 | 路由、JSON 边界、静态资源、Files、Git、Terminal 及关键错误路径已核对；配置枚举类型错误已修 |
| 3 | Sandbox、审批、文件/命令/文档/Web 工具、脱敏 | 已审 | Windows 路径保护、审批链、工具执行、持久化脱敏及 shell 截止返回已核对并修复 |
| 4 | Action、执行循环、预算、取消/超时、lease、恢复与运行存储 | 已审 | action schema、loop、预算、control、lease、恢复和 run store 的真实调用链及关键测试已核对 |
| 5 | Provider、流解析、能力声明、配置与 secrets | 已审 | Provider 错误持久化、配置类型、Unicode 配置与 secrets 诊断已修；流解析和能力声明已核对 |
| 6 | MCP、Skills、用户存储与扩展生命周期 | 已审 | 根目录链接清理、Skills 元数据身份、损坏文档诊断与事务恢复已修并复审 |
| 7 | Chat、Memory、Automation、Eval、CLI、上下文与 hooks | 已审 | Memory 版本链、持久化 status 类型、聊天恢复、hook 脱敏及相关生命周期已修并复审 |
| 8 | 全部前端组件、API/SSE、编辑/终端/设置、可访问性及测试覆盖 | 已审 | Settings、Runs、App、Files 和 Workspace 的异步竞态及可选存储边界已修；完整前端回归通过 |

## 修复与复审记录

早期检查发现并修复：

- `119d75c`：Windows 不存在路径的 `.ENV`、`.GIT` 等大小写变体不再绕过写保护。
- `f632fdc`：配置中的非 BMP Unicode 可写出有效 TOML。
- `ead9e09`：重新生成落后的正式 tracked bundle，并补真实服务验证。
- `f01e262`：共享清理函数拒绝根目录链接，避免沿链接删除外部内容。
- `67b1483`：Skills 以元数据名称作为身份，inventory/doctor 实际解析文档，并把无效 UTF-8 归一为领域错误。
- `d02ff7b`、`9d8c173`：Provider 失败保留已执行动作和聊天失败恢复证据。
- `dcb67b3`：hook 落盘复用统一脱敏。
- `bfea10d`：Memory 共享读取拒绝分叉、环与缺失父项。
- `1ca5516`：Memory/Automation 拒绝错误类型的持久化 status。
- `61d643f`、`6578209`：父进程退出但子进程继承输出管道时，shell timeout/cancel 保持截止返回；Windows ctypes 签名使用 64 位安全句柄，并处理关闭竞态。测试证明截止返回和诊断，不直接证明 reader 线程已经回收。
- `f8b79d7`、`dd09809`、`e5b4bbd`、`e4b2797`：分别修复 Settings 权限状态、Runs 迟到响应、App 重复发送与可选存储失败边界。这批修复经 Astra 集中复审。

最终覆盖阶段新增并修复：

- `099ad32`：Workbench 的 `provider`、`sandbox`、`approval` 对 JSON 数组/对象返回结构化 HTTP 400，且不写配置。
- `68a25bf`：项目配置的枚举值先验证字符串，TOML 数组/表不再泄漏 `TypeError`。
- `63d0989`：配置与 secrets 的 Unicode/OSError 读取失败归一为稳定领域错误；诊断不包含秘密内容，所有调用者保持 fail-closed。
- `47dcec2`：Files 忽略迟到的目录响应。
- `86d86d9`：Workspace 忽略迟到的资源刷新响应。
- `694da1a`：Workspace 避免自动刷新重叠，修复剩余竞态。
- `433837e`：CI 增加前端生产 build 门禁。Ubuntu 上 `build:preview` 的逐字节稳定性尚未证明，因此 CI 没有加入 tracked bundle 零漂移判断。

Astra 对配置块与 CI 块集中复审后通过。前端竞态块首轮复审为 request changes；`694da1a` 返修后再次复审为 approve。

## 最终验证检查点

最终 HEAD：`694da1ad8757b7efb15bedb89ca279a5fac3079b`，工作树干净。

- Python 全量：**1237 passed in 121.41s**。日志：`D:\CodexScratch\repository-review-2026-09-10\python-final-head-2026-09-15\full.stdout.log`；stderr 日志为 0 字节。
- 前端：typecheck、lint、UI policy、**38 条单元测试**与 `build:preview` 通过。
- Playwright：**83 条 E2E 通过，1 条显式性能采样跳过**；正式服务路径 **5 条 served E2E 通过**。
- 前端日志目录：`D:\CodexScratch\repository-review-2026-09-10\frontend-final-2026-09-15\logs`。
- `frontend/dist` 与 tracked `src/agent/web/static/preview` 的 **30 个文件路径和 SHA-256 一致**。

本检查点取代此前记录中的“进行中”“正在执行”“待收尾”和“待闭合”状态。历史修复的局部测试数字仍用于说明当时证据，最终结论以本节的当前 HEAD 全量检查为准。

## 验证限制

- 第三方生成 bundle 未逐行人工审阅；通过构建来源、实际服务路径以及 dist/tracked 30 文件 SHA-256 一致性核对。
- 未执行远程 Provider/网络验证，也未做长时间 Automation worker 压测。
- Ubuntu 上 preview 逐字节稳定性未证明，所以 CI 只加入生产 build，没有加入跨平台 bundle 零漂移检查。
- 没有复现 wheel 漏包，因此不把它记录为发布缺陷。
- 性能采样用例显式跳过，不宣称已完成性能基准验证。

审查与复现临时输出统一位于 `D:\CodexScratch\repository-review-2026-09-10`。
