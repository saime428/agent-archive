# Project vNext 最终矩阵验收记录

- 日期：2026-07-25
- 状态：Project vNext 核心完成
- 完成范围：阶段 0–3
- 需求触发范围：阶段 4–5
- 产品候选提交：`3e46fbbee888591d418ec35f93a4836b4be9fcab`

## 结论

阶段 0–3 的建设切片、旧壳退役和最终全链路缺陷清零均已完成。修复最终矩阵发现的
Python checkout/wheel 换行不确定性后，源码、两个独立 detached checkout 和 wheel 使用同一
产品提交整套复跑；对话、生成、前端、后端/API、CLI、打包、真实 Provider 与可见浏览器均通过。

因此，Project vNext 按“个人生产工具 + 完整作品”的当前定义完成。阶段 4–5 的生态中心、
分发、远程与社区能力没有实现，也不计入当前完成门；只有文档中的真实需求触发后才另开 spec。

## 确定性构建

- 最终矩阵首先复现出同一 Git tree 在主工作树与 detached checkout 构建出不同 wheel：
  36 个 Python entry 只有 CRLF/LF 差异，`RECORD` 因此不同。
- 根因是 `core.autocrlf` 可改变 checkout，而仓库没有固定 Python 源码行尾。修复在
  `.gitattributes` 增加 `*.py text eol=lf`，并用一个文档/构建契约测试锁定，不增加依赖或新构建层。
- 固定 `SOURCE_DATE_EPOCH=1785053752` 后，主工作树和两个独立 detached checkout 构建结果完全一致：
  `agent-2.1.0-py3-none-any.whl`，1,271,103 bytes，SHA-256
  `d60c97c66f31bab08bb4f1f868b1f4c2793c9c47e52d3cfabb58d9e1d1adaa34`。
- wheel 含 51 个 Python 文件，全部 LF；含 30 个 React preview 文件，legacy 文件为 0。

## 最终测试矩阵

| 范围 | 修复后结果 |
| --- | --- |
| Python 源码 | `1165 passed`；`compileall` 通过 |
| 隔离 wheel | 从 D 盘 wheel-site 导入，`1165 passed` |
| 前端静态门禁 | typecheck、lint、UI policy、production build、tracked preview 零漂移 |
| 前端测试 | 33 Vitest；59 Playwright passed；14 个视觉基线通过 |
| 30 秒性能门禁 | 约 59.50 FPS，0 long task，187 个流式 chunk |
| 实服 wrapper | Windows 6 passed；POSIX-only 1 skipped；源码与 wheel 核心实服各 5/5 passed |
| 后端/API | 根与 preview、query-preserving 308、no-store/CSP、gzip、health 均通过；4 个退休 URL/API 均 404 |
| CLI 与诊断 | doctor、config、release doctor、Tools、Hooks、MCP、Skills、Memory、Automation、`pip check` 均通过 |
| 对话与生成 | Fake run、交互 chat、resume、runs、4/4 eval、真实 DeepSeek JSON/native-tools smoke 与 streaming chat 均通过 |
| 可见浏览器 | wheel 实服完成 FakeLLM turn、命令面板、Files、根/preview 路径；页面 console warning/error 为 0 |
| Git/静态审计 | `git diff --check`、全分支 diff、dead-symbol/legacy/TODO/FIXME 检查均通过；Python index/worktree/attribute 全部 LF |

默认 Playwright 组合按设计跳过 30 秒性能录制，最终矩阵已单独显式执行并通过。POSIX wrapper
只因当前验收主机是 Windows 而跳过；对应 Windows 路径和跨平台核心实服路径均通过，不是未解决产品 finding。
浏览器控制插件自身的 Statsig telemetry 曾超时，但页面 console 为空、产品请求与交互正常，
该外部 connector telemetry 不计为应用缺陷。

## 缺陷清零

最终矩阵发现并复现 1 个产品/构建缺陷：同一提交可能因 Git checkout 行尾产生不同 wheel。
修复落在仓库 checkout 契约，而不是给 wheel 结果做事后改写；随后源码、wheel、前端、实服、
CLI、Provider 和可见浏览器矩阵全部重跑通过。当前矩阵内没有遗留可复现 finding。

这不表示软件未来不可能出现新缺陷；它表示当前完成定义、当前平台与已列矩阵中发现的可复现缺陷已经清零。

## 清理与仓库状态

- 端口 4173–4176、8000、8767 均已关闭；没有运行中的验收后台任务。
- D 盘 Phase 3G–3I 和最终矩阵材料合计 1,060,736,926 bytes，均为可重建测试输出、依赖副本、
  wheel 或 detached worktree；未获得清理授权，因此保留。
- C 盘共享 npm cache 当前为 1,291,173,524 bytes；pytest 只剩 3 个空目录和 current 链接。
  按 C 盘变更规则未清理，不能把共享 cache 的全部体积归因于本项目。
- 主工作树只保留两份用户原有的未跟踪 handoff；未修改、未暂存。没有 push、Ready 或 merge。

## 完成检查

- [x] 阶段 0–2 契约、扩展内核、生命周期、Frontend 等价与默认入口有当前证据
- [x] 阶段 3A–3I 的生产力闭环全部完成
- [x] 对话、生成、前端、后端/API、CLI、打包、真实 Provider 与浏览器整套通过
- [x] 最终矩阵发现的可复现缺陷已修复并完成修复后全量复跑
- [x] 源码、detached checkout、构建产物、wheel、文档与 Git 证据一致
- [x] 阶段 4–5 保持需求触发，不阻塞当前核心完成
