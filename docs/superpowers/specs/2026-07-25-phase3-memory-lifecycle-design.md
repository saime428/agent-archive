# 设计：Phase 3B Memory 生命周期

- 日期：2026-07-25
- 状态：设计已审查；待实施
- 上位方向：[Phase 3 方向分析与审查](../../project-vnext-phase3-direction-review.md)

## 目标

把已有 candidate → accept → retrieve → undo 补成可并发、可审计的本地 Memory 生命周期：
candidate 可 reject，active entry 可 revise/delete，检索只注入当前 active 叶节点，来源与完整修订链
可追踪。

本切片完成后只允许声明“3B Memory 完成”；Phase 3、Frontend vNext 和 Project vNext 核心仍未完成。

## 实施前基线

- `MemoryStore` 使用 `.agent/memory/candidates.jsonl` 与 `entries.jsonl`，写入没有进程锁；append 与
  `Path.write_text()` 可能竞争或留下截断文件。
- accept 先 append entry，再重写 candidate，两个文件没有共同恢复语义；同一 pending candidate
  可以被重复 accept。
- undo 只检查历史中存在 active record；重复 undo 仍会追加 tombstone，`list_entries()` 也没有
  排除已被 supersede 的旧 active entry。
- entry 已有 `supersedes`，但没有 revise、reject、history 命令，也没有 candidate 到 entry 的审计链接。
- Workbench Memory Review 是只读消费者；模型上下文由 `retrieve()` 注入。

## 固定语义

### 存储与并发

- 保留现有两个 JSONL 路径与旧记录兼容，不建数据库、不建通用 repository、不迁移 Workbench schema。
- 复用 `agent._user_store.store_lock` 与 `atomic_replace_bytes`。每个 mutation 在同一 Memory root 的
  OS 文件锁内重新读取权威状态，再原子替换一个日志文件。
- accept 只向 entry 日志原子追加带 `candidate_id` 的 active entry；candidate 的 accepted 状态由
  entry 链推导。这样一次 accept 只有一个权威文件发布，不需要跨文件事务。
- add/reject 只替换 candidate 日志；revise/delete 只替换 entry 日志。锁内再次校验 current state，
  保证竞争 accept/reject、revise/delete 只有一个成功。
- ID 改用带既有 `cand_` / `mem_` 前缀的 UUID，避免并发时间戳碰撞；旧时间戳 ID 继续可读。

### 状态与链

- candidate 状态只有 pending、accepted、rejected。只有 pending 可 accept 或 reject；重复与冲突操作
  明确非零失败，不静默生成第二条记录。
- active entry 是没有被任何后继 supersede 的 active 叶节点。revise 创建新的 active entry，
  `supersedes=<old entry id>`，保留原始 `source_run_id`；delete 创建 deleted tombstone 并 supersede
  当前叶节点。
- revise/delete 只接受 current active 叶节点，禁止从历史节点分叉。旧 entry 与 tombstone 永久保留，
  history 从原始 entry 到当前 active/deleted 终点按顺序返回。
- `list_entries()`、Workbench active count 与 `retrieve()` 只看 current active 叶节点；
  `include_deleted=True` 保持返回完整兼容日志。

### 边界与安全

- candidate/revision 内容先经过既有 redaction；空内容、超限内容、非法/未知 ID、未知状态、畸形 JSON、
  非普通文件、link/reparse root 或超限 store 明确报 `MemoryError`。
- Memory 继续作为 untrusted user context，不能覆盖系统、policy、sandbox、approval、redaction 或 Tool schema。
- 不改变 `memory_auto_write`；不做自动 accept/revise/delete，不给 Workbench 增加写接口。

## CLI

保留 `review/list/accept/undo`，新增：

```text
agent memory reject <candidate-id>
agent memory revise <entry-id> <replacement>
agent memory delete <entry-id>
agent memory history <entry-id>
```

`undo` 继续作为 `delete` 的兼容入口。所有 mutation 失败返回非零；输出只显示 ID、状态、来源与已脱敏正文。

## 验收

- 旧 JSONL 无迁移可读；accept/reject 竞争只有一个成功且文件保持合法。
- revise → retrieve 只返回新叶节点；delete 后 list/retrieve 均不返回旧节点；重复/历史节点 mutation 被拒绝。
- history 保留 candidate、source run、supersedes 与 tombstone；摘要/模型上下文只含当前叶节点。
- CLI 新旧命令、Workbench 只读 health、全量 Python、真实 CLI、wheel 路径/字节和 D 盘 detached
  worktree 通过；临时文件、锁 owner 与进程无残留。

## 非目标

- 语义向量检索、embedding、跨 workspace/global memory、自动冲突合并、远程同步、Memory Web 写 UI。
- Automation、eval、Editor/Search、Git、Terminal、Command/Layout 或 legacy retirement。
