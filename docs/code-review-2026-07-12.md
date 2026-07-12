# Agent 项目代码审查报告

**日期：** 2026-07-12  
**审查范围：** `F:\codex project\agent` 全仓库（静态阅读 + 全量 pytest）  
**测试结果：** 501 passed / 约 7.13s  
**审查时分支：** `codex/v3.0-frontend-modules` @ `4dbec52`

---

## 1. 项目快照

| 项 | 状态 |
|---|---|
| 定位 | 本地 Python coding agent（CLI + 静态 Workbench） |
| 版本 | 2.1.0（代码已推进到 v3.0 前端模块化） |
| 规模 | 后端约 5.5k 行；`server.py` ~1551 / `loop.py` ~967 / `cli.py` ~651 仍是大头 |
| 测试 | 501 通过，核心路径覆盖好 |
| 技术栈 | Python 3.11+、pydantic、typer/rich、stdlib HTTP + 静态前端 |

**主要代码地图：**

- `src/agent/cli.py` — Typer CLI 入口
- `src/agent/core/` — 动作协议、run loop、预算、run store、红acted 日志、memory/hooks/skills
- `src/agent/policy/` — 审批与工作区沙箱
- `src/agent/tools/` — filesystem / shell / git / web / documents
- `src/agent/llm/` — fake / DeepSeek / openai-compat
- `src/agent/web/` — 本地 Workbench 服务与静态 UI
- `tests/` — 与上述模块对齐的 pytest 套件

---

## 2. 真实 Bug / 行为缺陷

### 2.1 【高】`native_tools` 下 observation 回喂仍要求 JSON 协议

**位置：** `src/agent/core/loop.py` → `_build_observation_feedback_message`

该函数**不区分 native / JSON 协议**，统一要求：

> Return exactly one valid JSON action object...

而 system prompt 与 repair 通道在 `native_tools=true` 时是 *“Call exactly one tool”*。

**后果：** 第一轮工具成功后，后续轮次提示互相矛盾；thinking 模型更容易乱回复或触发 repair，直接影响日常多轮编码。

**建议修法：**

- 为 feedback 增加 `native: bool` 参数
- native 时改为 “Call exactly one tool…”
- 中长期可考虑标准 OpenAI 多轮：`role: tool` + `tool_call_id`

---

### 2.2 【中高】`approval = "never"` 名实不符（测试已锁死坏语义）

**配置侧**把 `never` 当成「关闭审批」：

- 项目 `.agent/config.toml` 禁止设 `approval=never`（文案：cannot disable approvals）
- 浏览器配置写入同样禁止 `never`

**策略侧** `classify_action` 对 `never` 下的 `write_file` / `run_command` 等**仍返回 `approval_required`**，与 `risky-confirm` 行为相同。相关测试（如 `tests/test_approvals.py`、`tests/core/test_loop_core.py`）明确断言这一行为。

**后果：** CLI `--approval never` **不会自动放行写操作**；无 approval handler 时只是 fail-closed。用户会以为关了审批，实际没有。

**建议：** 二选一，不要维持现状：

1. 真正实现 `never` = 自动放行 `CONFIRMATION_REQUIRED_ACTIONS`（全局配置 / CLI 可设，项目配置仍禁止）
2. 或 deprecate / 改名（例如 `strict`），并修正所有文案

---

### 2.3 【中】JSON 协议 system prompt 漏掉写/命令工具

**位置：** `src/agent/core/loop.py` → `_action_protocol_message`（非 native 分支）

当前列出的 actions 大致为：

`done, ask_user, list_dir, read_file, search_files, git_status, git_diff`（可选 `web_search`）

未列出：`write_file`、`apply_patch`、`run_command`、文档读写类工具。

技能（如 `code-dev`）里有 allowed tool hints，但 system 列表偏窄。`native_tools=false` 时，模型更少主动改代码。

**建议：** 与 `tool_catalog` / schema 对齐，生成完整可用动作列表。

---

### 2.4 【中】原生多 `tool_calls` 只取第一个

**位置：** `src/agent/llm/openai_compat.py`

- `_envelope_from_tool_message` 只取 `tool_calls[0]`
- `_ToolCallAssembler` 只处理 `index == 0`

其余 tool call **静默丢弃**。交接文档 `docs/next-feature-candidates.md` 已记为候选 3。

DeepSeek 在 `tool_choice: "auto"` 下较少发并行调用，ROI 偏低，但一旦出现就是静默丢动作。

---

### 2.5 【中】`python -c` 默认放行 = 高能力逃逸面

**位置：** `src/agent/tools/shell.py` → `_python_policy_denial`

`python -c ...` 默认放行，且对 `-c` **跳过路径参数沙箱校验**。审批通过后可执行任意 Python（读写、网络等）。

对 coding agent 可接受，但能力面很大。

**建议：**

- 在 doctor / README 明确标注为高风险能力；或
- 收窄策略（例如仅短脚本、或需显式 `allowed_commands`）

---

### 2.6 【中】Workbench 审批等待无超时

**位置：** `src/agent/web/server.py` → chat job `handle_approval`

`job.condition.wait()` 在无决策时**无限等待**。用户关闭页签或 SSE 断开后，后台线程可能长期占用。

**建议：** 增加超时（例如 5–10 分钟）后默认 deny，并与 `CHAT_JOB_TTL_SECONDS` 清理逻辑联动。

---

### 2.7 【低】文档工具依赖声明不全

`pyproject.toml` 主依赖仅声明 `pypdf`；`python-docx` / `python-pptx` 等未列入（运行时有缺失依赖友好错误）。

**建议：** 增加 optional extras，例如：

```toml
[project.optional-dependencies]
docs = ["python-docx", "openpyxl", "python-pptx"]
```

并在 doctor / README 标明可选安装。

---

### 2.8 【低】其他已知限制（设计债）

| 项 | 说明 |
|---|---|
| `allowed_commands` 空白切分 | 无法表达「单个 argv token 含空格」（代码中已有 `ponytail:` 注释） |
| Windows junction / symlink TOCTOU | 路线图 v2.1 已文档化 |
| Workbench 无鉴权 | 默认绑 `127.0.0.1` 尚可；绑 `0.0.0.0` 会暴露工作区读写 |
| `server.py` 体量 | 前端已 ES modules 拆分，后端仍是单体大文件 |

---

## 3. 可优化点（非必须立刻改）

### 3.1 工程质量

1. **`server.py` 拆分** — health / chat / files / config / payload 按域拆模块
2. **`loop.py` 再瘦** — feedback / message 构建与 native 协议可独立文件
3. **config 校验收敛** — 每加 `KNOWN_KEYS` 一项要动多处；可收敛为 schema 表
4. **覆盖率工具** — `pytest-cov` 在 optional `dev` 中；环境未装时 `--cov` 直接失败，应写清 dev 安装步骤

### 3.2 产品体验

1. 默认 `mode=guided`（3 步）对编码偏紧；Workbench 默认可 `auto`，或按技能/任务类型抬预算
2. 端点工具能力自动探测 — `native_tools` 配错易 400（见 `docs/next-feature-candidates.md` 候选 2）
3. 观察回喂 — 成功路径几乎无“下一步建议”，仅错误有 guidance；可加极短 continue 提示
4. 文档工具 optional extras 与 doctor 展示

### 3.3 安全（保持边界，别为方便削弱）

- 沙箱 / 审批 / 红acted 日志 / 快照 — **应保持**，这是产品核心卖点
- 若开放 `allowed_commands` 的 Web 写入，需要配置回滚语义（文档已 defer）
- `web_search` 依赖 DuckDuckGo HTML 解析，页面改版会静默空结果；失败时应给明确 “0 results / parse failed”

---

## 4. 做得好的地方（维护时别乱动）

- **501 测试** 与 TDD 节奏扎实
- **策略分层**清晰：沙箱、审批、命令硬拒绝、allowlist 优先级
- **错误恢复**：可恢复错误回喂 + `max_consecutive_errors`
- **本地密钥**：`.agent/secrets.env`，不进 config.toml
- **Workbench**：SSE、审批面板、快照/diff、前端 ES modules 已落地
- **架构取舍**：少依赖、stdlib HTTP、静态 UI — 与「本地安全 coding agent」定位一致

---

## 5. 下一步建议（按 ROI 排序）

### 5.1 立刻做（小 diff、高收益）

| 优先级 | 项 | 原因 |
|---|---|---|
| P0 | 修 native observation 回喂文案（+ 测试） | 影响日常 `native_tools=true` 多轮 |
| P0 | 厘清 `approval=never`：实现 auto-allow **或** 改名/deprecate | 配置谎言比缺功能更糟 |
| P1 | JSON system prompt 补全可用工具列表 | 关掉 native 时编码能力会“假死” |
| P1 | 审批 `condition.wait` 加超时 | 防 Workbench 僵尸线程 |

### 5.2 近期产品（有触发再做）

1. **`allowed_commands` 已完成** — 后续候选：
   - 端点工具能力探测（接 Ollama 等本地端点时做）
   - 并行 tool_calls（ROI 低，最后做）
2. 编码默认预算：Workbench 默认 `mode=auto` 或智能抬限
3. doctor 增强：可选文档依赖、`native_tools` 与 provider 一致性检查

### 5.3 明确不做（除非触发条件）

- 打包可执行文件 / Electron / Vue 大迁徙
- Web 写高风险配置（无回滚语义前）
- 为「并行 tool_calls」大改 loop 审批语义

### 5.4 工程债（有空再拆）

- `server.py` 按 API 域拆分
- 文档工具 optional extras
- 更新 `PROJECT_CONTEXT.md`（仍停留在 2026-07-08 / v1.0 叙述，与 2.1+ 现状不同步）

### 5.5 建议的第一刀实现顺序

若只改一轮就想明显变好：

1. `_build_observation_feedback_message(..., native=use_native)` — 对齐 native 指令
2. `classify_action` 对 `approval=="never"` 放行 CONFIRMATION_REQUIRED，**或**删除/重命名 never
3. JSON system prompt 使用完整工具目录
4. 审批 wait 超时后默认 deny

这四项都能用现有 pytest 风格锁住，且不动沙箱 / 快照主路径。

---

## 6. 结论

这是一个 **安全优先、测试扎实的本地 agent**。没有“随时会炸”的未测核心，但存在几处 **语义不一致**（native 回喂、`approval=never`、JSON 工具列表），会直接伤害日常编码体验。

**优先修提示词与审批语义，比继续堆新功能更划算。**

---

## 7. 相关文档

| 文档 | 用途 |
|---|---|
| `PROJECT_CONTEXT.md` | 项目一页纸上下文（偏旧） |
| `docs/next-feature-candidates.md` | 功能候选与交接注意 |
| `docs/roadmap-v2.1-v3.0.md` | v2.1–v3.0 路线图 |
| `docs/roadmap-progress.md` | 里程碑完成情况 |
| `docs/post-v1.0-polish-backlog.md` | polish 与 defer 项 |
| `CHANGELOG.md` | 近期变更 |

---

## 8. 审查方法说明

- 阅读 README / PROJECT_CONTEXT / 路线图 / 交接文档
- 通读核心路径：`loop.py`、`approvals.py`、`sandbox.py`、`shell.py`、`openai_compat.py`、`server.py`、`config.py`、`filesystem.py` 等
- 对照测试锁定的语义（尤其 `approval=never`、native recovery）
- 执行：`python -m pytest -q`（501 passed）
- 未做：真实 DeepSeek 联网冒烟、浏览器端到端手工点检
