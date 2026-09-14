# 全仓库分块审查

起始提交：`c991da8`。本次范围是全部自有源码、测试、构建/发布配置与文档契约，不局限于最近的前端 diff。第三方生成 bundle 不逐行人工审阅，但核对其来源、打包和实际服务路径。所有子代理使用 GPT-5.6 Sol 完成分块检查与修复；主代理在每块结束后交由 Astra 集中复审。

状态必须区分“待审”“进行中”“已审”；已有测试通过不等于模块已审完。每块检查入口、关键调用者、错误路径、数据一致性与对应测试。发现问题先复现，修复按问题单独收尾。

| 块 | 范围 | 状态 | 结论/证据 |
| --- | --- | --- | --- |
| 1 | 构建、打包、CI、实际 Web 入口、文档契约 | 进行中 | 已修 tracked bundle；仍需最终覆盖核对与前端完整回归 |
| 2 | HTTP 路由、请求验证、文件/Git/终端 API | 进行中 | 已读 server、files、terminal；仍需闭合其余路由和测试关联 |
| 3 | Sandbox、审批、文件/命令/文档/Web 工具、脱敏 | 进行中 | Windows 路径保护与 shell timeout 已修；仍需闭合全块覆盖 |
| 4 | Action、执行循环、预算、取消/超时、lease、恢复与运行存储 | 进行中 | Provider 失败持久化与恢复已修；仍需最终覆盖核对 |
| 5 | Provider、流解析、能力声明、配置与 secrets | 进行中 | 配置 Unicode 写入已修；仍需结束关联路径审查 |
| 6 | MCP、Skills、用户存储与扩展生命周期 | 已审 | 产品实现与关键测试路径已审；3 项实证问题已修复，未逐行审第三方 fixtures |
| 7 | Chat、Memory、Automation、Eval、CLI、上下文与 hooks | 已审 | 产品实现及关键测试路径已审；Memory 链、状态类型、hook 脱敏已修；未做远程 Provider 或长期 worker 压测 |
| 8 | 全部前端组件、API/SSE、编辑/终端/设置、可访问性及测试覆盖 | 进行中 | 已修窄屏编辑、Settings、Runs、App 与可选存储；前端完整回归正在执行 |

## 已知前端修复

- `4f59983`：命令面板切换视图复用未保存确认。
- `c991da8`：外部 Radix 弹窗与窄屏工作台协调模态状态，保留焦点和草稿。
- 该修复后的验证为 38 条单元测试通过、72 条 Playwright 通过、1 条可选性能采样跳过，以及 typecheck/lint/UI policy/build 通过。

审查与复现临时输出：`D:\CodexScratch\repository-review-2026-09-10`。本记录随各块完成更新，不以局部通过宣称全仓库完成。

## 2026-09-10 继续检查的落点

- 修复前 Python 全套：1183 passed；该结果仅是基线，不代表代码审查完成。
- `119d75c`：Windows 不存在路径的 `.ENV`、`.GIT` 等大小写变体绕过写保护；共享路径检查使用平台大小写规范化。相关测试 54 passed。
- `f632fdc`：配置包含非 BMP Unicode 时写出非法 TOML；保留 Unicode 并转义 DEL。相关测试 63 passed。
- `ead9e09`：正式 `agent web` 服务的 tracked bundle 落后于 React 源码；重新生成并补真实服务验证。build:preview、5 条 served E2E、7 条静态资源测试通过。
- 待收尾：模型写文件后下一次请求抛 ProviderError，`tool_calls.jsonl` 与摘要未生成；用临时工作区和模拟 Provider 复现。
- 待收尾：Skills 事务恢复清理的根目录若为目录链接，会进入外部目录删除内容；Astra 使用隔离临时目录复现，GPT-5.6 正在修共享清理函数。
- 待处理：hook 日志未使用现有脱敏函数；模拟 Authorization Bearer 字符串能原样落盘，现有 redactor 能识别同一字符串。
- 块 6 另外两项已报告的 Skills 元数据问题仍需收尾：目录名与声明名称不一致时冲突判断错误；doctor 未解析损坏 SKILL.md 却报告健康。

## 2026-09-12 续审检查点

以下更新取代上面的历史“待收尾”状态：

- `f01e262`：共享清理函数拒绝根目录链接；101 条相关测试通过。
- `67b1483`：Skills 身份统一为元数据名称，inventory/doctor 实际验证文档，无效 UTF-8 归一为领域错误；64 条 Skills 测试通过。
- `d02ff7b`：Provider 请求失败时持久化已经执行的动作与终止失败；266 条相关测试通过。
- `dcb67b3`：hook 落盘边界复用现有脱敏；94 条相关测试通过。
- `9ed503c`：窄屏搜索跳转后输入光标不再复位；真实 E2E、typecheck、lint、build:preview 通过。
- `9d8c173`：Provider 失败的聊天轮次标为 failed，保留恢复入口；27 条相关测试通过。
- `bfea10d`：Memory 共享读取校验版本链，拒绝分叉、环与缺失父项；13 条 Memory 测试通过。
- `1ca5516`：Memory/Automation 拒绝错误类型的持久化 status，使用领域错误诊断。

## 2026-09-14 事实检查点

以下修复已完成，并经 Astra 集中复审：

- `f8b79d7`：Settings 显示实际 Provider 与高权限 sandbox 状态。
- `dd09809`：Runs 详情与 diff 忽略迟到响应。
- `61d643f`、`6578209`：父进程退出但子进程继承输出管道时，shell timeout/cancel 保持截止返回；Windows `CancelIoEx` 使用 64 位安全 ctypes 签名，并处理关闭竞态。现有测试断言截止返回与诊断，没有直接断言 reader 线程已回收，因此不作该保证。
- `e5b4bbd`：App 锁定启动请求并保留草稿，避免重复发送。
- `e4b2797`：浏览器可选存储不可用时不再阻断启动或运行状态清理。

修复后 Python 全量在 HEAD `e4b2797a4db1b4772a0beb774eadaf5975e58cc4` 验证：1219 passed，121.68 秒。日志：`D:\CodexScratch\repository-review-2026-09-10\python-full-2026-09-14\pytest-full.log`。

旧的“待收尾/待独立修复”状态现更正为：上述问题已修复并集中复审；块 1–5 和块 8 仍处于进行中，等待最终覆盖核对与前端完整回归。前端完整回归正在由另一名 GPT-5.6 Sol 子代理执行。

下一批必须闭合全仓库剩余覆盖，包括未形成 diff 的路径，不能只复审本轮改动。所有子代理继续使用 GPT-5.6 Sol；主代理在每块结束后再交由 Astra 集中复审，以减少重复审查消耗。
