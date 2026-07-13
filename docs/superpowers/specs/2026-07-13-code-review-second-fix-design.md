# 设计：代码审查第二刀——显式授权 `python -c`

日期：2026-07-13
状态：草案，待确认
依据：`docs/code-review-2026-07-12.md` 2.5
前置：`docs/superpowers/specs/2026-07-11-command-allowlist-design.md`
计划：待本 spec 确认后另写

## 背景

首轮 5.5 修复已经完成。审查中尚未解决、且无需等待外部触发条件的最高风险项，是 `run_command` 默认放行 `python -c`：

- `_python_policy_denial` 将任意 `python -c <code>` 视为默认允许命令；
- `_validate_path_arguments` 无法从 Python 源码字符串可靠提取路径，因此该形态跳过 argv 路径校验；
- 动作仍需审批，但一旦批准，Python 代码可以自行读写文件、发起网络访问或调用其他进程；
- 这属于能力授权，不是工作区级隔离。

项目已经有 `allowed_commands`，无需再设计脚本长度限制、AST 检查或第二套权限配置。下一刀只把默认隐式授权改成现有白名单上的显式授权。

## 为什么现在不做端点能力自动探测

审查 5.2 和 `docs/next-feature-candidates.md` 把端点探测标为“有触发再做”：当前日常 provider 是已通过 native smoke 的 DeepSeek，近期没有接入不支持 tools 的 Ollama 或其他本地端点。

现有 `agent provider smoke <provider> --native` 已提供显式在线验证 seam。没有真实端点兼容问题前，不新增：

- `native_tools = "auto"` 第三种配置值；
- 首次请求前的额外探测调用；
- 进程缓存或 `.agent/` 能力状态文件；
- 基于不同厂商 400 文案的脆弱分类器。

真正接入新端点时，再以实际错误响应设计探测规则。

## 目标

1. 默认配置下，`python -c` 在命令策略层 fail-closed。
2. 用户可以复用 `allowed_commands` 显式授权 `python -c`。
3. `python -m pytest`、直接 `pytest`、`rg` 和只读 Git 的默认能力不变。
4. shell wrapper、网络命令和危险命令的硬拒绝优先级不变。
5. `run_command` 的审批、超时、输出预算和 `shell=False` 全部不变。
6. 拒绝结果明确告诉用户如何显式启用，不伪装成沙箱保护。

## 非目标

- 不解析或审计 `-c` 后的 Python 源码。
- 不用字符数、关键字或正则判断脚本“安全”。
- 不给 Python 增加进程、文件系统或网络隔离。
- 不改变 `allowed_commands` 的 token 前缀语义。
- 不禁止用户显式配置宽前缀 `allowed_commands = ["python"]`。
- 不改变 `run_command` 的 confirmation-required 分类。
- 不改 CLI、config schema、Workbench 设置写接口或 trace 结构。
- 不处理端点自动探测、真正并行 `tool_calls`、文档 optional extras 或 `server.py` 拆分。

## 当前执行链

`run_command` 经过两个已有 seam：

1. `policy/approvals.py` 判断动作是否需要审批；
2. `tools/shell.py::_policy_denial` 判断 argv 是否可进入 `subprocess.run`。

本设计只改第二个 seam。调用链仍为：

```text
classify_action
  -> approval handler
  -> execute_run_command
  -> _policy_denial
  -> _validate_path_arguments
  -> subprocess.run(shell=False)
```

因此：

- `approval=never` 会在进入 shell 模块前拒绝 `run_command`；
- `risky-confirm`/`always` 下，即使用户批准，未显式授权的 `python -c` 仍会被命令策略拒绝；
- 显式授权只让命令通过 `_policy_denial`，不会跳过审批。

## 核心决策

### 1. 复用 `allowed_commands`，不新增配置

`_policy_denial` 已在 Python 默认规则前检查 `_matches_allowed_command`。因此只需删除 `_python_policy_denial` 对 `-c` 的默认放行：

```python
def _python_policy_denial(argv: list[str]) -> str | None:
    if len(argv) >= 2 and argv[1] == "-c":
        return "Python -c is disabled by default; add an explicit allowed_commands prefix to enable it."
    if len(argv) >= 3 and argv[1] == "-m" and argv[2] == "pytest":
        return None
    return "Only pytest module runs are allowed by default."
```

不在 `_python_policy_denial` 内再次读取配置；白名单判断继续只存在于 `_policy_denial`，保持 locality。

### 2. 显式授权语义

推荐最窄配置：

```toml
allowed_commands = ["python -c"]
```

匹配结果沿用现有 token 前缀规则：

| 配置 | argv | 命令策略结果 |
| --- | --- | --- |
| `[]` | `python -c "print(1)"` | deny |
| `["python -c"]` | `python -c "print(1)"` | allow，随后仍需审批 |
| `["python"]` | `python -c "print(1)"` | allow，属于用户选择的宽授权 |
| `["python -c"]` | `py -c "print(1)"` | deny，首 token 不同 |
| `["py -c"]` | `py -c "print(1)"` | allow，随后仍需审批 |
| `[]` | `python -m pytest -q` | 保持默认 allow，随后仍需审批 |

不自动把 `python`、`python3` 与 `py` 视为同一 executable；用户应按实际 argv 配置，避免扩大既有匹配接口。

### 3. 路径语义保持诚实

`python -c` 的源码位于单个 argv token 中，通用路径扫描无法可靠判断其实际访问目标。显式授权后，现有 `_validate_path_arguments` 仍不解析源码，也不能声称 Python 被 workspace sandbox 限制。

安全契约是：

```text
explicit allowed_commands opt-in + run_command approval
```

而不是：

```text
Python code is contained inside the workspace
```

README 必须明确这一区别，并提醒 `allowed_commands = ["python"]` 同时授权脚本文件、`-c` 和其他 Python 参数形态。

本改动也不消除所有 Python 代码执行能力：默认保留的 `pytest` / `python -m pytest` 会执行项目测试及其插件。它们是 coding agent 的既有验证路径，仍属于 confirmation-required 的 `run_command`。本 spec 只移除无需显式命令白名单即可进入的直接 inline interpreter，不把结果描述成完整代码执行隔离。

### 4. 错误与模型恢复

默认拒绝返回现有 `POLICY_DENIED` observation，message 固定为：

```text
Python -c is disabled by default; add an explicit allowed_commands prefix to enable it.
```

不新增错误码或专用事件。现有 observation feedback 会把拒绝原因回喂模型；模型可以改用 `python -m pytest`、已有工具，或请求用户配置授权。

## 文档与界面

只修改 README 的命令白名单段落：

- 默认 `python -c` 已关闭；
- 最窄启用方式是 `allowed_commands = ["python -c"]`；
- `allowed_commands = ["python"]` 是更宽授权；
- 显式授权与审批不是 Python sandbox。

不新增 doctor 输出：`agent doctor` 和 `agent config doctor` 已显示生效的 `allowed_commands`。不改 Workbench：设置页已只读展示同一配置。

## 测试设计

### 命令策略

在 `tests/test_tools_shell.py` 锁住：

1. 默认 `python -c` 返回新的精确拒绝文案；
2. `allowed_commands=("python -c",)` 可放行 inline Python；
3. 既有宽授权 `allowed_commands=("python",)` 仍可放行，避免静默改变已有显式配置；
4. `python -m pytest` 仍默认放行；
5. hard-deny 优先级测试保持不变。

现有直接执行 `python -c` 的 shell 测试，是测试自身需要该能力，不代表产品默认策略。它们应显式传入 `allowed_commands=("python -c",)`，继续覆盖 cwd、timeout、输出截断和执行结果。

### 不执行证明

新增一个最小用例，让 inline Python 尝试创建 marker：

```python
argv = [sys.executable, "-c", "from pathlib import Path; Path('escaped.txt').write_text('x')"]
```

默认空白名单下断言：

- observation code 为 `POLICY_DENIED`；
- marker 不存在；
- 不需要 monkeypatch 源码解析或 subprocess internals。

再用 `allowed_commands=("python -c",)` 执行同一动作，断言 marker 只在测试工作区内产生，证明迁移路径有效。该测试只证明显式授权链路，不把工作区内写入描述为安全隔离。

### 文档

`tests/test_docs.py` 只增加一个 README 契约测试，断言包含：

- `allowed_commands = ["python -c"]`；
- `python -c` 默认关闭；
- 明确说明它不是 Python sandbox。
- 明确说明 pytest 仍会执行项目代码。

不为纯文案增加新的测试文件。

## 预计文件

- `src/agent/tools/shell.py`
- `tests/test_tools_shell.py`
- `README.md`
- `tests/test_docs.py`

不预计修改 `config.py`、`loop.py`、`approvals.py`、CLI、Workbench 或增加依赖。

## 验收

自动门禁：

```powershell
python -m pytest tests/test_tools_shell.py tests/test_docs.py tests/test_approvals.py tests/core/test_loop_core.py -q
python -m pytest -q
python -m agent.cli doctor
git diff --check
```

真实路径检查使用 `D:\CodexScratch` 临时工作区：

1. 默认配置运行 inline Python 写 marker，确认返回 `POLICY_DENIED` 且 marker 不存在；
2. 加入 `allowed_commands = ["python -c"]` 后显式批准同一动作，确认命令执行；
3. `approval=never` 下即使存在白名单仍不出现审批，并在进入 shell 前拒绝；
4. 验收完成后清理临时工作区。

## 迁移

依赖默认 `python -c` 的项目需要在 global 或 project config 显式加入：

```toml
allowed_commands = ["python -c"]
```

已有 `allowed_commands = ["python"]` 的项目无需迁移，但 README 会标明它比 `python -c` 更宽。不会自动改写用户配置。

## 风险与回退

### 现有编码流程被拒绝

这是预期的安全默认值变化。固定拒绝文案和 README 给出一行迁移配置；不做隐式兼容回退，否则仍是原来的默认高能力面。

### 用户误以为显式授权等于隔离

README 与 spec 明确：allowlist 是能力授权，approval 是执行确认，两者都不是 Python 进程 sandbox；保留的 pytest 路径仍会执行项目代码。真正需要隔离时，应另立基于 OS/容器能力的设计，而不是扩展字符串检查。

### 回退

若真实工作流证明迁移成本不可接受，只需恢复 `_python_policy_denial` 的 `-c` allow 分支和对应测试/README；不涉及配置迁移、持久化格式或日志兼容。
