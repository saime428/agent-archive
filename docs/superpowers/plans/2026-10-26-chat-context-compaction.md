# 对话上下文压缩（参考 Mirror）

## 背景

多轮对话里，每轮是一次独立的 `run_once`，轮与轮之间只靠 `ConversationState.build_context_message`（`src/agent/core/chat.py:165`）带历史：取最近 10 轮的简要记录，拼好后用 `truncate_text` 截到 8000 字符。两个问题：

1. 第 11 轮以前的对话直接丢掉，没有任何摘要。
2. `truncate_text`（`src/agent/core/budget.py:38`）保留开头，历史超长时被截掉的是**最新**几轮。

单次 run 内部不需要压缩：迭代上限按模式固定（最多 10），每条观察已截到 20k，上下文有上界。

Mirror 的做法（`mirror-agent/src/compaction/compactor.rs`）：快超预算时，把「上次摘要 + 较早消息」用一次独立的无工具调用交给模型，生成结构化检查点摘要；最近消息原样保留，切点只落在用户消息处；摘要输入超长时保留尾部；摘要失败不替换原上下文；下次压缩把旧摘要一并带上。

## 方案

只改对话层。命令行和网页端都走 `ChatSession.run_turn`，改一处两边都生效。下文 B = `conversation_context_chars`。

1. **预算**（`src/agent/core/budget.py`）
   - `conversation_context_chars`：8000 → **16000**（已确认）。它同时是 `@文件` 引用的上限（`chat.py:310`），引用上限随之从 8000 涨到 16000。
   - 删掉 `conversation_max_turns`：改为只按字符数触发，10 轮短问答不该为凑轮数去调一次模型。同步改 `tests/test_budget.py:23`。
   - 新增 `compaction_input_chars = 40_000`：摘要请求里「被折叠轮次」部分的上限。
   - 其余比例不加旋钮：摘要上限 = B/4，压缩后保留的最近原文目标 = B/4，渲染时单轮的用户原话和最终回答各截到 B/4。

2. **状态**（`ConversationState`）
   - 新增 `summary: str = ""` 和 `summarized_turns: int = 0`，表示 `turns[:summarized_turns]` 已折进摘要。`turns` 一条不删，界面历史和 `/transcript` 不变。
   - `save` 写入这两项。`load` 宽松解析，和现有 `title` 的做法一致：`summary` 不是字符串就当空串，`summarized_turns` 不是整数就当 0，越界就夹到 `0..len(turns)`。这两项都能重新生成，不该因为它们导致整个会话加载失败、从 `list()` 里消失。

3. **共用渲染**：抽出 `_render_turn`，单轮的用户原话和最终回答各截到 B/4。上下文构建和压缩输入共用它，避免一条超长回答把整段历史挤掉。

4. **`build_context_message`**
   - 固定表头（保持现有两行在最前）→ 摘要一节（如有，标明是模型生成的较早对话摘要，仍在 UNTRUSTED 块内）→ 「Recent turns」。
   - 从最新一轮往前放，放不下就停，**最新一轮总是放**，修掉「截掉最新」的问题。
   - `truncate_text(..., B)` 留作最后兜底。

5. **`ChatSession._compact_if_needed(event_handler, control)`**，在 `run_turn` 开头调用
   - 触发：渲染全部未折叠轮次 + 摘要后超过 B，也就是有轮次会被丢掉。
   - 切点：从最新往前累加，保留能放进 B/4 的轮次，至少保留最新一轮。没有可折叠的轮次就跳过。
   - 输入：旧摘要原样放在前面，后接被折叠轮次的渲染文本；只对后半截按 `compaction_input_chars` 保留尾部，旧摘要不会被截掉。
   - 调用前：`control` 已停止就跳过。
   - 调用：一次 `llm.chat([system, user])`。提示词沿用 Mirror 的检查点格式，节顺序调成「目标 → 下一步 → 关键上下文 → 约束与偏好 → 进度 → 关键决定」，被截断时先丢次要的。另要求用对话原语言写、控制在 B/4 字符内，超出按 B/4 硬截。
   - 失败处理：返回 dict、空串或抛 `Exception` 时状态不变，照常跑这一轮。抛 `KeyboardInterrupt` 时，有 `control` 就 `request_cancel()` 后返回（`run_once` 会记成「取消」，命令行不会退出），没有 `control` 就照原样抛出，和 `loop.py:235` 一致。
   - 成功后：更新 `summary` 和 `summarized_turns`。不额外保存，`run_turn` 末尾和网页端异常路径本来就会保存同一个 state 对象。
   - 事件：通过 `event_handler` 发 `{"event": "context_compaction", "status": "ok", "summarized_turns": n}`，失败时发 `{"status": "failed", "error_type": ...}`。

6. **FakeLLM**（`src/agent/llm/fake.py`）：认出摘要请求（首条 system 消息是压缩提示词），返回固定摘要文本，**不消耗**脚本化动作队列。这样离线演示和长对话测试不会每轮报压缩失败，也不会错位吃掉下一个脚本动作。

7. **命令行**（`src/agent/cli.py`）：`_chat_event_handler` 在成功和失败时各打印一行；`/status` 增加 `compacted_turns`。

8. **网页端**：不改前端。`parseChatEvent` 会忽略不认识的事件名，事件只留在 job 事件日志里。

## 不做（以后需要再加）

- 手动 `/compact` 命令。
- 前端展示压缩状态。
- 单次 run 内部压缩（目前有上界）。
- 按真实 token 用量触发（项目里预算都按字符计）。

## 改动文件

- `src/agent/core/budget.py`、`src/agent/core/chat.py`、`src/agent/llm/fake.py`、`src/agent/cli.py`
- `tests/test_chat.py`、`tests/test_budget.py`
- `README.md`、`CHANGELOG.md`（Unreleased）
- `docs/superpowers/plans/2026-10-26-chat-context-compaction.md`：本方案的仓库内副本

## 验证

- 新测试（`tests/test_chat.py`）：
  - 超出预算时触发压缩，旧轮次折进摘要，下一轮上下文里有摘要和最近原文，最新一轮总在。
  - 第二次压缩的输入以上次摘要开头；被折叠部分超长时旧摘要仍完整。
  - 摘要调用返回 dict 或抛异常时，状态不变，这一轮照常完成，发出 `failed` 事件。
  - 摘要调用里抛 `KeyboardInterrupt`（带 `control`）时，这一轮记为 cancelled，不向外抛。
  - FakeLLM 带脚本动作时，压缩不吃掉动作。
  - 未压缩但超预算时，保留最新几轮、丢最旧的。
  - `save`/`load` 往返保留新字段；旧文件可加载；非法值被夹回合法范围。
- 全量：miniconda 3.13 的 `python -m pytest`、`ruff check`。
- 手动：用 FakeLLM 在临时目录跑 `agent chat` 若干长轮次，看提示行和 `/status`。
- 收尾：独立代码审查一遍；提交到本地 `main`，不推送。
