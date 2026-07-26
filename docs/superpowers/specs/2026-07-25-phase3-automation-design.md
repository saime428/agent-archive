# 设计：Phase 3C 可审计 Automation

- 日期：2026-07-25
- 状态：设计已审查；待实施
- 上位方向：[Phase 3 方向分析与审查](../../project-vnext-phase3-direction-review.md)

## 目标

为个人生产工具补一条显式、前台、本地的 Automation 闭环：定义固定间隔任务，显式启停，前台
worker 幂等 claim 到期 slot，复用同一 Agent runtime 执行，并把 attempt、异常通知、取消和崩溃恢复
持久化。

本切片完成后只允许声明“3C Automation 完成”；Phase 3、Frontend vNext 和 Project vNext 核心
仍未完成。

## 实施前基线

- 仓库没有 Automation 生产 Module、CLI、store 或 worker。
- Phase 3A 已提供 `RunControl`、整轮 timeout、受控命令进程树停止和跨进程
  `WorkspaceRunLease`；CLI/Web 已共用同一 `run_once`、Provider、MCP 与安全链。
- 系统没有任务队列、数据库、后台服务或操作系统计划任务，本切片也不引入。

## 固定产品语义

### 定义与 schedule

- 新定义只有 task、固定 `interval_seconds`、可选 Skills 和 `timeout_seconds`。CLI 暴露
  `--every-minutes`，不实现 cron、自然语言时间、时区 UI、一次性日历或依赖关系。
- add 后默认 disabled；enable 写一条 enabled revision，并以当前 UTC 时间作为 `anchor_at`，因此显式
  启动 worker 后首个 slot 立即到期。disable 写 revision，只阻止未来 claim，不暗中取消已运行 attempt。
- 当前定义是 `definitions.jsonl` 中每个 automation id 的最后一条 revision；完整 revision log 保留审计。
- 到期 slot 固定为 `anchor + floor((now-anchor)/interval) * interval`。worker 只 claim 当前最新到期
  slot，不追补全部历史 backlog；需要补跑时新建/重新 enable，而不是突然执行一串旧任务。

### 幂等与 attempt

- 幂等键是 `automation_id + scheduled_for`。claim 在 Automation OS 文件锁内重新读取权威日志，
  同一 slot 只能原子追加一个 claimed attempt；并发 worker 不会重复执行。
- attempt 使用 append-only 状态链：`claimed → running → succeeded|failed|cancelled|timed_out`；worker
  崩溃留下的 `claimed/running` 在下一个独占 worker 启动时终结为 `interrupted`。
- 每条 attempt 固定保留 automation id、slot、run id、时间、相对 summary 路径、状态和有界脱敏错误。
  failed/cancelled/timed_out/interrupted 的终态记录同时是 durable local notification event；不建第三份
  通知数据库。
- 取消是每个 attempt 的单文件 marker。CLI 原子发布 marker；`RunControl.stop_reason()` 通过有界 probe
  观察它，模型流与 Tool/受控子进程沿既有取消路径停止。终态不可再次取消或改写。

### worker 与 runtime

- `agent automation worker` 是用户显式启动的前台进程；`--once` 做一次恢复、claim、执行后退出，
  默认模式以有界 poll 间隔循环。绝不安装服务、注册 Task Scheduler、写启动项或自启动。
- 一个 workspace 同时只有一个 Automation worker，使用独立 worker OS lock；定义启停和 cancel 使用
  store lock，不能被长持有 worker lock 阻塞。
- 每个 attempt 读取执行时的 workspace secrets/config，创建标准 Provider 与 MCP runtime，获取
  `WorkspaceRunLease`，调用 `run_once`，最后关闭 MCP。run id 与普通 Runs/Review 完全兼容。
- worker 不提供 approval handler。任何 `approval_required` 动作继续由既有 policy 产生
  `APPROVAL_REQUIRED`，不会被 worker 自动批准；低风险动作照常运行。
- workspace busy、config/provider/MCP/runtime 异常和非完成 RunResult 都写 failed attempt/notification，
  `--once` 返回非零；一个失败不破坏日志或重复同一 slot。
- Ctrl+C/SIGTERM 设置 worker stop event；当前 attempt 通过同一 cancel probe 收口，未开始的已 claim
  attempt 终结为 cancelled，进程退出前不留下伪 running 状态。

## 存储与安全

- 存储固定在 `.agent/automations/`：`definitions.jsonl`、`attempts.jsonl`、`cancel/` 与独立
  `worker/` lock root。
- 复用 `_user_store.store_lock`、`atomic_replace_bytes`、plain-file 与 link/reparse 校验；不复制第二套
  OS lock，不引入 SQLite、队列或第三方 scheduler。
- ID 使用 `auto_` / `attempt_` + UUID；旧/畸形状态、重复 slot、非法 transition、超限正文/store、
  非普通文件和 link/reparse 明确报 `AutomationError`。
- task、错误和通知在持久化前走既有 redaction；CLI 不打印 secrets 或未脱敏异常详情。

## CLI

```text
agent automation add <task> --every-minutes <n> [--skill <name>] [--timeout-seconds <n>]
agent automation list
agent automation history <automation-id>
agent automation enable <automation-id>
agent automation disable <automation-id>
agent automation worker [--once] [--poll-seconds <n>]
agent automation attempts [--automation-id <id>]
agent automation notifications
agent automation cancel <attempt-id>
```

不增加 update/delete/run-now：修改 task 或 interval 时新增定义；需要重置 schedule 时 disable 后再 enable。

## 验收

- add/enable → due claim → `run_once` → run summary → succeeded attempt；重复/并发 claim 不重跑。
- disable 后不产生新 slot；cancel 能停止正在流式生成的 attempt；下次 worker 能恢复 crashed attempt。
- approval-required Tool 不执行；workspace lease 冲突、Provider/MCP/config 失败写非零 attempt/notification。
- CLI、定义历史、attempt/notification、损坏/link/原子失败、全量 Python、真实 worker、wheel 字节与
  D 盘 detached worktree 通过；temp、worker lock owner 和进程无残留。

## 非目标

- Web/React Automation 管理面、HTTP API、系统通知、邮件、webhook、远程 worker、分布式队列。
- cron/RRULE、自然语言时间、时区/节假日、补跑 backlog、retry/backoff、优先级、依赖 DAG。
- 无人值守高风险写入或 approval bypass；系统服务、Windows Task Scheduler、开机自启。
- eval、Editor/Search、Git、Terminal、Command/Layout、legacy retirement 或 Phase 4–5 生态入口。
