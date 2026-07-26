# Phase 3D 小而稳定的 Eval 实施计划

- 日期：2026-07-25
- 状态：已完成；实现与独立验收通过
- 设计：[Phase 3D 小而稳定的 Eval](../specs/2026-07-25-phase3-stable-eval-design.md)

## 固定边界

- 只修改 Eval core composition、CLI、直接测试、README/Changelog/路线与验收文档。
- 复用 `run_once`、FakeLLM、run logs、redaction 和 `_user_store` 原子发布；不新增依赖、config schema、
  Provider/MCP transport、Web route/UI 或通用评测框架。
- 所有提交后 workspace、wheel、cache 与 detached worktree 放在 `D:\CodexScratch`；两份未跟踪
  handoff 不修改、不暂存。

## Task 1：文档与红灯

提交 spec、plan、verification 骨架和 docs 契约。新增 `tests/test_eval.py` 与 CLI 测试，先覆盖：

- 4 个 case 的精确 metrics/期望与两次运行 deterministic signature；
- report schema、相对路径、脱敏/有界 failure 和原子写；
- workspace config/secrets/MCP/Skills 不影响固定 Fake gate；
- CLI 成功输出/退出 0，以及 mismatch 输出详情/退出 1；
- 重复/非法 case id、link/reparse 与 report 发布失败。

## Task 2：最小 Eval core

新增 `src/agent/core/eval.py`：冻结的 case/result/report dataclass，4 个内置 case，安全 eval 目录准备，
顺序执行 helper、tool trace 计数、期望比较、聚合和 256 KiB 原子 report。case workspace 各自调用一次
真实 `run_once`；duration 由 monotonic clock 观察但不进入 pass/fail。

不创建 repository、runner Interface、case loader 或 metrics registry；只有一个内置实现。

## Task 3：CLI

注册 `eval` Typer 子命令和 `agent eval run --cwd`。每个 case 与 totals 使用直接单行输出；全部通过返回
0，任一失败返回 1。CLI 不接受 provider、case path、并行度、阈值或上传参数。

## Task 4：审查与验证

执行 Eval/CLI 定向、core loop/policy/filesystem 相关集和全量 Python。五轴审查确认：真实 runtime 未被
复制、期望不依赖时间、审批无 bypass、报告不含 secrets、路径/日志有界且重复 signature 稳定。

## Task 5：提交后真实路径

从最终代码提交创建 D 盘 detached worktree：

- 重跑目标与全量 Python；
- 在带 DeepSeek/project config 的 workspace 从源码和隔离 wheel 各执行两次 `agent eval run`，语义
  signature 一致且 4/4；
- 构造失败 report/CLI 非零路径；比较 Eval/CLI 与 14 个 React runtime 文件逐字节一致；
- `release doctor`、`git diff --check`、worktree/temp/process 清理。

最后更新 verification、方向与 roadmap，只声明 3D 完成，下一步为 3E Editor/Search。

## 完成门

- 4 个固定 case 覆盖完成、Tool、错误恢复和审批拒绝，重复 signature 一致；
- metrics/failure detail/report/退出码可审计且有界脱敏；
- workspace 真实配置不污染 Fake gate，无真实网络请求；
- 全量、真实 CLI、wheel、提交后复验和清理通过；
- Project vNext 核心仍保持未完成。
