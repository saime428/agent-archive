# Workbench 流式输出与输入区精简实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Web 聊天流式渲染(thinking/content/args 分片打标直达浏览器);输入区 chip 精简为联网/电脑文件/原生工具三个可点开关 + 工作过程显示开关;最大化窗口布局修正。

**Architecture:** `_ToolCallAssembler` 增 reasoning_content 并改为 yield `(kind, text)`;`loop._model_response` 解包并把 kind/text 放进 `model_stream_chunk` 事件;`_run_chat_job` 传 no-op `stream_handler` 激活流式,事件经现有 SSE 通道到前端;`sse.js` 订阅新事件,`chat.js` 按 kind 渲染;`_validated_config_updates` 白名单加 `native_tools`;chip 单键 POST `/api/config`。

**Spec:** `docs/superpowers/specs/2026-07-11-workbench-streaming-ui-design.md`

## Global Constraints

- CLI 行为契约不变:`stream_handler` 仍接收 `str`;JSON 协议 `chat`/`stream_chat`、repair、审批、错误恢复零改动。
- `stream_chat_tools` 的 return 信封逐字不变;reasoning 文本只 yield 不进信封。
- 既有测试中仅允许改动:流式用例的 chunk 解包方式(str → tuple);其余用例不改仍绿。
- 前端不引入新依赖、不加构建步骤;localStorage 仅用于"工作过程"显示开关。
- 验证协议:沙箱 `python3 -m py_compile` + 静态审查(沙箱不可用时在用户机器跑);pytest 在用户机器统一门禁;前端手工冒烟在用户门禁。
- git 纪律同前:`-c core.autocrlf=input`;只 stage 任务列出的文件;提交前 `git show :<path>` 提取暂存 blob 验证(py 文件编译、js/css/html 抽查行数与尾行),不符即 BLOCK——本仓库挂载曾多次损坏提交。

---

### Task 1: 流式分片打标(openai_compat)

**Files:**
- Modify: `src/agent/llm/openai_compat.py`
- Test: `tests/test_openai_compat.py`

**改动:**

1. `_ToolCallAssembler` 增加字段 `self.thinking_parts: list[str] = []`(仅计数用途可省;保留供调试)。`feed(delta)` 返回类型改为 `list[tuple[str, str]]`:
   - `delta.reasoning_content` 为非空 str → append `("thinking", text)`(不进 `content_parts`)。
   - `delta.content` 为非空 str → `content_parts` 照旧累加,append `("content", text)`。
   - tool_calls 参数分片照旧累加 `argument_parts`,append `("args", text)`。
   - 返回 pieces 列表(可能为空)。
2. `_tool_stream_piece` 返回类型改为 `list[tuple[str, str]] | type[_StreamDone] | None`;`_assemble_tool_stream` 对返回列表逐个 `yield piece`。
3. `stream_chat_tools` 签名注释/类型改为 `Generator[tuple[str, str], None, dict | str]`。`envelope()` 不变。

**测试:**

- 现有 4 个 stream 用例:`_drive` 收集到的是 tuple,断言改为 `"".join(text for _kind, text in chunks)`;`test_stream_chat_tools_assembles_fragmented_tool_call` 增加断言:content 分片 kind 为 `"content"`、arguments 分片 kind 为 `"args"`。
- 新增:

```python
def test_stream_chat_tools_yields_reasoning_as_thinking() -> None:
    events = [
        '{"choices": [{"delta": {"reasoning_content": "let me think"}}]}',
        '{"choices": [{"delta": {"content": "ok"}}]}',
    ]
    client = OpenAICompatClient(
        api_key="", model="m", base_url="http://localhost:11434/v1",
        stream_transport=lambda url, headers, body, timeout: iter(_sse(events)),
    )

    chunks, envelope = _drive(client.stream_chat_tools([{"role": "user", "content": "hi"}], TOOLS))

    assert ("thinking", "let me think") in chunks
    assert envelope == {"message": "ok"}  # thinking 不进信封
```

- [ ] Step 1: 改测试(先红)
- [ ] Step 2: 实现
- [ ] Step 3: py_compile 验证 + 暂存 blob 验证后提交
  `git -c core.autocrlf=input commit -m "feat: tag streaming chunks with thinking/content/args kinds"`

---

### Task 2: 循环透传 kind/text(loop.py)

**Files:**
- Modify: `src/agent/core/loop.py`
- Test: `tests/core/test_loop_native.py`(末尾追加)

**改动:** `_model_response` native 分支循环体:

```python
            except StopIteration as stop:
                return stop.value if stop.value is not None else ""
            kind, text = chunk if isinstance(chunk, tuple) else ("content", str(chunk))
            stream_handler(text)
            _emit_event(event_handler, "model_stream_chunk", {"kind": kind, "text": text, "chunk_chars": len(text)})
```

JSON 协议分支的 `model_stream_chunk` 负载同步改为 `{"kind": "content", "text": text, "chunk_chars": len(text)}`。

**测试(追加):** 脚本化客户端加 `stream_chat_tools`(yield `("thinking", "t1")`、`("args", '{"final"...')` 后 return done 信封),`run_once` 传收集用 `event_handler` 与 no-op `stream_handler`,断言事件序列含 `model_stream_chunk` 且 kind/text 正确、run 正常 done。

- [ ] Step 1: 写失败测试
- [ ] Step 2: 实现
- [ ] Step 3: py_compile + 暂存 blob 验证后提交
  `git -c core.autocrlf=input commit -m "feat: carry chunk kind and text in model_stream_chunk events"`

---

### Task 3: Web 后端接流 + native_tools 可写

**Files:**
- Modify: `src/agent/web/server.py`
- Test: `tests/test_web.py`(末尾追加)

**改动:**

1. `_run_chat_job` 的 `run_turn` 调用加 `stream_handler=lambda _text: None`。
2. `_validated_config_updates` 的 `allowed` 集合加 `"native_tools"`,分支校验与 `dry_run` 同模式(非 bool → `ValueError("native_tools must be a boolean.")`)。

**测试(追加):**

- `build_save_config_payload` 接受 `{"native_tools": true}` 并落盘(读回 config.toml 断言);拒绝 `{"native_tools": "yes"}`。
- chat job 事件含流式分片:按 test_web.py 现有 chat job 测试的构造方式,注入带 `stream_chat_tools` 的 fake 客户端(monkeypatch `make_llm`),跑一轮后断言 `job.events` 含 `event == "model_stream_chunk"` 且带 `text`。

- [ ] Step 1: 写失败测试
- [ ] Step 2: 实现
- [ ] Step 3: py_compile + 暂存 blob 验证后提交
  `git -c core.autocrlf=input commit -m "feat: stream chat chunks over SSE and allow native_tools writes"`

---

### Task 4: 前端流式渲染

**Files:**
- Modify: `src/agent/web/static/assets/sse.js`、`src/agent/web/static/assets/render/chat.js`

**改动:**

1. `sse.js` `CHAT_EVENT_NAMES` 增加 `"model_stream_chunk"`。
2. `chat.js` `handleLiveChatEvent(payload)` 增加分支:
   - `payload.event === "model_stream_chunk"`:
     - `kind === "content"` → 追加到 `state.liveTurn.streamText`(新字段),live 气泡正文显示 `streamText || "正在运行..."`。
     - `kind === "thinking"` / `"args"` → 追加到 `state.liveTurn.thinking_text`,更新工作过程折叠区(`.thinking-copy` 直接 textContent 追加,不走 typewriter,避免每分片重排)。
   - `final` 到达:现状逻辑不变(最终文本替换正文);`streamText` 清空。
3. 更新频率控制:分片追加只做 textContent += 与滚动跟随,不重建 DOM 节点。

**验证:** 无前端自动化测试;`node --check`(如无 node 则静态审查)+ 用户门禁手工冒烟。

- [ ] Step 1: 实现
- [ ] Step 2: 暂存 blob 验证(js 文件 tail 比对)后提交
  `git -c core.autocrlf=input commit -m "feat: render streamed thinking and content chunks in workbench chat"`

---

### Task 5: 输入区 chip 精简与可点开关

**Files:**
- Modify: `src/agent/web/static/index.html`、`src/agent/web/static/assets/state.js`、`src/agent/web/static/assets/render/chat.js`、`src/agent/web/static/assets/render/health.js`、`src/agent/web/static/assets/app.css`

**改动:**

1. `index.html` `.input-actions` 重构为:

```html
<button id="web-search-toggle" class="chip-toggle" type="button">联网：关</button>
<button id="computer-read-toggle" class="chip-toggle" type="button">电脑文件：关</button>
<button id="native-tools-toggle" class="chip-toggle" type="button">原生工具：关</button>
<button id="thinking-toggle" class="chip-toggle" type="button" aria-pressed="true">工作过程</button>
<button id="send-button" class="send-button" type="submit" aria-label="发送">→</button>
```

   移除 provider-chip、api-key-chip、mode-chip、sandbox-chip、审批 pill。
2. `state.js`:els 中删除 `provider`/`apiKey`(原 api-key-chip)/`webSearch`/`computerRead`/`modeChip`/`sandboxChip` 五项,新增四个 toggle 引用。**清理引用清单**:grep `els.provider`、`els.apiKey`、`els.webSearch`、`els.computerRead`、`els.modeChip`、`els.sandboxChip` 在 `health.js`/`chat.js`/`app.js` 的所有出现点,渲染类引用删除或改指设置面板元素;遗漏一处就是运行时 TypeError,此步必须逐个确认。
3. `chat.js` 事件绑定:三个配置 toggle 各绑 click → `toggleConfigKey(key, button)`(新函数,放 `health.js`):

```javascript
export async function toggleConfigKey(key, button) {
  const current = Boolean(state.config?.config?.[key]);
  button.disabled = true;
  try {
    state.config = await postJson("/api/config", { [key]: !current });
    renderChipToggles();
  } catch (error) {
    els.settingsStatus.textContent = error instanceof Error ? error.message : String(error);
  } finally {
    button.disabled = false;
  }
}
```

   (`state.config` 的实际形状以 `/api/config` 响应为准,实现时核对取值路径。)`renderChipToggles()` 按配置真值刷新三个按钮文案与 `.on` 类;在 `refreshWorkbench` 渲染链路中调用。
   `thinking-toggle`:切换 `document.body.dataset.showThinking`,localStorage 持久化,CSS 控制工作过程区显隐。
4. `health.js`:设置面板补 `native_tools` checkbox(index.html settings 区 + `buildSettingsPayload` + change 监听,与 web_search 同模式),两处入口(chip 与设置面板)共用 `/api/config`。
5. `app.css`:`.chip-toggle` 样式(默认 muted,`.on` 高亮,hover 指针),沿用 status-pill 视觉基调。

**验证:** 静态审查 + 用户门禁手工冒烟(点击三个开关后 `.agent/config.toml` 落盘、刷新后状态一致、无控制台报错)。

- [ ] Step 1: index.html + state.js + 引用清理
- [ ] Step 2: toggle 逻辑 + 渲染 + 样式
- [ ] Step 3: 暂存 blob 验证后提交
  `git -c core.autocrlf=input commit -m "feat: replace status chips with interactive config toggles"`

---

### Task 6: 布局修正

**Files:**
- Modify: `src/agent/web/static/assets/app.css`

**改动:**

1. `.chat-thread`:`padding-inline: max(clamp(20px, 5vw, 40px), calc((100% - 760px) / 2));`,删除 `.chat-thread > *` 的 `max-width: 760px; margin-inline: auto`(列宽由父级内边距约束,子元素 `width: 100%`)。
2. `.message-bubble.user`:`margin-inline: auto 0;`(替换现有 `margin-inline: 0 auto`——正是"用户消息贴最左"的根源),`max-width: min(560px, 82%)` 保留。
3. `.input-dock` 所在容器同轴:输入区外层加相同 `padding-inline` 规则或 `max-width: 760px; margin-inline: auto`,与消息列对齐(以现有 DOM 结构取改动最小者)。
4. 检查响应式断点(1808/1838 行附近)与新规则不冲突。

**验证:** 用户门禁手工冒烟:窗口最大化/半屏/窄窗,用户消息右对齐、agent 左对齐、输入框与消息列同轴。

- [ ] Step 1: 实现
- [ ] Step 2: 暂存 blob 验证后提交
  `git -c core.autocrlf=input commit -m "fix: align chat column and right-align user messages"`

---

### Task 7: 文档与用户门禁

**Files:**
- Modify: `CHANGELOG.md`、`README.md`

- [ ] Step 1: CHANGELOG `## Unreleased` 追加:

```markdown
- Workbench 流式输出:模型思考/正文/工具参数分片实时渲染;输入区精简为联网/电脑文件/原生工具三个可点开关与工作过程显示开关;修正最大化窗口下消息列对齐。
```

- [ ] Step 2: README workbench 小节同步(流式说明 + 开关说明,替换过时的 chip 描述)。
- [ ] Step 3: 暂存 blob 验证后提交
  `git -c core.autocrlf=input commit -m "docs: document workbench streaming and input toggles"`

- [ ] Step 4: 用户门禁(用户机器执行)

```
python -m pytest -q
python -m agent.cli doctor
启动 workbench(现有一键启动脚本),真实对话冒烟:
  1. 发一条需要工具的消息 → 工作过程区实时出现思考/参数分片,最终回答正常;
  2. 依次点击联网/电脑文件/原生工具开关 → .agent/config.toml 对应键变化,刷新页面状态一致;
  3. 工作过程开关可收起/展开,刷新后记忆保持;
  4. 窗口最大化 → 用户消息右对齐、agent 回复同列左对齐、输入框同轴;
  5. 浏览器控制台无报错。
```

Expected: pytest 全绿;五项手工冒烟全过。任何一项不过,回到对应任务修复后重跑。
