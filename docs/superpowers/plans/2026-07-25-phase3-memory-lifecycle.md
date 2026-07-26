# Phase 3B Memory 生命周期实施计划

- 日期：2026-07-25
- 状态：计划已审查；待实施
- 设计：[Phase 3B Memory 生命周期](../specs/2026-07-25-phase3-memory-lifecycle-design.md)

## 固定边界

- 只修改 Memory core、CLI、其直接只读消费者契约、测试与文档。
- 不新增依赖、数据库、embedding、Web 写接口或自动 mutation。
- 继续使用 `.agent/memory/candidates.jsonl`、`entries.jsonl` 和旧记录兼容格式。
- 所有临时目录、并发 helper 与 wheel 放在 `D:\CodexScratch`；不触碰两份未跟踪 handoff。

## Task 1：锁定文档与完成边界

新增 spec、plan、verification 骨架和 `tests/test_docs.py` 契约；先声明实施中，继续保留
“Project vNext 核心仍未完成”和“Phase 4–5 需求触发”。

## Task 2：状态计算与失败测试

扩展 `tests/test_memory.py`，先覆盖：

- 旧记录兼容、accepted 状态推导、删除后 list 不返回旧 active；
- reject 与重复 accept/reject；
- revise 链、history、当前叶检索、历史节点禁止分叉、重复 delete；
- 两个 store 并发 accept/reject 只有一个成功；
- 畸形/超限/link store 拒绝，原子发布失败保留旧文件。

红灯必须证明真实缺口，不 monkeypatch 私有返回值绕过文件系统。

## Task 3：最小 MemoryStore 实现

复用 `_user_store` 的 OS lock、plain-file/reparse 校验与 atomic replace；不复制第二套锁或事务框架。
accept 用 entry 的 `candidate_id` 作为单文件 commit；reject 改 candidate 文件；revise/delete 改 entry 文件。

current active leaf 与 history 由一个共享 helper 计算；`list_entries()`、`retrieve()`、mutation precondition
全部走这一个权威结果，避免各调用者分别补丁。

## Task 4：CLI 与只读消费者

新增 reject/revise/delete/history，undo 复用 delete helper。更新 CLI 测试、README、CHANGELOG；
Workbench 不增加 mutation API，只验证 pending/active count 与叶节点 payload 正确。

## Task 5：全量与真实路径

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_memory.py tests/test_cli.py tests/test_web.py -q --basetemp <D唯一目录>\target
.\.venv\Scripts\python.exe -m pytest -q --basetemp <D唯一目录>\all
.\.venv\Scripts\agent.exe release doctor --cwd .
git diff --check
```

在 D 盘真实 workspace 用 CLI 完成 add fixture → review → reject，以及 add → accept → revise → history →
retrieve → delete；确认 JSONL、模型 memory message 与 Workbench health 只展示当前叶节点。

## Task 6：提交后复验

按 core/tests、CLI/docs、verification 拆分精确提交。从最终代码提交创建 D 盘 detached worktree，重跑
目标/全量/真实 CLI/wheel 字节检查；清理 worktree/temp 后，verification 记录 commit/tree/测试证据并作
文档状态提交。

## 完成门

- candidate/entry mutation 并发安全且文件原子；旧数据兼容；
- accept/reject、revise/delete、history 与 retrieve 当前叶闭环全部通过；
- 不出现历史分叉、重复 tombstone、已删除 entry 注入或 Web 隐式写；
- 全量、真实 CLI、wheel、提交后复验和清理通过；
- 只声明 3B 完成，下一步为 3C Automation。
