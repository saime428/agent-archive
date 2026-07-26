# Phase 3B Memory 验收记录

- 日期：2026-07-25
- 状态：3B Memory 已完成并通过完成门；Phase 3 与 Project vNext 核心仍未完成
- 设计：[`2026-07-25-phase3-memory-lifecycle-design.md`](../superpowers/specs/2026-07-25-phase3-memory-lifecycle-design.md)
- 计划：[`2026-07-25-phase3-memory-lifecycle.md`](../superpowers/plans/2026-07-25-phase3-memory-lifecycle.md)

## 完成边界

3B 只完成 candidate reject、entry revise/delete/history、current-leaf retrieve 与并发/原子存储。
Automation、eval 和 Frontend 开发工作区不在本切片；Web 继续只有 Memory Review 只读消费路径。

Project vNext 核心仍未完成；后续还需 Phase 3C–3I 和最终全链路缺陷清零。Phase 4–5
继续是需求触发项。

## 实现结果

- 继续使用 `.agent/memory/candidates.jsonl` 与 `entries.jsonl`；旧时间戳 ID 和无 `candidate_id`
  的 entry 不迁移即可读取，新 ID 使用既有前缀加 UUID。
- mutation 共用 `_user_store.store_lock` 与 `atomic_replace_bytes`。accept 只原子发布带
  `candidate_id` 的 entry，accepted 状态由 entry 推导；reject 只改 candidate 日志，revise/delete
  只改 entry 日志，竞争决策在锁内重新读取后只有一个成功。
- revise 创建 superseding active entry，delete/undo 创建 tombstone；历史节点不能再次 mutation，
  `list_entries()`、`retrieve()`、模型 Memory message 与 Workbench active payload 只使用当前 active 叶节点。
- 内容继续先脱敏；空/超限正文、非法 ID/状态、畸形 JSON、重复 ID、link/reparse、非普通文件、
  超限 store 和原子发布失败均显式报 `MemoryError`，旧文件在发布失败时保持原字节。
- CLI 保留 `review/list/accept/undo`，新增 `reject/revise/delete/history`；固定状态输出绕过 Rich
  自动折行，长 UUID 仍保持单行。

## 自动化证据

- 预期红灯：Memory/CLI 定向基线 `10 failed, 2 passed`，覆盖旧 active 未隐藏、缺命令、重复
  accept、损坏 JSON traceback 与非原子写。
- 修复后定向：Memory/CLI `12 passed`；Memory + run loop + Workbench `16 passed`；相关 CLI、
  core loop、UI 与 user-store `304 passed`。
- 工作树全量：`1114 passed in 107.33s`。
- 最终代码提交 D 盘 detached worktree 全量：`1114 passed in 110.74s`。
- `agent release doctor --cwd .`：`release readiness: complete`；`git diff --check` 通过。

## 提交、wheel 与真实 CLI

- 最终代码提交：`d4bf7eae033905bb37332a9c1629fa34b5fbadb2`。
- tree：`4a35ebf48454a24d40aa02ee56dea590932cd8a6`。
- wheel：`agent-2.1.0-py3-none-any.whl`，490,981 bytes，SHA-256
  `1fcf81e81a4c396a5301843d11095ee7d1faaac8fa759f4f0dfc5e7834d0213c`；`cli.py`、
  `core/memory.py` 与 14 个 React runtime 文件的路径和内容均与源码逐字节一致。
- wheel import 路径确认来自隔离 `wheel-site`，不是仓库源码；真实 CLI 完成
  run → review → reject，以及 run → accept → revise → history → stale revise 非零失败 → delete。
  删除后 `review` 与 `list` 均为空，history 保留 candidate、source run、supersedes 与 tombstone。
- 现有 workspace 的 180 条旧 candidate 记录只读加载成功；测试 fixture 同时验证旧 accepted entry
  可无迁移 revise。

## 验收中发现并修复

1. 首个 wheel 实测发现 `revise`/`delete` 的双 UUID 成功信息被 Rich 按 80 列折行；改为直接写入
   单行文本并增加回归断言。旧 wheel 证据作废并清理，修复提交后重新执行全量、wheel 与真实 CLI。

## 清理与状态

- 两轮 `D:\CodexScratch\agent-phase3b-*` detached worktree、wheel、pip cache、pytest temp、
  wheel-site 与真实 CLI workspace 已按已验证的绝对路径删除；Git worktree 只剩主工作树。
- 两份用户原有的未跟踪 handoff 文档未修改、未暂存；没有 push、Ready 或 merge。
- 未新增依赖、数据库、embedding、Web mutation API 或自动 Memory mutation。

## 完成门

- [x] 旧 JSONL 与既有 CLI 兼容
- [x] candidate accept/reject 单终态且并发安全
- [x] revise/delete 只作用于 current active 叶节点，history 可审计
- [x] list/retrieve/模型上下文/Workbench 只展示当前 active 叶节点
- [x] 畸形、超限、link/reparse 与原子发布失败安全
- [x] 目标、全量、真实 CLI、wheel 与提交后复验通过
- [x] D 盘 temp/worktree/lock owner/process 清理通过

下一切片是 3C Automation；本记录不构成 Phase 3 或 Project vNext 核心完成声明。
