# Agent 长期路线图：v2.1 → v3.0

最后更新：2026-07-08

## 背景

v0.1 → v2.0 阶段已 100% 完成。经过全项目代码审计（后端 ~5,400 行、前端 ~3,600 行、测试 ~290 用例），识别出三个优先重心：

1. **安全硬化** — 堵住 CRITICAL 缺口
2. **接线已有扩展点** — 多个能力骨架已定义但未生效
3. **重构与工程质量** — 消除重复、拆分大文件、前端模块化

路线图按优先级排序：先堵安全缺口，再接能力，后重构。

---

## Phase 1 — 安全硬化（v2.1）🔴 最高优先

### 1.1 堵住 secrets 写保护缺口 [CRITICAL]

`sandbox.py` 保护了**读** `.agent/secrets.env`，但**没保护写**——攻击者可通过 `write_file("../../.agent/secrets.env", ...)` 覆盖密钥文件。

- 文件：[src/agent/policy/sandbox.py](src/agent/policy/sandbox.py)
- 改动：`_has_protected_write_part` 增加 `.agent/secrets.env` 和整个 `.agent/` 目录（`.agent/runs/` 已保护除外）
- 测试：新增 `test_sandbox.py` 密钥写保护用例

### 1.2 修 Workbench XSS 向量 [HIGH]

`app.js` 有 15 处 `innerHTML` 直接拼接服务端响应数据（聊天标题、运行记录、文件列表等）。虽然当前数据来自本地受信端点，但未来若接入公网或注入恶意数据则暴露 XSS。

- 文件：[src/agent/web/static/assets/app.js](src/agent/web/static/assets/app.js)
- 改动：新增 `escapeHtml()` 工具函数，对 `innerHTML` 路径做转义；`messageBody` 已走 Markdown 渲染的保持、纯文本统一用 `textContent`
- 测试：`test_ui.py` 新增 XSS 转义断言

### 1.3 修 SSE 聊天任务内存泄漏 [MEDIUM]

`_CHAT_JOBS` 字典的条目在聊天完成后永不删除，包含完整的事件列表。长时间运行会导致内存持续增长。

- 文件：[src/agent/web/server.py](src/agent/web/server.py)
- 改动：加 TTL（例如 5 分钟），job 完成后在 SSE 连接关闭时标记，由 `build_chat_events_payload` 检查并清理
- 测试：新增 task 清理行为测试

### 1.4 手写 TOML 序列化器加固 [LOW]

`_dump_toml` 不处理转义、内联表、带引号的键。写入非平凡配置时会丢数据。

- 文件：[src/agent/web/server.py](src/agent/web/server.py)
- 改动：加 TOML 字符串转义逻辑，或限制写入字段类型为已知安全的简单值
- 无需单独测试：已有 `test_ui.py` 配置写入测试覆盖

### 1.5 TOCTOU 加固 [LOW]

Windows 上 `_is_within` 不解析 junction/symlink，存在 TOCTOU 竞态窗口。

- 文件：[src/agent/policy/sandbox.py](src/agent/policy/sandbox.py)
- 改动：文档标注已知限制；写入路径在写之后做二次 `_is_within` 校验
- 测试：无（平台限制，文档化即可）

### v2.1 验收

```powershell
python -m pytest tests/test_sandbox.py tests/test_ui.py tests/test_web.py -q
python -m pytest -q
git diff --check
```

---

## Phase 2 — 接线 sandbox 模式（v2.2）🔴

### 2.1 激活三种 sandbox 模式

`config.sandbox` 定义了 `read-only` / `workspace-write` / `danger-full-access` 但核心循环从未读取。这是"设计了没接线"的最大项。

| 模式 | 行为 |
|---|---|
| `read-only` | 拒绝所有 `CONFIRMATION_REQUIRED_ACTIONS`（写/patch/命令/Markdown 报告），允许只读工具 |
| `workspace-write` | 当前行为（默认），工作区内可读写 |
| `danger-full-access` | 工作区内读写 + 允许绝对路径写入（需显式确认，项目配置不可设置） |

- 文件：[src/agent/core/loop.py](src/agent/core/loop.py)、[src/agent/policy/sandbox.py](src/agent/policy/sandbox.py)
- 接线点：`_tool_observation` 中读 `config.sandbox`，与 `classify_action` 协同决策
- 防护：项目 `.agent/config.toml` 不可将 sandbox 从 `workspace-write` 升级到 `danger-full-access`（与 approval=never 保护同模式）

### 2.2 Workbench 显示 sandbox 模式

状态栏已有 mode chip，加一个 sandbox chip 复用同一模式。

- 文件：[src/agent/web/static/index.html](src/agent/web/static/index.html)、[app.js](src/agent/web/static/assets/app.js)

### 2.3 Workbench 显示 sandbox 模式

状态栏已有 mode chip，复用同一模式。

- 文件：[index.html](src/agent/web/static/index.html)、[app.js](src/agent/web/static/assets/app.js)
- `/api/health` 已有 `sandbox` 字段（"mode": "read-only" 出现在多个 payload builder 中），直接暴露到前端

### v2.2 验收

```powershell
python -m pytest tests/test_loop.py tests/test_sandbox.py tests/test_config.py -q
python -m pytest -q
```

---

## Phase 3 — 接线其余扩展点（v2.3）🟡

### 3.1 接线 `memory_auto_write`

选项定义了但循环无条件写候选。关闭时不写，减少磁盘噪音。

- 文件：[src/agent/core/loop.py](src/agent/core/loop.py)
- 改动：`_write_memory_candidate` 前读 `config.memory_auto_write`

### 3.2 接线技能 `allowed_tools`

技能声明了需要哪些工具，但从不强制执行。运行循环应校验 action 是否在选中技能的 allowed_tools 集合内。

- 文件：[src/agent/core/loop.py](src/agent/core/loop.py)
- 改动：`_tool_observation` 中增加白名单检查；空 allowed_tools = 所有工具可用（向后兼容）

### 3.3 实现实用 hooks

当前只有空 `audit` 和测试用 `fail`。实现两个真正有用的 hook：

- `audit`：写审计行到 `hooks.jsonl`（当前已是空操作，改成真的记录）
- `before_tool_format`：在 PostToolUse 类 hook 触发格式化，与 PCC hooks 规则对齐

不引入新文件，在已有 `hooks.py` 的 `BUILTIN_HOOKS` 注册表中扩展。

### v2.3 验收

```powershell
python -m pytest tests/test_loop.py tests/test_skills.py tests/test_hooks.py tests/test_memory.py -q
python -m pytest -q
```

---

## Phase 4 — 提供者可扩展性（v2.4）🟡

### 4.1 提供者注册表模式

当前工厂是硬编码 `if/else`。改为基于注册表的模式：

```python
PROVIDER_REGISTRY: dict[str, Callable[[AgentConfig], LLMClient]] = {
    "fake": lambda _: FakeLLMClient(),
    "deepseek": lambda cfg: DeepSeekClient(api_key=_deepseek_key(cfg), model=cfg.model),
}
```

- 文件：[src/agent/llm/factory.py](src/agent/llm/factory.py)
- 好处：加新 provider 只需注册，不碰 config 外的代码；为 Claude/OpenAI 留接口

### 4.2 加自动重试 + 指数退避

当前 429/网络瞬时错误直接传播到调用方。加一个薄重试层。

- 文件：[src/agent/llm/deepseek.py](src/agent/llm/deepseek.py)
- 策略：429/5xx 最多 3 次，退避 1s/2s/4s；连接错误同样退避

### 4.3 加连接复用

`urllib` 每次新连接。改为利用 HTTP keep-alive 或 pool。

- 文件：[src/agent/llm/deepseek.py](src/agent/llm/deepseek.py)

### v2.4 验收

```powershell
python -m pytest tests/test_deepseek.py -q
python -m pytest -q
```

---

## Phase 5 — 后端重构（v2.5）🟢

### 5.1 loop.py 拆分

当前 1250 行。提取：

- `core/summary.py` — `_render_summary` + 所有 `_*_lines` 格式化函数
- 消除 `_format_action_id` 重复（`actions.py` + `loop.py` 各有一份）
- 消除 `_restore_hints_by_path` 重复（`loop.py` + `run_store.py`）
- 消除 `DRY_RUN_SKIPPED_ACTIONS` / `DRY_RUN_SKIPPED_TOOLS` 重复
- 三条提前返回路径抽共享 `_finalize_run()` helper

### 5.2 config.py 去重

合并 `_validate_value` 和 `_validate_override`（200+ 行几乎相同）。

### 5.3 工具层一致性修复

- `apply_patch` "first" 语义：替换首个出现而非要求精确 1 次匹配
- `sandbox.py` `PROTECTED_WRITE_PARTS` 补 `.svn`/`.hg`/`node_modules`/`.env`

### 5.4 文档工具可选依赖

为缺失 `pypdf`/`python-docx`/`openpyxl`/`python-pptx` 提供更友好的错误消息，而非裸 OSError。

### v2.5 验收：纯重构

```powershell
python -m pytest -q  # 全量通过 = 行为不变
python -m agent.cli release doctor --cwd .
```

---

## Phase 6 — 前端模块化（v3.0）🟢

### 6.1 JS 拆分为 ES 模块

当前 `app.js` 1785 行单文件，78 个函数，全局可变 state。

拆分结构（零构建，HTML 用 `<script type="module">`）：

```
static/assets/
├── app.js          # 入口 + boot
├── state.js        # 全局状态 + DOM 引用
├── api.js          # loadJson / postJson
├── sse.js          # SSE 连接 / 事件处理
├── render/
│   ├── health.js   # renderHealth
│   ├── chat.js     # renderChats / renderChatThread / renderMessageBody
│   ├── runs.js     # renderRuns / renderRunReplay
│   ├── files.js    # renderFiles / renderFileEntries
│   ├── editor.js   # renderEditorHome
│   ├── resources.js # renderResources / renderPagedList
│   ├── diagnostics.js # renderDiagnostics
│   └── ui.js       # 通用 UI (modals, resizers, theme, tabs)
└── app.css         # CSS @layer 分组
```

### 6.2 SSE 增量渲染

当前每个 SSE 事件**全量重建**整个聊天线程 DOM。改为增量：新事件只追加/更新对应气泡。

### 6.3 搜索防抖

`chatSearch` 和 `fileSearch` 每次按键触发全量重新渲染。加 200ms 防抖。

### 6.4 CSS @layer 分组

当前 1834 行无结构。用 `@layer base, layout, components, utilities;` 分组。

### v3.0 验收

```powershell
$env:PYTHONPATH="src"
python -m agent.cli start --cwd .
# 手动冒烟：聊天、文件浏览、主题切换、审批流程、列拖拽
python -m pytest tests/test_ui.py -q
python -m pytest -q
```

---

## 随阶段顺手的工程债

| 债项 | 在哪个 Phase 顺便做 |
|---|---|
| `pyproject.toml` 版本 `0.1.0` → 当前版本 | Phase 1 |
| 建 `CHANGELOG.md` | Phase 1 |
| 拆 `test_loop.py`（2100 行）→ `tests/core/test_loop_*.py` | Phase 5 |
| 拆 `test_actions.py`（1000 行） | Phase 5 |
| 加 `--cov` 覆盖率配置 | Phase 5 |
| 删 `docs/agent-interview-summary.docx`（与 `.md` 重复） | Phase 1 |
| 清理 `roadmap-progress.md` 中过时的 "Later Roadmap" 表格 | Phase 1 |
| 修复 `test_docs.py` 硬编码测试命令字符串 | Phase 1 |
| `loop.py` 中 `_direct_chat_answer` / `_direct_external_list_path` 仅中文 — 文档标注限制 | Phase 1 |

---

## 不做的事情（明确延迟）

- **多 provider 完整实现（Claude/OpenAI 客户端）**：注册表留接口，具体客户端由后续需求驱动
- **PyInstaller/Nuitka 打包**：v1.0 已有决策文件，非瓶颈
- **Vue/Vite/Electron/Tauri**：v0.7 已有决策文件，静态 Workbench 当前够用
- **中文 i18n 抽象**：代码中硬编码的中文字符串数量大，但不是功能瓶颈
- **嵌入/语义搜索内存**：当前内存量小，词集匹配够用
- **原生 function-calling**：当前 JSON 协议与 prompt 工程链路成熟，切换成本高收益不明确

---

## 时间估算

| Phase | 主题 | 预估 |
|---|---|---|
| v2.1 | 安全硬化 | 1-2 天 |
| v2.2 | sandbox 模式接线 | 1 天 |
| v2.3 | 其余扩展点接线 | 1-2 天 |
| v2.4 | 提供者可扩展性 | 1-2 天 |
| v2.5 | 后端重构 | 2-3 天 |
| v3.0 | 前端模块化 | 2-3 天 |
| **总计** | | **8-13 天** |

---

## 防护栏

- 保持 secrets 在环境变量或 `.agent/secrets.env`，不提交
- 保持 `docs/main.pdf` 未跟踪
- 保持静态 Workbench 壳决策（v0.7），不引入框架
- 不削弱 sandbox / approval / redaction / snapshot / durable-log 安全行为
- 重构阶段现有测试全绿 = 行为不变；不接受回归
