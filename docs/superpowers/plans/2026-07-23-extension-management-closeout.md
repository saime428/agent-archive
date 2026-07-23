# 扩展管理面收尾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 关闭阶段 2 扩展闭环的四个管理面缺口：hooks 加载警告与 `hooks list`、`mcp show`、顶层 doctor 聚合、`config set/unset`（含 config 写路径收敛到共享模块）。

**Architecture:** `KNOWN_HOOK_NAMES` 进 config.py（叶子模块，契约测试锁一致性）；`McpConfigStore.describe` 走既有快照路径；doctor 聚合只读静态 store；新 `agent/config_write.py` 是项目 config 唯一写路径，web 与 CLI 为其两个 Adapter。

**Tech Stack:** Python 3.13 stdlib + 现有 pytest。无新依赖。

**Spec:** `docs/superpowers/specs/2026-07-23-extension-management-closeout-design.md`

**状态：** 已执行（2026-07-23，全量门禁通过）

## Global Constraints

- 不新增第三方依赖；config 文件格式与 run/session 数据不迁移。
- 行为变化仅限：新增命令（`hooks list`、`mcp show`、`config set/unset`）、新增 config 警告、doctor 与 `config show` 新增输出行。已有输出行不改。
- web `/api/config/save` 请求/响应契约不变；`tests/test_web.py` 现有断言一律不改（已核实：该文件未断言 `_validated_config_updates` 的类型/枚举错误文案，委托后文案变为 config 风格属允许漂移）。
- `tests/test_ui.py:253` 断言 `OSError, match="Could not save project config"`：共享写模块的发布失败包装必须保持消息 `Could not save project config {config_path}.`。
- `tests/test_docs.py:786` 硬断言 roadmap 的 `Next Project vNext slice: the remaining Phase 2 management surface`：该行只能在 Task 7 与 roadmap 同一提交内一起更新（Task 1-6 不碰 roadmap，全量测试保持绿）。
- `McpConfigStore.describe` 不 import/构造 `McpStdioRuntime`，不产生子进程。
- 顶层 doctor 退出码语义不变：仍只在 config 加载失败时 exit 1。
- 测试命令：`python -m pytest`（项目 venv：`.venv\Scripts\python.exe`，`$env:PYTHONPATH="src"`）。提交前 `git diff --check`。
- 提交消息遵循仓库风格（`feat:`/`refactor:`/`docs:` 前缀，无 attribution 尾注）。

---

### Task 1: KNOWN_HOOK_NAMES 与加载警告

**Files:**
- Modify: `src/agent/config.py`
- Test: `tests/test_config.py`（追加）、`tests/test_hooks.py`（追加契约测试）

**Interfaces:**
- Consumes: 无（首个任务）。
- Produces: `agent.config.KNOWN_HOOK_NAMES: frozenset[str]`（`{"audit", "before_tool_format", "fail"}`）；`load_config` 对合并后 config 追加两类警告。

- [x] **Step 1: 写失败测试**

`tests/test_hooks.py` 追加契约测试：

```python
def test_known_hook_names_match_builtin_hooks() -> None:
    from agent.config import KNOWN_HOOK_NAMES
    from agent.core.hooks import BUILTIN_HOOKS

    assert frozenset(BUILTIN_HOOKS) == KNOWN_HOOK_NAMES
```

`tests/test_config.py` 追加（沿用文件既有 fixture 风格写 config 文件）：

- `test_unknown_enabled_hook_warns`：项目 config 写 `enabled_hooks = ["audit", "typo"]`，断言 warnings 恰有一条含 `Unknown hook 'typo' in enabled_hooks; known hooks:` 且含 `audit, before_tool_format, fail`；config 本身加载成功、`enabled_hooks` 保留原值。
- `test_unknown_blocking_hook_warns`：`blocking_hooks = ["nope"]` → 警告含 `Unknown hook 'nope' in blocking_hooks`。
- `test_blocking_hook_not_enabled_warns`：`enabled_hooks = ["audit"]`、`blocking_hooks = ["fail"]` → 警告含 `Blocking hook 'fail' is not in enabled_hooks`。
- `test_known_hooks_produce_no_hook_warnings`：`enabled_hooks = ["audit"]`、`blocking_hooks = ["audit"]` → warnings 中无 `hook` 字样。

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_hooks.py tests/test_config.py -q`
Expected: FAIL（`ImportError: cannot import name 'KNOWN_HOOK_NAMES'`）

- [x] **Step 3: 最小实现**

`src/agent/config.py`：

1. `KNOWN_KEYS` 之后加：

```python
KNOWN_HOOK_NAMES = frozenset({"audit", "before_tool_format", "fail"})
```

2. `load_config` 中构造 `diagnostics` 之前（overrides 应用后，保证检查合并终值）加：

```python
    for key_name, names in (("enabled_hooks", config.enabled_hooks), ("blocking_hooks", config.blocking_hooks)):
        for name in names:
            if name not in KNOWN_HOOK_NAMES:
                known = ", ".join(sorted(KNOWN_HOOK_NAMES))
                warnings.append(f"Unknown hook {name!r} in {key_name}; known hooks: {known}.")
    for name in config.blocking_hooks:
        if name in KNOWN_HOOK_NAMES and name not in config.enabled_hooks:
            warnings.append(f"Blocking hook {name!r} is not in enabled_hooks and will never run.")
```

（未知名不重复报第二类警告，避免一个 typo 产出两行。）

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_hooks.py tests/test_config.py -q`
Expected: 全部 passed

- [x] **Step 5: 相邻回归**

Run: `python -m pytest tests/test_cli.py tests/test_web.py -q`
Expected: 全部 passed（现有测试的 hooks 配置都用已知名或空值）

- [x] **Step 6: Commit**

```bash
git add src/agent/config.py tests/test_config.py tests/test_hooks.py
git commit -m "feat: warn on unknown hook names in config"
```

---

### Task 2: `agent hooks list` 与展示面补齐

**Files:**
- Modify: `src/agent/cli.py`（新 `hooks_app`、`config_show`、`_print_doctor`）
- Test: `tests/test_cli.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `KNOWN_HOOK_NAMES`（经 config warnings 间接）；`agent.core.hooks.BUILTIN_HOOKS`。
- Produces: `agent hooks list [--cwd]`；`config show` 与 `_print_doctor` 各新增 `enabled_hooks`/`blocking_hooks` 两行。

- [x] **Step 1: 写失败测试**

`tests/test_cli.py` 追加（沿用 `CliRunner` 与临时 workspace 写法）：

- `test_hooks_list_shows_builtins_and_state`：config 写 `enabled_hooks = ["audit"]`、`blocking_hooks = ["audit"]`，断言输出含 `audit\tenabled\tblocking`、`before_tool_format\tdisabled\t-`、`fail\tdisabled\t-`，exit 0。
- `test_hooks_list_marks_unknown_reference`：config 写 `enabled_hooks = ["typo"]`，断言输出含 `typo\tunknown\t-` 且 exit 0。
- `test_config_show_lists_hook_keys`：默认 workspace 下 `config show` 输出含 `enabled_hooks: []` 与 `blocking_hooks: []`。
- `test_doctor_lists_hook_keys`：`config doctor` 输出含 `config enabled_hooks: []` 与 `config blocking_hooks: []`。

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_cli.py -q -k "hooks or hook_keys"`
Expected: 4 条 FAIL（无 `hooks` 命令、无输出行）

- [x] **Step 3: 最小实现**

`src/agent/cli.py`：

1. import 区加 `from agent.core.hooks import BUILTIN_HOOKS`。
2. 现有 `add_typer` 组（38-44 行）加 `hooks_app = typer.Typer(help="Inspect run hooks.")` 与 `app.add_typer(hooks_app, name="hooks")`（定义位置随其他 sub-app）。
3. 新命令：

```python
@hooks_app.command("list")
def hooks_list(cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory.")) -> None:
    """List builtin hooks and their configured state."""
    workspace = (cwd or Path.cwd()).resolve()
    try:
        config, _diagnostics = load_config(workspace)
    except ConfigError as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    for name in sorted(BUILTIN_HOOKS):
        enabled = "enabled" if name in config.enabled_hooks else "disabled"
        blocking = "blocking" if name in config.blocking_hooks else "-"
        console.file.write(f"{name}\t{enabled}\t{blocking}\n")
    referenced = tuple(dict.fromkeys(config.enabled_hooks + config.blocking_hooks))
    for name in referenced:
        if name not in BUILTIN_HOOKS:
            blocking = "blocking" if name in config.blocking_hooks else "-"
            console.file.write(f"{name}\tunknown\t{blocking}\n")
```

4. `config_show`：`allowed_commands` 行之后加：

```python
    console.print(f"enabled_hooks: {list(config.enabled_hooks)}")
    console.print(f"blocking_hooks: {list(config.blocking_hooks)}")
```

5. `_print_doctor`：`config allowed_commands` 行之后加同格式两行（`config enabled_hooks:` / `config blocking_hooks:`）。

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_cli.py -q`
Expected: 全部 passed（含既有 doctor/config show 断言——只增行不改行）

- [x] **Step 5: Commit**

```bash
git add src/agent/cli.py tests/test_cli.py
git commit -m "feat: add hooks list and surface hook config"
```

---

### Task 3: `McpConfigStore.describe` 与 `agent mcp show`

**Files:**
- Modify: `src/agent/mcp_config.py`（`McpServerDetail` + `describe`）
- Modify: `src/agent/cli.py`（`mcp show` 命令）
- Test: `tests/test_mcp_config.py`、`tests/test_cli.py`（各追加）

**Interfaces:**
- Consumes: 既有 `_locked`/`_read_snapshot`/`_inventory`/`_parse_servers`/`_validate_server_id`/`_config_error`。
- Produces: `McpServerDetail`（frozen dataclass：`item: McpInventoryItem`、`config: McpServerConfig | None`）；`McpConfigStore.describe(server_id: str) -> McpServerDetail`；`agent mcp show ID [--cwd]`。

- [x] **Step 1: 写失败测试**

`tests/test_mcp_config.py` 追加（沿用既有 store fixture 写法）：

- `test_describe_valid_server_returns_config`：set 一个合法 server 后 `describe`，断言 `item.status == "valid"`、`config.command`/`args`/`pass_env`/`cwd` 与写入一致。
- `test_describe_disabled_server_still_parses_config`：disable 后 `describe`，`item.status == "disabled"` 且 `config is not None`。
- `test_describe_disabled_broken_command_returns_none_config`：写入坏 command 的 disabled 片段（沿用既有"disabled 坏 command"fixture 手法），`config is None` 且 `item.status == "disabled"`。
- `test_describe_env_invalid_server_returns_none_config`：enabled 但缺 `pass_env` 环境变量的 server（`_inventory` 判为 invalid 的既有 fixture 手法），`item.status == "invalid"` 且 `config is None`（describe 与 `_inventory` 同链：parse 成功但 env 校验失败也归 None，保持 spec 的 invalid→None 映射）。
- `test_describe_orphan_returns_none_config`：构造 orphan state（既有测试有此手法），`item.status == "orphan"`、`config is None`。
- `test_describe_unknown_server_raises`：`pytest.raises(McpRuntimeError, match="Server does not exist.")`。

`tests/test_cli.py` 追加：

- `test_mcp_show_prints_fields`：set 后 `mcp show ID`，断言输出含 `server_id: `、`source: managed`、`enabled: true`、`status: valid`、`command: `、`args: `、`pass_env: `、`cwd: `，exit 0。
- `test_mcp_show_unknown_exits_one`：`mcp show missing` → exit 1，输出含 `Server does not exist.`。

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_mcp_config.py tests/test_cli.py -q -k "describe or mcp_show"`
Expected: FAIL（`AttributeError: describe` / 未知命令）

- [x] **Step 3: 最小实现**

`src/agent/mcp_config.py`：`McpInventoryItem` 之后加 dataclass，`validate` 之后加方法：

```python
@dataclass(frozen=True, slots=True)
class McpServerDetail:
    item: McpInventoryItem
    config: McpServerConfig | None
```

```python
    def describe(self, server_id: str) -> McpServerDetail:
        _validate_server_id(server_id)
        with self._locked() as root:
            snapshot = self._read_snapshot(root)
            items = {item.server_id: item for item in self._inventory(snapshot)}
            item = items.get(server_id)
            if item is None:
                raise _config_error("Server does not exist.", server_id=server_id)
            config = None
            raw = next((raw for raw in snapshot.servers if raw.server_id == server_id), None)
            if raw is not None:
                try:
                    parsed = self._parse_servers((raw,))[0]
                    self._validate_environment(parsed)
                    config = parsed
                except McpRuntimeError:
                    config = None  # 与 _inventory 同链：parse 或 env 校验失败都归 None
            return McpServerDetail(item=item, config=config)
```

`src/agent/cli.py` 加命令（放在 `mcp list` 之后）：

```python
@mcp_app.command("show")
def mcp_show(
    server_id: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory."),
) -> None:
    """Show one MCP server's static config without starting it."""
    try:
        detail = _mcp_store(cwd).describe(server_id)
    except McpRuntimeError as exc:
        _print_mcp_error(exc)
        raise typer.Exit(code=1) from exc
    item = detail.item
    console.file.write(f"server_id: {item.server_id}\n")
    console.file.write(f"source: {item.source}\n")
    console.file.write(f"enabled: {str(item.enabled).lower()}\n")
    console.file.write(f"status: {item.status}\n")
    if item.message:
        console.file.write(f"message: {_bounded_text(item.message)}\n")
    if detail.config is not None:
        console.file.write(f"command: {detail.config.command}\n")
        console.file.write(f"args: {list(detail.config.args)}\n")
        console.file.write(f"pass_env: {list(detail.config.pass_env)}\n")
        console.file.write(f"cwd: {detail.config.cwd}\n")
```

（`pass_env` 只含环境变量名；`describe` 全程不触碰 `McpStdioRuntime`。）

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_mcp_config.py tests/test_cli.py -q`
Expected: 全部 passed

- [x] **Step 5: Commit**

```bash
git add src/agent/mcp_config.py src/agent/cli.py tests/test_mcp_config.py tests/test_cli.py
git commit -m "feat: add mcp show command"
```

---

### Task 4: 顶层 doctor 聚合

**Files:**
- Modify: `src/agent/cli.py`（`_print_doctor` 末尾）
- Test: `tests/test_cli.py`（追加）

**Interfaces:**
- Consumes: `McpConfigStore.inventory()`、`SkillStore.doctor(default_skills=...)`（均既有）。
- Produces: doctor 末尾摘要行（格式见 Step 3）；读取失败时单行 error，不改退出码。

- [x] **Step 1: 写失败测试**

`tests/test_cli.py` 追加：

- `test_doctor_reports_extension_summary_when_empty`：空 workspace 下 `config doctor` 输出含 `mcp servers: 0 total, 0 enabled, 0 invalid, 0 orphan` 与 `skills: ` / `healthy=` 摘要行，exit 0。
- `test_doctor_counts_mcp_servers`：set 一个 server 后输出 `mcp servers: 1 total, 1 enabled, 0 invalid, 0 orphan` 与 `mcp detail: agent mcp doctor`。
- `test_doctor_extension_summary_survives_store_error`：monkeypatch `agent.cli.McpConfigStore.inventory` 抛 `McpRuntimeError` → 输出含 `mcp inventory error: `，exit 0。

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_cli.py -q -k "extension_summary or counts_mcp"`
Expected: FAIL（无摘要行）

- [x] **Step 3: 最小实现**

`_print_doctor` 末尾（config warnings 循环之后）追加：

```python
    try:
        mcp_items = McpConfigStore(cwd).inventory()
    except McpRuntimeError as exc:
        console.file.write(f"mcp inventory error: {_bounded_text(str(exc))}\n")
    else:
        enabled = sum(1 for item in mcp_items if item.enabled)
        invalid = sum(1 for item in mcp_items if item.status == "invalid")
        orphan = sum(1 for item in mcp_items if item.status == "orphan")
        console.file.write(
            f"mcp servers: {len(mcp_items)} total, {enabled} enabled, {invalid} invalid, {orphan} orphan\n"
        )
        if mcp_items:
            console.file.write("mcp detail: agent mcp doctor\n")
    try:
        report = SkillStore(cwd).doctor(default_skills=config.default_skills)
    except SkillError as exc:
        console.file.write(f"skills doctor error: {_bounded_text(str(exc))}\n")
    else:
        console.file.write(
            f"skills: {len(report.items)} total, {len(report.problems)} problems, healthy={str(report.healthy).lower()}\n"
        )
        console.file.write("skills detail: agent skills doctor\n")
```

（`McpConfigStore`/`SkillStore`/`SkillError` 均已在 cli.py import。直接沿用既有
helper：`_mcp_store(cwd)` 与 `_skill_store(cwd)`（cli.py:533、688，接受
`Path | None`；`_print_doctor` 传入的 `cwd` 已是 resolved Path，可直接传）。上面
代码块中的 `McpConfigStore(cwd)`/`SkillStore(cwd)` 相应写作
`_mcp_store(cwd)`/`_skill_store(cwd)`。）

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_cli.py -q`
Expected: 全部 passed（既有 doctor 断言只增行不受影响）

- [x] **Step 5: Commit**

（已核实 `tests/test_docs.py` 无 doctor 输出断言，无需相邻回归。）

```bash
git add src/agent/cli.py tests/test_cli.py
git commit -m "feat: aggregate extension status in doctor"
```

---

### Task 5: 共享 config 写模块与 web 委托

**Files:**
- Create: `src/agent/config_write.py`
- Modify: `src/agent/config.py`（`_validate_value`/`_normalize_value` 改公开名，更新内部调用）
- Modify: `src/agent/web/settings.py`（委托共享模块）
- Test: `tests/test_config_write.py`（新建）；`tests/test_web.py` 断言零修改

**Interfaces:**
- Consumes: `config.validate_value(key, value, path)`、`config.normalize_value(key, value)`（重命名后）；`_user_store.atomic_replace_bytes`。
- Produces: `agent.config_write.save_project_config(workspace: Path, updates: dict[str, Any]) -> Path`；`agent.config_write.remove_project_config_keys(workspace: Path, keys: Iterable[str]) -> Path`。语义：键必须在 `KNOWN_KEYS`；序列值规格化为 tuple 后验证；`sandbox="danger-full-access"`/`approval="never"` 抛 `ValueError`（文案见 Step 3）；写入原子，失败保留旧文件；`remove` 对项目 config 不存在的键抛 `ValueError`。

- [x] **Step 1: 写失败测试**

新建 `tests/test_config_write.py`：

- `test_save_writes_project_config_atomically`：`save_project_config(tmp, {"model": "m2"})` 后 `load_config` 读到 `m2`，其余键不变。
- `test_save_accepts_list_and_tuple_sequences`：`{"default_skills": ["a", "b"]}` 与 `("a", "b")` 均成功且文件内为 TOML list。
- `test_save_strips_string_values`：`{"model": " m "}` 存为 `"m"`；`{"default_skills": [" a "]}` 项存为 `"a"`（保持 web 委托前的 strip 行为）。
- `test_save_rejects_unknown_key`：`{"nope": 1}` → `ValueError`，文件不变。
- `test_save_rejects_invalid_value_and_keeps_file`：先写合法值，再用非法值（如 `{"mode": "bogus"}`）断言抛错且文件内容与前一次一致。
- `test_save_rejects_danger_sandbox_and_never_approval`：两个值各断言 `ValueError` 文案（见 Step 3）。
- `test_remove_deletes_key_and_falls_back`：set 后 remove，`load_config` 回落默认值。
- `test_remove_missing_key_raises`：`ValueError`。

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_config_write.py -q`
Expected: FAIL（`ModuleNotFoundError: agent.config_write`）

- [x] **Step 3: 实现**

1. `src/agent/config.py`：`_validate_value` → `validate_value`、`_normalize_value` → `normalize_value`（模块内 3 处调用同步改；无外部引用，已核实）。
2. 新建 `src/agent/config_write.py`：

```python
from __future__ import annotations

import json
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agent import _user_store
from agent.config import KNOWN_KEYS, ConfigError, normalize_value, validate_value

_SEQUENCE_KEYS = {"default_skills", "allowed_commands", "enabled_hooks", "blocking_hooks"}
_REJECTED_PROJECT_VALUES = {
    ("sandbox", "danger-full-access"): "project config cannot widen sandbox permissions; edit the global config by hand instead.",
    ("approval", "never"): "project config cannot disable approvals; edit the global config by hand instead.",
}


def save_project_config(workspace: Path, updates: dict[str, Any]) -> Path:
    prepared: dict[str, Any] = {}
    for key, value in updates.items():
        if key not in KNOWN_KEYS:
            raise ValueError(f"Unknown config key: {key}.")
        if key in _SEQUENCE_KEYS and isinstance(value, (list, tuple)):
            value = tuple(item.strip() if isinstance(item, str) else item for item in value)
        elif isinstance(value, str):
            value = value.strip()  # 保持 web 委托前的 strip 行为；base_url 允许空串语义不变
        rejected = _REJECTED_PROJECT_VALUES.get((key, value if isinstance(value, str) else None))
        if rejected is not None:
            raise ValueError(rejected)
        validate_value(key, value, None)
        prepared[key] = normalize_value(key, value)
    config_path = _project_config_path(workspace)
    existing = _read_project_config(config_path)
    existing.update(prepared)
    return _publish(config_path, existing)


def remove_project_config_keys(workspace: Path, keys: Iterable[str]) -> Path:
    config_path = _project_config_path(workspace)
    existing = _read_project_config(config_path)
    for key in keys:
        if key not in KNOWN_KEYS:
            raise ValueError(f"Unknown config key: {key}.")
        if key not in existing:
            raise ValueError(f"Key is not set in project config: {key}.")
        del existing[key]
    return _publish(config_path, existing)
```

（`_project_config_path`、`_read_project_config`、`_dump_toml`、`_toml_value`、`_publish` 从 `web/settings.py` 移入本模块——`_publish` 即现有 mkdir + `atomic_replace_bytes` + `UserStoreError → OSError` 包装。）

3. `src/agent/web/settings.py`：删除 `_read_project_config`、`_dump_toml`、`_toml_value` 与 `build_save_config_payload` 中的读改写段；`build_save_config_payload` 变为：

```python
def build_save_config_payload(workspace: Path, request: dict[str, Any]) -> dict[str, Any]:
    root = workspace.resolve()
    updates = _validated_config_updates(request)
    save_project_config(root, updates)
    payload = build_config_payload(root)
    payload["status"] = "ok"
    return payload
```

（发布失败的 `OSError` 包装移入共享 `_publish`，消息保持
`Could not save project config {config_path}.` 逐字不变——`tests/test_ui.py:253`
以 `match="Could not save project config"` 锁定该文案。）

`_validated_config_updates` 保留：键白名单（浏览器不暴露 hooks/allowed_commands 等键）、`approval`/`sandbox` 的浏览器收紧与其现有文案、`provider` 白名单文案；删除与 `validate_value` 重复的纯类型检查（model/mode/bool/default_skills 各分支的 isinstance 检查改为直接放行，由共享模块验证）。`ConfigError` 是 `ValueError` 子类，server 现有 `except ValueError` 路径不变。

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_config_write.py tests/test_web.py tests/test_config.py -q`
Expected: 全部 passed；`tests/test_web.py` 零修改

- [x] **Step 5: 全量回归**

Run: `python -m pytest -q`
Expected: 全部 passed

- [x] **Step 6: Commit**

```bash
git add src/agent/config.py src/agent/config_write.py src/agent/web/settings.py tests/test_config_write.py
git commit -m "refactor: share project config write path"
```

---

### Task 6: `agent config set/unset`

**Files:**
- Modify: `src/agent/cli.py`（两个新命令）
- Test: `tests/test_cli.py`（追加）

**Interfaces:**
- Consumes: Task 5 的 `save_project_config`/`remove_project_config_keys`。
- Produces: `agent config set KEY VALUE... [--cwd]`、`agent config unset KEY [--cwd]`。VALUE 解析：list 键收多 VALUE；bool 键收 `true|false`；int 键收十进制正整数；enum/str 键收单 VALUE。成功后重载 config 并打印 `saved: <path>` 与全部 `config warning:` 行。

- [x] **Step 1: 写失败测试**

`tests/test_cli.py` 追加：

- `test_config_set_scalar_roundtrip`：`config set model my-model` → exit 0，`config show` 含 `model: my-model`。
- `test_config_set_bool_and_int`：`config set dry_run true`、`config set memory_max_items 9` 各 roundtrip；`config set dry_run yes` → exit 1。
- `test_config_set_list_key_takes_multiple_values`：`config set default_skills a b` → `config show` 含 `default_skills: ['a', 'b']`。
- `test_config_set_scalar_rejects_multiple_values`：`config set model a b` → exit 1。
- `test_config_set_rejects_danger_values`：`config set sandbox danger-full-access` 与 `config set approval never` → exit 1，输出含 `edit the global config by hand`。
- `test_config_set_prints_new_warnings`：`config set enabled_hooks typo` → exit 0 且输出含 `config warning: Unknown hook 'typo'`（写成功、警告即时可见）。
- `test_config_unset_falls_back`：set 后 unset，`config show` 回落默认；unset 未设键 → exit 1。

- [x] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_cli.py -q -k "config_set or config_unset"`
Expected: FAIL（无 set/unset 命令）

- [x] **Step 3: 最小实现**

`src/agent/cli.py`（`config_doctor` 之后）：

```python
_BOOL_KEYS = {"dry_run", "memory_auto_write", "web_search_enabled", "computer_read_enabled", "native_tools"}
_INT_KEYS = {"memory_max_items", "max_consecutive_errors"}
_LIST_KEYS = {"default_skills", "allowed_commands", "enabled_hooks", "blocking_hooks"}


def _parse_config_value(key: str, values: list[str]):
    if key in _LIST_KEYS:
        return tuple(values)
    if len(values) != 1:
        raise ValueError(f"Key {key} takes exactly one value.")
    raw = values[0]
    if key in _BOOL_KEYS:
        if raw not in {"true", "false"}:
            raise ValueError(f"Key {key} expects true or false.")
        return raw == "true"
    if key in _INT_KEYS:
        if not raw.isdigit():
            raise ValueError(f"Key {key} expects a positive integer.")
        return int(raw)
    return raw


@config_app.command("set")
def config_set(
    key: str,
    values: list[str] = typer.Argument(...),
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project config."),
) -> None:
    """Set one key in the project config with validation and atomic write."""
    workspace = (cwd or Path.cwd()).resolve()
    try:
        value = _parse_config_value(key, values)
        path = save_project_config(workspace, {key: value})
    except (ValueError, ConfigError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"saved: {path}", soft_wrap=True)
    try:
        _config, diagnostics = load_config(workspace)
    except ConfigError as exc:
        # 写入已验证成功；reload 失败只可能来自其他文件（如损坏的全局 config）
        console.print(f"config warning: {exc}")
        return
    for warning in diagnostics.warnings:
        console.print(f"config warning: {warning}")


@config_app.command("unset")
def config_unset(
    key: str,
    cwd: Path | None = typer.Option(None, "--cwd", help="Workspace directory for project config."),
) -> None:
    """Remove one key from the project config."""
    workspace = (cwd or Path.cwd()).resolve()
    try:
        path = remove_project_config_keys(workspace, [key])
    except (ValueError, ConfigError, OSError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=1) from exc
    console.print(f"saved: {path}", soft_wrap=True)
```

import 区加 `from agent.config_write import remove_project_config_keys, save_project_config`。

- [x] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_cli.py -q`
Expected: 全部 passed

- [x] **Step 5: Commit**

```bash
git add src/agent/cli.py tests/test_cli.py
git commit -m "feat: add config set and unset commands"
```

---

### Task 7: 收尾——文档同步与全量门禁

**Files:**
- Modify: `CHANGELOG.md`、`README.md`、`docs/roadmap-progress.md`、`docs/project-vnext-direction.md`、`tests/test_docs.py`、spec 状态行

**Interfaces:**
- Consumes: Task 1-6 全部完成。
- Produces: 文档与验收证据。

- [x] **Step 1: CHANGELOG 与 README**

- `CHANGELOG.md` 的 `## Unreleased` 顶部加一条：hooks 加载警告与 `hooks list`、`mcp show`、doctor 扩展摘要、`config set/unset` 与共享 config 写路径；注明 Workbench 写接口、reconnect、marketplace 仍不在范围。
- `README.md` 在既有 mcp/skills/config 命令文档处补 `agent hooks list`、`agent mcp show`、`agent config set`、`agent config unset` 及一句用途说明。

- [x] **Step 2: roadmap、方向文档与 test_docs 同步**

三者同一提交内更新（`tests/test_docs.py:786` 硬断言 roadmap 措辞）：

- `docs/roadmap-progress.md`：vNext 表 `Full Project vNext ecosystem` 行的 next gap 更新——剩余 Phase 2 management surface 完成；`Next Project vNext slice` 段落改为指向下一主线（Frontend vNext 阶段 0 或 Phase 3，按方向文档措辞，不宣布未批准的新工作）；`Completed slice:` 追加一行（保留既有各行文字不动，`test_docs` 多处按行断言）。
- `docs/project-vnext-direction.md` "下一次正式开工的默认顺序" 第 2 条：追加本 spec 为已完成。
- `tests/test_docs.py`：`test_managed_extension_lifecycle_docs_record_commands_scope_and_status` 中
  `assert "Next Project vNext slice: the remaining Phase 2 management surface" in roadmap`
  改为断言新的 next-slice 措辞；文件末尾追加本切片 docs 测试（house 模式，紧凑版）：

```python
def test_extension_management_closeout_docs_record_commands_and_status() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    spec = (
        ROOT / "docs" / "superpowers" / "specs" / "2026-07-23-extension-management-closeout-design.md"
    ).read_text(encoding="utf-8")

    for command in ("agent hooks list", "agent mcp show", "agent config set", "agent config unset"):
        assert command in readme
    assert "config set" in changelog
    assert "状态：已实施" in spec
```

- [x] **Step 3: spec 状态**

spec 头部 `- 状态：已批准，待实施` 改为 `- 状态：已实施（全量门禁通过）`。

- [x] **Step 4: 全量门禁**

Run: `python -m pytest -q`
Expected: 全部 passed（基线 986 + 新增 ~30）

Run: `python -m agent.cli doctor`
Expected: exit 0，含新摘要行

Run: `git diff --check`
Expected: 无输出

- [x] **Step 5: Commit**

```bash
git add CHANGELOG.md README.md docs/roadmap-progress.md docs/project-vnext-direction.md tests/test_docs.py docs/superpowers/specs/2026-07-23-extension-management-closeout-design.md
git commit -m "docs: close extension management closeout slice"
```
