# 设计：Phase 3D 小而稳定的 Eval

- 日期：2026-07-25
- 状态：已实施并通过独立验收；下一切片为 3E Editor/Search
- 上位方向：[Phase 3 方向分析与审查](../../project-vnext-phase3-direction-review.md)

## 目标

给当前 Agent runtime 增加一条小型、离线、确定性的质量门：固定 case 使用 `FakeLLMClient` 经过真实
`run_once` 执行，记录完成、错误、Tool 次数与耗时，按精确期望判定并用稳定退出码供本地回归使用。

本切片完成后只允许声明“3D Eval 完成”；Phase 3、Frontend vNext 和 Project vNext 核心仍未完成。

## 固定参考集

首版只有 4 个内置 case，不读取用户定义、不扫描目录、不建立插件系统：

1. `direct_completion`：零 Tool 直接 done；
2. `read_then_finish`：读取固定 fixture 后 done；
3. `recover_after_missing_file`：先得到一次可恢复文件错误，再读取存在的 fixture 并 done；
4. `approval_stays_blocked`：请求写文件但不提供 approval handler，必须以 `APPROVAL_REQUIRED` 终结，
   且目标文件不存在。

每个 case 固定 task、fixture、Fake action 序列与期望：是否 completed、终态 action/status/error code、
Tool 调用次数、error observation 次数及禁止出现的文件。任何一项不符即 case failed，并列出实际值与
期望值。

## 执行与隔离

- 新增最小 `agent.core.eval` composition，直接复用 `run_once`、`AgentConfig` 与 `FakeLLMClient`；不复制
  parser、Tool executor、policy、approval、sandbox、redaction 或 run log 逻辑。
- eval 使用固定 `provider=fake`、`mode=auto`、空 default Skills、无 MCP runtime、无 approval handler；
  不读取 workspace config/secrets，因此项目中的真实 Provider、API key、MCP 或 hook 不影响硬门禁。
- 每次运行在 `<workspace>/.agent/evals/eval_<uuid>/cases/<case-id>/` 建立独立 workspace。case 的
  `.agent/runs` 保留真实 summary/tool trace；不同 case 不共享文件或 Memory。
- `.agent`、`evals` 与本次 eval 目录必须是本地真实目录，拒绝 link/reparse；report 使用既有
  `_user_store.atomic_replace_json` 发布，失败不能留下半份 report。
- case 抛出普通异常时转为 failed detail，先脱敏再有界；`KeyboardInterrupt` 不吞掉。

## 指标与判定

每个 case 记录：`passed`、`completed`、terminal action/status/error、`tool_calls`、`errors`、
`duration_ms`、run id、相对 summary 路径与 failure detail。聚合记录 total/passed/failed/completed、
Tool/error 总数和总耗时。

`duration_ms` 只用于观察，不参与通过判定，避免机器负载造成假红灯。重复运行的一致性定义为：排除
eval/run id、时间戳、summary 路径和 duration 后，case 顺序、完成态、错误码、Tool/error 次数与总通过
结果完全一致。

全部 case 符合期望时退出 0；任一 case mismatch 或执行异常时仍写 report、打印失败详情并退出 1。
这只是本仓库回归门，不把 4 个 Fake case 宣称成真实模型 benchmark 或产品效果分数。

## 本地报告与 CLI

唯一首版入口：

```text
agent eval run [--cwd <workspace>]
```

CLI 每个 case 输出一条有界单行，再输出 totals 与相对 report 路径。report schema 固定为
`agent-eval-v1`，最大 256 KiB；不保存 prompt 全文、secrets、环境变量或真实 Provider 响应。

不增加 list/show/delete、用户 case 文件、阈值配置、并行执行、重试、趋势数据库或 CI 服务。报告和
case run 保留在 `.agent/evals` 便于人工审计；出现真实空间压力时再增加显式 retention/cleanup。

## 验收

- 两次参考集运行的确定性 signature 完全一致，4 个 case 全通过；metrics 与原始 tool trace 对齐。
- 审批 case 不创建文件；workspace config 即使指定 DeepSeek、hook、Skill 或 MCP，也不改变 eval。
- 注入 case 执行异常时 report 有有界脱敏 failure detail，CLI 退出 1 且无 traceback。
- link/reparse、report 原子失败、非法/重复 case 定义安全失败。
- 目标测试、全量 Python、真实 CLI、wheel 字节与 D 盘 detached worktree 通过；临时数据清理完成。

## 非目标

- 真实 Provider 在线 benchmark、模型排行、LLM-as-judge、随机/统计采样、token/cost 硬阈值。
- Web/API/React Eval 管理面、CI SaaS、历史趋势数据库、远程上传或共享 leaderboard。
- 用户自定义 case/plugin、并行 runner、retry、flaky quarantine、覆盖率替代品。
- Editor/Search、Git/Diff、Terminal、Command/Layout、legacy retirement 或 Phase 4–5 需求触发项。
