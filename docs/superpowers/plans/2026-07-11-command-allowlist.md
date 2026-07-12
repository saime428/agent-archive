# 可配置命令白名单实现计划

> **For agentic workers:** Execute task-by-task. Each behavior task starts with a failing test, ends with focused verification, and is committed independently.

**Goal:** 允许用户在配置中声明额外 argv 前缀，同时保持硬拒绝、路径沙箱、审批和默认行为不变。

**Architecture:** `AgentConfig.allowed_commands` 使用 tuple 保存 TOML list；`run_once` 将其传给 `execute_run_command`；`shell._policy_denial` 先执行 shell/network/dangerous 硬拒绝，再匹配白名单，最后回落现有默认规则；CLI、trace/summary 与 Workbench 仅展示生效值，浏览器配置写接口不开放该键。

**Spec:** `docs/superpowers/specs/2026-07-11-command-allowlist-design.md`

## Global Constraints

- 不新增依赖，不调用 shell，不把 argv 拼成字符串执行。
- 白名单按完整 token 前缀匹配，禁止 substring/glob/regex。
- `SHELL_WRAPPERS`、`NETWORK_COMMANDS`、`DANGEROUS_COMMANDS` 永远先于白名单判定。
- `run_command` 仍是 confirmation-required；`approval`、sandbox、路径校验、超时和输出预算不变。
- `allowed_commands = []` 时行为逐字兼容当前 HEAD。
- Web 第一阶段只读展示；`_validated_config_updates` 不加入该键。
- 每个任务只 stage 列出的文件；提交前运行 focused tests 与 `git diff --check`。

---

### Task 1: 配置模型与验证

**Files:**
- Modify: `src/agent/config.py`
- Test: `tests/test_config.py`

**改动：**

1. `KNOWN_KEYS` 增加 `allowed_commands`。
2. `AgentConfig` 增加 `allowed_commands: tuple[str, ...] = ()`。
3. `ConfigOverrides` 增加 `allowed_commands: tuple[str, ...] | None = None`，并接入 `_apply_overrides`。
4. 将 `allowed_commands` 纳入字符串序列校验与 tuple 规范化；TOML 接受 list，override 接受 tuple，元素必须是非空字符串。
5. 不做危险命令预校验、不去重，运行时策略保持单一事实源。

**测试：**

- 默认值为 `()`。
- 项目 TOML `allowed_commands = ["python", "pip show"]` 加载为 tuple。
- 空 list 合法。
- 非 list、含空字符串或非字符串元素时抛 `ConfigError`。
- `ConfigOverrides(allowed_commands=("npm test",))` 正常覆盖。

- [ ] Step 1: 先写失败测试
- [ ] Step 2: 实现最小配置接线
- [ ] Step 3: 运行 `python -m pytest tests/test_config.py -q`
- [ ] Step 4: 运行 `git diff --check`
- [ ] Step 5: 仅提交本任务文件
  `git -c core.autocrlf=input commit -m "feat: add allowed_commands configuration"`

---

### Task 2: 命令策略匹配与 run loop 接线

**Files:**
- Modify: `src/agent/tools/shell.py`
- Modify: `src/agent/core/loop.py`
- Test: `tests/test_tools_shell.py`
- Test: `tests/core/test_loop_core.py`

**改动：**

1. `execute_run_command` 增加 keyword-only 参数 `allowed_commands: tuple[str, ...] = ()`。
2. `_policy_denial` 接收白名单并固定顺序：
   - shell wrapper → 拒绝；
   - network command → 拒绝；
   - dangerous command → 拒绝；
   - `_matches_allowed_command(...)` → 放行；
   - 现有 Git/Python/pytest/rg 默认规则；
   - 默认拒绝。
3. 新增最小 helper：

```python
def _matches_allowed_command(argv: list[str], allowed_commands: tuple[str, ...]) -> bool:
    for command in allowed_commands:
        prefix = command.split()
        if not prefix or len(prefix) > len(argv):
            continue
        executable_matches = _normalized_executable(argv[0]) == _normalized_executable(prefix[0])
        if executable_matches and argv[1 : len(prefix)] == prefix[1:]:
            return True
    return False
```

   `_normalized_executable` 复用 `_executable_name`，并去掉尾部 `.exe`。不要引入 `shlex` 或 shell 语义。
4. `run_once` 调 `execute_run_command` 时传 `allowed_commands=config.allowed_commands`。
5. `_validate_path_arguments` 保持在策略通过后执行，代码不改。

**shell 单测：**

- 无白名单时 `python script.py` 仍返回默认拒绝。
- `("python",)` 匹配 `python.exe script.py`。
- `("pip show",)` 匹配 `pip show pydantic`，不匹配 `pip install pydantic`。
- `("npm test",)` 不匹配 `npm testing`。
- 白名单含 `powershell`、`curl`、`rm` 时仍分别被硬拒绝。
- allowlisted Python 脚本在工作区内可执行；同一命令携带越界路径时仍返回 `SANDBOX_VIOLATION`。

**loop 集成测试：**

- 使用脚本化 FakeLLM：先请求 `[sys.executable, "script.py"]`，配置 `allowed_commands=("python",)`，审批 handler 返回 true；断言脚本执行观察被回喂，下一轮 `done`。
- 不提供审批 handler 时仍终止为 `APPROVAL_REQUIRED`，且脚本未执行（可复用既有审批测试结构，只补白名单配置）。

- [ ] Step 1: 写 matcher/执行器失败测试
- [ ] Step 2: 实现 shell 最小逻辑
- [ ] Step 3: 写 loop 接线失败测试
- [ ] Step 4: 传递 `config.allowed_commands`
- [ ] Step 5: 运行 `python -m pytest tests/test_tools_shell.py tests/core/test_loop_core.py -q`
- [ ] Step 6: 运行 `git diff --check`
- [ ] Step 7: 仅提交本任务文件
  `git -c core.autocrlf=input commit -m "feat: allow configured command prefixes"`

---

### Task 3: CLI 与持久化审计展示

**Files:**
- Modify: `src/agent/cli.py`
- Modify: `src/agent/core/loop.py`
- Modify: `src/agent/core/summary.py`
- Test: `tests/test_cli.py`
- Test: `tests/core/test_loop_core.py`

**改动：**

1. `_print_doctor` 输出：
   `config allowed_commands: [...]`。
2. `config_show` 输出：
   `allowed_commands: [...]`。
3. `_trace_config` 增加 `"allowed_commands": list(config.allowed_commands)`。
4. `summary._config_lines` 增加 `config_allowed_commands`。
5. 不在普通 `agent run` 结果重复打印，避免输出噪音；doctor、config show 和审计文件已经覆盖。

**测试：**

- doctor 与 config doctor 输出包含白名单字段。
- config show 在默认配置显示 `[]`，项目配置显示实际条目。
- tool-call trace 把 tuple 序列化为 list。
- run summary 包含 `config_allowed_commands`。

- [ ] Step 1: 写失败测试
- [ ] Step 2: 实现展示与审计字段
- [ ] Step 3: 运行 `python -m pytest tests/test_cli.py tests/core/test_loop_core.py -q`
- [ ] Step 4: 运行 `git diff --check`
- [ ] Step 5: 仅提交本任务文件
  `git -c core.autocrlf=input commit -m "feat: surface command allowlist diagnostics"`

---

### Task 4: Workbench 只读展示并锁住写入口

**Files:**
- Modify: `src/agent/web/server.py`
- Modify: `src/agent/web/static/assets/render/health.js`
- Test: `tests/test_ui.py`

**改动：**

1. `build_config_payload` 将 `allowed_commands` 与其他 tuple 字段一起显式转换为 JSON list。
2. `renderSettings` 的现有 `settingsReadinessList` 增加一行：

```javascript
["命令白名单", (config.allowed_commands || []).join(", ") || "未配置"]
```

   复用现有只读列表，不增加新表单字段、不改 index/state。
3. `_validated_config_updates.allowed` 不加入 `allowed_commands`。
4. 保存其他 Web 设置时，服务端读取原 TOML 并合并受支持字段，必须保留已有白名单。

**测试：**

- `/api/config` payload 把配置白名单返回为 list。
- 原配置含 `allowed_commands = ["python"]` 时，Web 保存其他设置后该行仍存在且值不变。
- POST `{allowed_commands: ["rm"]}` 不得新增或覆盖配置。
- 静态脚本包含只读展示逻辑；不出现 `allowed_commands` 表单写 payload。

- [ ] Step 1: 写后端行为失败测试
- [ ] Step 2: 实现 payload 规范化与只读行
- [ ] Step 3: 运行 `python -m pytest tests/test_ui.py -q`
- [ ] Step 4: 运行 `node --check src/agent/web/static/assets/render/health.js`
- [ ] Step 5: 运行 `git diff --check`
- [ ] Step 6: 仅提交本任务文件
  `git -c core.autocrlf=input commit -m "feat: show command allowlist in workbench"`

---

### Task 5: 文档、交接状态与最终门禁

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/next-feature-candidates.md`
- Test: `tests/test_docs.py`

**改动：**

1. README 增加配置示例：

```toml
allowed_commands = ["python", "pip show", "npm test"]
```

2. README 明确：
   - 按 argv token 前缀匹配；
   - 前缀越短权限越宽；
   - shell/network/dangerous 拒绝不可覆盖；
   - allowlisted 命令仍需审批和路径沙箱。
3. CHANGELOG `Unreleased` 记录命令白名单。
4. `docs/next-feature-candidates.md` 将候选 1 标为已完成，并保留候选 2/3 的排序与触发条件，避免下一会话重复选题。
5. `tests/test_docs.py` 增加最小文档断言，只检查配置键和安全说明。

- [ ] Step 1: 更新文档测试并确认先红
- [ ] Step 2: 更新 README、CHANGELOG、交接状态
- [ ] Step 3: 运行 `python -m pytest tests/test_docs.py -q`
- [ ] Step 4: 运行 focused gate：

```powershell
python -m pytest tests/test_config.py tests/test_tools_shell.py tests/core/test_loop_core.py tests/test_cli.py tests/test_ui.py tests/test_docs.py -q
```

- [ ] Step 5: 运行全量门禁：

```powershell
python -m pytest -q
git diff --check
python -m agent.cli doctor
python -m agent.cli release doctor --cwd .
```

- [ ] Step 6: 人工冒烟：

```text
1. 不配置 allowed_commands：python script.py 仍被默认拒绝。
2. 配置 allowed_commands = ["python"]：同一动作进入审批；批准后执行成功。
3. 配置 allowed_commands = ["curl", "powershell", "rm"]：三者仍被硬拒绝。
4. Workbench 设置页显示白名单，但没有编辑入口；保存其他设置后白名单不变。
5. run trace 与 summary 能看到实际生效的 allowed_commands。
```

- [ ] Step 7: 仅提交本任务文件
  `git -c core.autocrlf=input commit -m "docs: document configurable command allowlist"`

Expected：focused tests 与全量 pytest 全绿；默认行为无回归；硬拒绝、审批和沙箱边界均有自动化证据。
