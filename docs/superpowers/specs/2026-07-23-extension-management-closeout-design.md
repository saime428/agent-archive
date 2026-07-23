# 设计：扩展管理面收尾

- 日期：2026-07-23
- 状态：已实施（全量门禁通过）
- 上位方向：[Project vNext 总方向](../../project-vnext-direction.md)（seam：Extension Lifecycle Interface 与 Operations 收尾）

## 背景

阶段 2 主线（managed MCP/Skills 生命周期、Provider 能力声明）完成后，扩展闭环
（校验 → 启停 → 诊断 → 更新/卸载）仍留四个小缺口。它们单独都不够一份 spec 的
体量，合并为一份收尾切片；做完即可宣告阶段 2 后端管理面闭合。

代码事实：

1. **Hooks 零管理面**（`agent/core/hooks.py`）：只有 `audit`、
   `before_tool_format`、`fail`（测试用）三个硬编码 builtin。config 的
   `enabled_hooks`/`blocking_hooks` 只验证"非空字符串列表"
   （`config.py::_validate_value`），填错名字加载时不报错，要到 run 时才产出
   error record；若 typo 出现在 `blocking_hooks`，每次 run 直接被阻断，且没有
   任何命令能预先发现。没有 `hooks list`。
2. **`mcp show` 缺失**：Skills 有 `list/show`，MCP 只有 `list`（单行摘要）。
   查看一个 server 的 command/args/pass_env/cwd 要手动翻 `mcp.toml` 或
   fragments 目录。`McpConfigStore` 没有单 server 详情访问器。
3. **顶层 `doctor` 不聚合扩展状态**（`cli.py::_print_doctor`）：完全不提
   MCP/Skills，用户要分别跑 `agent mcp doctor`、`agent skills doctor` 才知道
   全貌。
4. **CLI 无受控 config 写**：Workbench 已有项目 config 写路径
   （`web/settings.py::build_save_config_payload`：键白名单 + 原子发布），CLI
   侧没有对等命令，改 `default_skills`、`enabled_hooks` 等仍靠手编 TOML。
   `web/settings.py::_validated_config_updates` 还是 `config.py::_validate_value`
   的第二份重复实现，白名单与验证规则已经开始漂移（web 自带 approval/sandbox
   收紧，但 model/mode 等验证逻辑重复）。

## 目标

1. Hooks 获得最小管理面：`agent hooks list` 一眼看到可用 hook 与启用状态；
   config 引用未知 hook 名在**加载时**出警告，不再等到 run 时。
2. `agent mcp show ID` 与 Skills 的 `show` 对齐：不启动进程，显示单 server 的
   来源、启停、静态状态与解析后的配置字段。
3. `agent doctor` 增加 MCP/Skills 一段式摘要（静态、不起进程），指向专用
   doctor 命令。
4. `agent config set/unset` 提供受控项目 config 写；验证逻辑收敛到 config 层
   单一实现，web 与 CLI 成为同一写 seam 的两个 Adapter。
5. 行为兼容：除新增命令、新增警告与 doctor 新增输出行外，现有 run 行为、
   config 文件格式、run/session 数据、web `/api/config/save` 对外行为均不变。

## 设计

### 1. Hooks 最小管理面

**已知 hook 名集合**（`agent/config.py`）：

- 新增 `KNOWN_HOOK_NAMES: frozenset[str]`，与 `VALID_VALUES` 并列。config.py
  保持叶子模块（只依赖 stdlib），不 import `core.hooks`；一致性由契约测试保证
  （`tests/test_hooks.py`：`BUILTIN_HOOKS.keys() == KNOWN_HOOK_NAMES`），与
  `VALID_VALUES["provider"]` ↔ `PROVIDER_REGISTRY` 的既有模式相同。

**加载时警告**（`config.py::load_config` 诊断链）：

- `enabled_hooks` 或 `blocking_hooks` 含未知名 → `diagnostics.warnings` 增行
  `Unknown hook '<name>' in <key>; known hooks: <sorted list>.`
- `blocking_hooks` 含 `enabled_hooks` 之外的名字 → 警告（该项永不触发）。
- 用警告不用硬错误：与"未知 config 键 → 警告"的既有先例一致；typo hook 目前
  在运行时仍能跑（非阻塞时只记日志），硬错误会让原本可加载的配置直接失败，
  违反兼容护栏。doctor 已打印全部 config warnings，自动获得此诊断。

**`agent hooks list`**（`cli.py`，新 `hooks_app`）：

- 无参数；输出每个 builtin hook 一行：`name\tenabled|disabled\tblocking|-`，
  之后对 config 中引用的未知名各输出一行 `name\tunknown\t...`。
- 只读 config 与 `BUILTIN_HOOKS`，无副作用；未知名存在时仍 exit 0（诊断由
  警告承担，list 是展示面）。

**既有展示面补齐**：`config show` 与 `_print_doctor` 目前打印
`default_skills`/`allowed_commands` 但不打印 hooks 键；各补两行
`enabled_hooks`/`blocking_hooks`，与其他 list 键格式一致。

不做 `hooks enable/disable` 专用命令：`config set enabled_hooks ...`（见 §4）
已覆盖同一写路径，两个入口写同一个键只会制造歧义。

### 2. `agent mcp show ID`

**`McpConfigStore.describe(server_id) -> McpServerDetail`**（`mcp_config.py`）：

- 新 frozen dataclass `McpServerDetail`：`item: McpInventoryItem` +
  `config: McpServerConfig | None`。`config` 在片段无法解析为
  `McpServerConfig` 时为 None：invalid、orphan，以及 disabled 且片段不可解析
  （lifecycle spec 允许 disabled 的坏 command 存在）；disabled 但可解析时正常
  返回 config。
- 实现走既有 `_locked()` + `_read_snapshot()` 快照路径，与
  `validate(server_id)` 同源；未知 ID 抛既有 `McpRuntimeError`。不起进程。

**CLI 输出**（`cli.py`）：

- 逐行 `key: value`：`server_id`、`source`、`enabled`、`status`、`message`
  （有则显示，走 `_bounded_text`）、`command`、`args`、`pass_env`（**只打印
  环境变量名，永不解析值**）、`cwd`。
- 未知 ID：`_print_mcp_error` + exit 1，与其他 mcp 子命令一致。

### 3. 顶层 doctor 聚合

`cli.py::_print_doctor` 末尾（config warnings 之后）追加两段：

- MCP：读 `McpConfigStore.inventory()`（静态、不起进程），输出
  `mcp servers: <total> total, <enabled> enabled, <invalid> invalid, <orphan> orphan`；
  仅在有 server 或有错误时追加提示行 `mcp detail: agent mcp doctor`。
- Skills：读 `SkillStore.doctor(default_skills=...)`（目录扫描，无进程），输出
  `skills: <total> total, <problems> problems, healthy=<bool>` 与
  `skills detail: agent skills doctor`。
- 任一读取抛异常 → 单行 `mcp inventory error: ...` / `skills doctor error: ...`
  （`_bounded_text`），**不改变 doctor 退出码**：顶层 doctor 的失败语义保持
  "config 加载失败才 exit 1"，扩展问题属于诊断输出。

### 4. `agent config set/unset`（受控项目 config 写）

**Seam 决策（design it twice）：**

| 方案 | 判定 |
| --- | --- |
| A. 抽共享写模块 `agent/config_write.py`，web 与 CLI 都是 caller | ✅ 两个真实 Adapter，验证单一事实源 |
| B. CLI import `web.settings` | ❌ CLI 依赖 web 层，层次倒置 |
| C. CLI 复制一份验证 | ❌ 白名单/规则第三份漂移 |

**共享模块 Interface**（`agent/config_write.py`，新文件）：

- `save_project_config(workspace: Path, updates: dict[str, Any]) -> Path`：
  读现有 `.agent/config.toml`（沿用 web 的 `_read_project_config` 逻辑，移入
  本模块）→ 合并 `updates` → `_dump_toml`（自 web/settings.py 移入）→
  `_user_store.atomic_replace_bytes` 原子发布 → 返回写入路径。键值验证委托
  `config.py::_validate_value` + `_normalize_value`（改为模块公开名
  `validate_value`/`normalize_value`，行为不变）。注意 `_validate_value` 的
  `path=None` 分支期望序列值为 tuple；共享模块在验证前把序列值统一规格化为
  tuple（web 传入的 JSON list 与 CLI 多 VALUE 同路径），避免两个 caller 各自
  转换。
- `remove_project_config_keys(workspace: Path, keys: Iterable[str]) -> Path`：
  同一读改写路径，删除存在的键。
- 语义护栏（在共享模块统一执行，与加载语义对齐）：项目 config 写入
  `sandbox="danger-full-access"` 或 `approval="never"` 直接拒绝
  （`ValueError`）——加载时本来就会忽略并警告这两个值，写进去只会制造
  "写成功但不生效"的假象。

**web 改造**（`web/settings.py`，对外行为不变）：

- `build_save_config_payload` 保留浏览器特有收紧（键白名单小集、approval 仅
  `risky-confirm|always`、sandbox 仅 `read-only|workspace-write`），验证与写入
  委托共享模块；`_validated_config_updates` 中与 `_validate_value` 重复的
  类型/枚举检查删除，只留浏览器策略差异。错误消息文案保持现有断言兼容
  （实施 plan 逐条核对 `tests/test_web.py`）。

**CLI 命令**（`cli.py`）：

- `agent config set KEY VALUE... [--cwd]`：KEY 必须在 `KNOWN_KEYS`；list 键
  （`default_skills`、`allowed_commands`、`enabled_hooks`、`blocking_hooks`）
  接受多个 VALUE，标量键恰好一个 VALUE（bool 键收 `true|false`，int 键收正
  整数字符串）；成功后重新 `load_config` 并打印新产生的 warnings（含 §1 的
  未知 hook 警告），形成写后即时反馈。
- `agent config unset KEY [--cwd]`：从项目 config 删除该键，回落全局/默认。
- 只写**项目** config（`<cwd>/.agent/config.toml`），与 web 写路径一致；
  global config 仍为手编。
- CLI 键集合为 `KNOWN_KEYS` 全量（含 `allowed_commands`、hooks 键）：本地
  CLI 用户与手编文件同信任级，收紧只针对浏览器面。上述 sandbox/approval
  危险值护栏对 CLI 同样生效。

## 消费者

| 消费者 | 用到的面 |
| --- | --- |
| CLI 用户 | `hooks list`、`mcp show`、doctor 聚合、`config set/unset` |
| `agent doctor` / `release doctor` | config warnings 自动含 hook 警告 |
| `web/settings.py`（既有） | 共享 config 写模块的第二个 Adapter，行为不变 |
| 未来 Frontend vNext | 不在本切片：HTTP 暴露归前端切片，届时复用同一模块 |

## 非目标

- `hooks enable/disable` 专用命令与用户自定义 hook 脚本/外部 hook 加载；
  hooks 仍是受控 builtin 集合，不演变成第二套工具系统。
- MCP reconnect/restart、Streamable HTTP/SSE transport、resources/prompts。
- Workbench/HTTP 新端点（扩展清单只读暴露归前端 vNext 切片）。
- Marketplace、registry、远程来源、签名。
- global config 写命令；secrets 读写与 redaction 行为变化。
- 新第三方依赖；config 文件格式与 run/session 数据迁移。

## 兼容与迁移

- config 文件格式不变；无数据迁移。
- 新警告只追加进 `diagnostics.warnings`，现有消费者按行打印，天然兼容。
- doctor 与 `config show` 输出只增行不改行；`release doctor` 不变。
- web `/api/config/save` 请求/响应契约与拒绝语义不变（内部改为委托共享模块，
  错误文案回归测试锁定）。
- `mcp show`、`hooks list`、`config set/unset` 均为新命令，无旧行为可破坏。

## 验收标准

### Hooks

- `enabled_hooks`/`blocking_hooks` 含未知名 → `load_config` 警告可见于
  `agent doctor` 与 `agent config show`；已知名无警告。
- `blocking_hooks` 含未启用名 → 警告。
- `hooks list` 输出全部 builtin 与 config 引用的未知名；无副作用。
- `config show` 与 doctor 输出 `enabled_hooks`/`blocking_hooks` 行。
- 契约测试：`BUILTIN_HOOKS.keys() == KNOWN_HOOK_NAMES`。

### MCP show

- manual/managed/enabled/disabled/invalid/orphan 各形态输出正确字段；
  `pass_env` 只出现变量名；未知 ID exit 1。
- `describe` 路径不 import/构造 `McpStdioRuntime`，不产生子进程。

### doctor 聚合

- 空状态（无任何扩展）输出零计数摘要且 exit 0；有 invalid/orphan 时计数正确；
  store 读取失败输出单行 error 且退出码不变。

### config set/unset

- 每个键类别（枚举、bool、int、字符串、list）set 后 `config show` 反映新值；
  非法值拒绝且文件不变（原子性：写失败保留旧文件）。
- `sandbox=danger-full-access`、`approval=never` 被 CLI 与 web 一致拒绝。
- `unset` 删除项目键后回落全局/默认值；unset 不存在的键明确报错。
- web `/api/config/save` 全部现有测试不改断言通过（重构不漏行为）。

### 全局门禁

- 全量 pytest、`agent doctor`、`git diff --check` 通过。
- 测试临时目录一律用 pytest `tmp_path` 或 `D:\CodexScratch`，验收后清理。
- 不新增依赖；`git status` 无计划外文件。
