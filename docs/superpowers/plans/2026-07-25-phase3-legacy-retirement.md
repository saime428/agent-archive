# Phase 3I Legacy retirement 实施计划

- 日期：2026-07-25
- 状态：待实施
- 设计：[Phase 3I Legacy retirement](../specs/2026-07-25-phase3-legacy-retirement-design.md)

## 固定边界

- 只退休旧壳、`/legacy/`、同步 `/api/chat/turn` 及其无调用者代码；现行 React/async Interface 不变。
- 不新增 dependency、feature flag、兼容 shim、tombstone 页面或数据迁移。
- 历史验收文档保持历史事实；只更新 README、CHANGELOG、当前方向、roadmap 和新 3I 验收记录。
- 临时 checkout、wheel、site、served workspace 和测试输出放在 `D:\CodexScratch`；两份既有 handoff 不修改、
  不暂存。D/C 盘遗留项按既有授权边界处理。

## Task 1：文档与失败契约

提交 spec、plan、verification 骨架和 docs 契约。修改 Python/served E2E，使最终契约先因 `/legacy`、旧资产与
同步 turn 尚存在而失败；同时锁定根、`/preview/` 和 async chat 不变。

## Task 2：删除旧产品路径

删除 14 个旧静态文件；从 server 删除 legacy map/alias 与同步 turn route；从 chats/runtime 删除只有这些路径
使用的 wrapper、approval helper 和 lease helper。搜索所有调用者，保留 async runtime 共用的 state/response
投影与 session reservation。

## Task 3：保持有效覆盖

删除只读取旧 DOM/JS 或验证同步兼容层的测试。现行产品行为继续由 ChatRuntime、core chat、React unit/E2E 和
served-wheel 测试覆盖；必要时只补最小 async 断言，不在测试中重建被删除的同步 wrapper。

## Task 4：审查与独立验收

先跑 3I 定向 Python/served 契约，再跑 frontend 与 Python 全量、CLI、docs、release doctor、diff check 和
静态生产引用扫描。五轴审查重点检查 Interface 意外删除、测试覆盖弱化、package 残留、未知 POST body 处理、
数据/安全语义和文档历史边界。

从最终代码提交创建 D 盘 detached worktree，执行双 wheel 确定性、wheel-site Python/served 实服、源码与 wheel
资产闭包、真实浏览器根/preview/retired-path/API/chat smoke、console 和窄屏检查。完成后更新 verification、方向与
roadmap，只声明 3I 完成，并进入最终跨 Interface 缺陷清零矩阵。

## 完成门

- 旧壳文件、生产引用和同步兼容实现均不存在；退休 URL/API 稳定返回 404。
- 根与 `/preview/` 的 React、async 对话、Files/Git/Terminal/Runs/System、审批和数据均无回归。
- source、detached、wheel、served-wheel、可见浏览器和 package inventory 一致。
- 3I 完成后仍明确标记 Project vNext 核心为未完成，直到最终全量矩阵与缺陷清零完成。
