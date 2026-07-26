# Phase 3D Eval 验收记录

- 日期：2026-07-25
- 状态：3D Eval 已完成并通过完成门；Phase 3 与 Project vNext 核心仍未完成
- 设计：[`2026-07-25-phase3-stable-eval-design.md`](../superpowers/specs/2026-07-25-phase3-stable-eval-design.md)
- 计划：[`2026-07-25-phase3-stable-eval.md`](../superpowers/plans/2026-07-25-phase3-stable-eval.md)

## 完成边界

3D 只完成 4 个内置 FakeLLM case、真实 `run_once` 指标、稳定判定、CLI 退出码与本地 report。
真实 Provider benchmark、用户 case/plugin、Web 管理面、CI 服务和趋势数据库不在本切片。

Project vNext 核心仍未完成；后续仍需 Phase 3E–3I 和最终全链路缺陷清零。Phase 4–5
继续是需求触发项。

## 实现结果

- 新增 `agent.core.eval`，4 个冻结 case 依次覆盖 direct completion、read、一次可恢复错误后完成和
  approval-required write 拒绝；每个 case 都在独立 workspace 调用真实 `run_once`。
- 固定 `provider=fake`、`mode=auto`、空 Skills、无 MCP/approval handler；不读取外层 workspace 的
  config、secrets、hooks 或 MCP，因此硬门禁不依赖网络和 API key。
- case 精确比较 completed、terminal action/status/error、Tool/error 次数和禁止副作用；duration 只记录。
  `deterministic_signature()` 明确排除 ID、时间、路径和 duration。
- 报告写入 `.agent/evals/eval_<uuid>/report.json`，schema 为 `agent-eval-v1`；case 的真实 summary 与
  tool trace 同目录保留。目录拒绝 link/reparse，report 复用 256 KiB 原子发布，异常详情先脱敏再有界。
- CLI 新增 `agent eval run`；逐 case 与 totals 单行输出，4/4 返回 0，mismatch、执行异常或存储错误
  返回 1 且不打印 traceback。

## 自动化证据

- 预期红灯：`tests/test_eval.py` 因 `agent.core.eval` 不存在而 collection error。
- 最终 Eval 定向：`6 passed in 0.87s`；Eval/CLI/docs：`161 passed in 13.94s`；loop/policy/filesystem
  相关集：`281 passed in 16.40s`。
- Web 请求拒绝修复后：`tests/test_web.py` 为 `119 passed in 6.15s`，完整 Web 文件连续复跑 10 次
  全部通过。
- D 盘 basetemp 工作树全量：`1139 passed in 114.38s`。
- 最终代码提交 D 盘 detached worktree + D 盘 basetemp 全量：`1139 passed in 109.35s`。
- `compileall`、`git diff --check`、wheel `release doctor` 与 detached Git clean 通过。

## 提交、wheel 与真实 CLI

- 最终代码提交：`909c9a51feeb9b6e7c8983c5f470ce3817d27115`。
- tree：`22f66d6cdbf549b8098509b96e93f7246013a8bd`。
- wheel：`agent-2.1.0-py3-none-any.whl`，504,512 bytes，SHA-256
  `9bece635bc77c209a08fbf1412b3a83c108b548556b12e16472899aaf436cc2a`；`core/eval.py`、`cli.py`、
  `web/server.py` 与 14 个 React runtime 文件均与 detached 源码逐字节一致。
- wheel import 路径确认来自隔离 `wheel-site`。在同时含 DeepSeek provider、缺失 Skill、失败 hook、
  无效 MCP TOML 和 sentinel secret 的 workspace 连跑两次 `agent eval run`，均为 4/4，且去掉
  ID/duration/report 路径后的 CLI 语义输出逐字相同：completed=3、tool_calls=4、errors=2。
- 两份 report 均不含 provider、缺失 Skill 或 sentinel secret。把 `.agent/evals` 换成普通文件时，
  隔离 wheel CLI 稳定退出 1、提示真实目录约束且无 traceback。

## 验收中发现并修复

1. 3C 的 `.agent/automations/` 与新增 `.agent/evals/` 未进入 `.gitignore`，在仓库根运行会产生误导性
   untracked 本地状态；现统一加入忽略规则并由文档契约测试锁定。
2. 首次全量出现 `test_workbench_rejects_simple_form_write_without_json_content_type` 的 Windows 10053
   连接中止。根因是拒绝路径在读取已声明 body 前发送 4xx 并关闭 socket，Windows 高负载下可能以
   RST 丢掉响应。Web handler 现在对不超过既有 64 KiB 上限的拒绝 body 先消费再响应；Host、Origin、
   JSON 类型与大小边界不放宽。修复后完成单文件 119 项和连续 10 轮复跑。

## 清理与状态

- `D:\CodexScratch\agent-phase3d-*` 的 source/wheel smoke、detached worktree、wheel、cache、wheel-site、
  basetemp 与失败 workspace 已按核对后的绝对路径删除；Git worktree 只剩主工作树。
- pytest 早期默认在 C 盘留下 `pytest-220`、`pytest-221`、`pytest-222` 与 `pytest-current`，约
  37.1 MB。最终有效全量已改用 D 盘 basetemp；C 盘项未在无授权时删除，已向用户单独请求许可。
- 两份用户原有的未跟踪 handoff 文档未修改、未暂存；没有 push、Ready 或 merge。
- 未新增依赖、真实 Provider 网络门、用户 case/plugin、Web Eval 管理面、数据库或 CI 服务。

## 完成门

- [x] 4 个固定 case 的完成/错误/Tool 次数与副作用期望正确
- [x] 两次运行的 deterministic signature 一致，duration 不参与门禁
- [x] workspace config/secrets/MCP/Skills 不污染 Fake gate
- [x] failure detail/report/CLI 退出码有界、脱敏且可审计
- [x] link/reparse、非法定义与原子发布失败安全
- [x] 目标、全量、真实 CLI、wheel 与提交后复验通过
- [x] D 盘 temp/worktree/process 清理通过

下一切片是 3E Editor/Search；本记录不构成 Phase 3 或 Project vNext 核心完成声明。
