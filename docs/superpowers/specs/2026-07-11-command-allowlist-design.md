# 可配置命令白名单设计

日期：2026-07-11
状态：草案（基于 `docs/next-feature-candidates.md` 候选 1，待实施前确认）
范围：`src/agent/config.py`、`src/agent/core/loop.py`、`src/agent/core/summary.py`、`src/agent/tools/shell.py`、CLI/Workbench 只读展示、对应测试与文档

## 背景

`run_command` 当前只默认放行：

- `pytest`、`rg`
- 只读 Git 子命令
- `python -c ...`
- `python -m pytest ...`

这保证了安全默认值，但也让 code-dev 场景中的 `python script.py`、`pip show`、`npm test` 等常见命令无法执行。目标是在不削弱现有硬拒绝、路径沙箱和审批机制的前提下，让用户显式声明额外可执行的 argv 前缀。

## 目标

1. 新增项目/全局配置键 `allowed_commands`，默认空列表，默认行为零变化。
2. 按 argv token 前缀匹配，而不是拼接字符串或子串匹配。
3. shell wrapper、网络命令和危险命令的拒绝规则永远优先，白名单不能覆盖。
4. 白名单只决定命令是否通过命令策略；`run_command` 仍按现有机制要求审批并校验路径。
5. CLI、持久化 trace/summary 和 Workbench 设置就绪区可以只读查看生效白名单。

## 非目标

- 不支持 glob、正则、否定规则或按技能拆分白名单。
- 不允许 Workbench 写入 `allowed_commands`。
- 不改变 `run_command` 的审批类别、超时、输出预算或 `shell=False`。
- 不增加 shell wrapper，不开放 curl/ssh/wget 等网络命令。
- 不处理端点能力探测或并行多工具调用。

## 配置契约

用户配置写法：

```toml
allowed_commands = ["python", "pip show", "npm test"]
```

内部使用不可变 `tuple[str, ...]`：

```python
allowed_commands: tuple[str, ...] = ()
```

配置加载规则：

- TOML 中必须是非空字符串组成的 list；空 list 合法。
- CLI override（若内部测试或后续调用使用）必须是 tuple。
- 不自动去重；重复项无副作用，保持配置原样便于诊断。
- 不在加载阶段拒绝看似危险的条目；运行时硬拒绝规则仍是唯一裁判，避免配置层复制安全名单。

## 匹配语义

每个配置项按空白拆成 token 前缀。首 token 复用现有 executable 规范化：取 basename、转小写、忽略可选 `.exe`；其余 token 精确且区分大小写。必须按完整 token 边界匹配。因此 `pip Show` 不匹配配置项 `pip show`。

| 配置项 | argv | 结果 |
| --- | --- | --- |
| `python` | `python script.py` | 匹配 |
| `python` | `C:\\Python313\\python.exe script.py` | 匹配 |
| `pip show` | `pip show pydantic` | 匹配 |
| `pip show` | `pip Show pydantic` | 不匹配 |
| `pip show` | `pip install pydantic` | 不匹配 |
| `npm test` | `npm testing` | 不匹配 |

第一期不支持“单个 token 自身含空格”的命令前缀，例如带空格的绝对 executable 路径。若真实需求出现，再把配置升级为 token 数组结构，而不是引入 shell 解析。

## 策略顺序

`_policy_denial(argv, allowed_commands)` 固定按以下顺序执行：

1. 拒绝 `SHELL_WRAPPERS`。
2. 拒绝 `NETWORK_COMMANDS`。
3. 拒绝 `DANGEROUS_COMMANDS`。
4. 若 argv 匹配 `allowed_commands`，通过命令策略。
5. 否则沿用现有默认规则：只读 Git、受限 Python、pytest、rg。
6. 其余命令返回 `Command is not allowed by default.`。

通过命令策略后仍必须经过：

- `run_command` 的 confirmation-required 审批；
- `_validate_path_arguments` 和 `WorkspaceSandbox`；
- `subprocess.run(..., shell=False)`；
- 现有超时和输出截断。

因此，`allowed_commands = ["curl"]`、`["powershell"]` 或 `["rm"]` 仍会被硬拒绝；`allowed_commands = ["git commit"]` 可以越过默认只读 Git 限制，但仍需用户审批。

## 调用链接线

- `AgentConfig` 保存 `allowed_commands`。
- `run_once` 在调用 `execute_run_command` 时仅传入 `config.allowed_commands`，工具层不依赖整个配置对象。
- `execute_run_command` 保持默认参数 `allowed_commands=()`，现有直接调用者行为不变。
- `_trace_config` 和 Markdown summary 记录生效白名单，便于审计为何某条命令能够执行。

## CLI 与 Workbench

CLI：

- `agent doctor` 输出 `config allowed_commands`。
- `agent config show` 输出 `allowed_commands`。

Workbench：

- `/api/config` 只读 payload 包含 JSON list。
- 设置页现有“运行就绪”列表增加“命令白名单”一行。
- `_validated_config_updates` 明确不加入 `allowed_commands`；浏览器 POST 不能新增或覆盖白名单，现有配置值必须保留。

## 模型提示决策

第一期不把 `allowed_commands` 注入 JSON/native 系统提示。白名单属于执行策略，不是新增工具；模型仍只看到既有 `run_command` schema。命令未获策略放行时，现有 `POLICY_DENIED` 错误恢复会把结果回喂模型，由模型改用其他命令或询问用户。

这样避免系统提示复制配置状态，也不把用户配置内容扩散到模型上下文。只有实际试错率证明错误恢复不足时，才考虑加入一行经过预算和转义的只读提示。

## 风险与缓解

### 配置过宽

`allowed_commands = ["python"]` 会允许任意 Python 脚本进入审批阶段。README 必须明确：优先声明最窄前缀，并仅在理解命令能力时配置。

README 还必须明确举例：`allowed_commands = ["git commit"]` 会有意越过默认只读 Git 策略并进入审批阶段；首 token 不区分大小写/`.exe`，后续 token 区分大小写。

缓解：审批不变、硬拒绝优先、路径沙箱不变、trace 记录白名单。

### 项目配置扩大能力

项目 `.agent/config.toml` 可以声明白名单，但不能自动执行命令；模型请求 `run_command` 后仍需要用户批准。第一期沿用交接方案，不限制为全局配置。

### 简单 token 化的上限

空白拆分不表达带空格 token。第一期通过文档注明上限；只有真实用例出现时才升级配置结构。

## 验收标准

- 默认空白名单下，现有命令策略与全部测试保持不变。
- `python script.py`、`pip show ...`、`npm test ...` 可由对应白名单放行。
- token 前缀不误匹配相近命令。
- shell/network/dangerous 硬拒绝不可被白名单覆盖。
- allowlisted 命令仍需审批，越界路径仍被沙箱拒绝。
- doctor、config show、trace、summary 和 Workbench 只读展示生效白名单。
- Web 配置写接口不能修改白名单。
- 全量 pytest、`git diff --check`、doctor 和人工冒烟通过。
