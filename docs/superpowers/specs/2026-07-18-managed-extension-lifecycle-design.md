# 设计：可管理的本地 MCP 与 Skills 生命周期

- 日期：2026-07-18
- 状态：已确认，实施计划已审查
- 上位方向：[Project vNext 总方向](../../project-vnext-direction.md)
- 实施计划：[可管理的本地 MCP 与 Skills 生命周期](../plans/2026-07-18-managed-extension-lifecycle.md)
- 前置实现：[stdio MCP 动态工具集成](2026-07-17-stdio-mcp-dynamic-tools-design.md)
- 前置加固：[MCP Server 故障隔离](2026-07-18-mcp-server-fault-isolation-design.md)
- 性质：Project vNext 阶段 2“可管理生态”的第一份后端 spec

## 一句话目标

在不建设 Marketplace、远程 registry 或假管理 UI 的前提下，让用户通过 CLI 完成 MCP 的安全配置、启停与诊断，以及 Skills 的本地校验、安装、启停、更新、打包和卸载；运行时继续只消费冻结后的有效快照。

## 当前事实与缺口

### MCP

- `McpStdioRuntime` 已能从用户级 `~/.agent/mcp.toml` 读取最多 8 台 stdio Server，并完成 initialize、动态 Tool catalog、安全链、故障隔离与进程清理。
- 配置目前只能手工编辑；没有安全的增改、启停、静态校验或显式 live doctor。
- Python 标准库 `tomllib` 只读。直接重写用户手写的 `mcp.toml` 会丢失注释、排序和未知人工排版，不能作为默认管理方案。
- Runtime 按进程冻结配置；现有 CLI/Workbench 不支持热重载，这个不变量应保留。

### Skills

- `core/skills.py` 已发现 package builtin 与项目 `.agent/skills/*/SKILL.md`，并在选择后按预算加载正文、限制 `allowed_tools`，把全部 Skill 文本标为不可信上下文。
- 当前没有用户级安装目录，也没有 validate、enable/disable、update、package 或 remove。
- `SKILL.md` frontmatter 只有 `name`、`description` 与 `allowed_tools`；本期没有可靠 registry/version 来源，不能伪造在线更新能力。
- 项目 Skill 当前可以覆盖同名 builtin。该兼容行为本期保留，但新的用户安装不得再引入静默同名覆盖。

## 本期目标

1. MCP 手写配置继续兼容且不被管理命令重写；新管理命令写入 Agent 自己拥有的独立配置片段。
2. MCP 可静态列出、校验、启停、增改、移除和显式 live diagnose；只有 diagnose 会启动 Server。
3. Skills 增加用户级本地安装源，并完成 validate → install → enable/disable → update → package → remove 闭环。
4. 所有用户级写入具备路径约束、互斥、先校验后发布和失败回滚；运行时看不到半写状态。
5. MCP 与 Skills 的运行语义继续复用现有 runtime、Skill loader、Tool catalog、policy、approval、redaction 和 trace，不建立第二条执行链。
6. CLI 是首个管理 Adapter；Module Interface 保持与未来 HTTP/Workbench Adapter 可复用，但本期不增加浏览器写接口。

## 关键设计决定

### 1. 不创建通用 `ExtensionManager`

MCP 配置的核心问题是命令授权、环境、进程与协议健康；Skills 的核心问题是文件包、上下文加载与 Tool 限制。两者只有生命周期词汇相似，数据与失败模式不同。

因此本期保持两个深 Module：

- **MCP Config Module**：拥有配置来源合并、静态校验、启停状态和受控写入；`McpStdioRuntime` 只消费它给出的 enabled config snapshot。
- **Skills Module**：拥有候选包校验、用户安装目录、启停状态、更新/回滚、打包和现有正文加载。

两者可复用少量内部的路径、锁和原子替换 helper，但不暴露统一 CRUD Interface，不增加 `kind=mcp|skill` 的浅转发层。等第三类扩展出现且真实调用者需要统一管理时再抽象。

### 2. 管理面与运行面分开

- `list`、`validate`、`set/install`、`enable/disable`、`update/package/remove` 是管理操作，不启动 MCP Server，不加载 Skill 正文进模型。
- `mcp doctor` 是用户显式触发的 live probe，会启动当前 enabled Server，调用现有 discovery，再在唯一 `finally` 关闭 Runtime。
- 普通 run/chat/Workbench 只在进程首次 discovery 时读取一次 enabled snapshot。管理命令成功后必须重启已有 Workbench；不做热重载或隐式重启。
- install/enable 不等于选择 Skill。新 Skill 不自动加入 `default_skills`，也不改变当前 run。

### 3. CLI 先行，浏览器写入后置

MCP `command` 代表本机代码执行授权，Skill 包也是不可信外部输入。现有 Workbench 没有为用户级扩展写入设计独立的确认与来源展示流程，因此本期：

- 增加 CLI 管理命令；
- 不增加 Workbench 页面、POST `/api/mcp/*`、POST `/api/skills/*` 或 Hub；
- 不把项目配置或网页请求当成 MCP 启动授权；
- 后续前端 spec 只能复用本期 Module Interface，并另行设计用户确认、CSRF/本地来源和状态展示。

## MCP 配置与状态

### 存储布局

```text
~/.agent/
  mcp.toml                 # 现有手写配置，兼容且管理命令只读
  mcp.d/
    <server-id>.toml       # Agent 管理的单 Server 配置片段
  mcp-state.json           # Agent 管理的启停覆盖
```

受管片段不使用动态 `[servers.<id>]` table；Server ID 来自安全文件名，文件内容只包含现有字段：

```toml
command = "example-server"
args = ["--stdio"]
pass_env = ["EXAMPLE_TOKEN"]
cwd = "config"
```

`mcp-state.json` 的首版格式固定为：

```json
{"version":1,"disabled":["example"]}
```

规则：

- 先读取手写 `mcp.toml`，再读取按 Server ID 排序的 `mcp.d/*.toml`；同一 ID 出现在两个来源时 fail closed，不采用 last-wins。
- managed Server ID 沿用现有 ASCII 字母/数字/`_`/`-` 规则，并限制为 1–64 字符；同时拒绝 Windows 设备保留名、尾随点/空格和大小写折叠后的文件名冲突。手写配置保持现有兼容语义。
- `mcp-state.json` 是高信任用户状态覆盖，可禁用任一来源的 Server，但不能增加或修改命令。
- 状态中名称合法、但当前没有对应 manual/managed 来源的 disabled 项是 orphan：普通 Runtime 忽略且不计入 Server 上限，`list/doctor` 显式报告；`enable/disable` 对不存在的来源返回非零。新建 `set` 会清除同名 orphan 并以 enabled 发布，替换现有 managed Server 则保留原 enabled/disabled 状态；`remove` 可幂等清理同名 managed 来源或 state-only orphan。
- disabled Server 仍必须有合法 ID 和可解析 TOML；跳过命令解析、PATH/env 检查和进程启动，使用户能先禁用一个已损坏或暂时缺依赖的配置。
- enabled Server 继续走现有完整 `_parse_server_config` 安全校验；Server 总数、PATH 净化、workspace command 拒绝、`pass_env` 和 `cwd` 语义不变。
- 配置来源与 enabled/disabled 可出现在显式管理诊断中，但普通 run summary、trace 和 session 不记录 command、argv、cwd、环境变量名或值。

### CLI Interface

新增 `agent mcp` 命令组：

```text
agent mcp list [--cwd PATH]
agent mcp validate [SERVER_ID] [--cwd PATH]
agent mcp set SERVER_ID --command COMMAND [--arg VALUE ...] [--pass-env NAME ...] [--server-cwd config|workspace] [--cwd PATH]
agent mcp enable SERVER_ID [--cwd PATH]
agent mcp disable SERVER_ID [--cwd PATH]
agent mcp remove SERVER_ID [--cwd PATH]
agent mcp doctor [--cwd PATH]
```

- `list` 不启动进程，输出 ID、来源 `manual|managed`、enabled 状态与静态校验状态；默认不回显完整 argv。
- `validate` 只做配置、路径、字段、环境变量存在性与信任边界检查，不执行命令。
- `set` 对受管片段执行 create-or-replace；候选必须先通过与 Runtime 相同的校验，再原子发布。新建项 enabled，替换项保留原状态。若 ID 来自手写 `mcp.toml`，拒绝覆盖并提示用户手工迁移。
- `enable/disable` 只更新状态覆盖，不启动或停止其他进程；已有 Workbench 在重启后生效。
- `remove` 只删除受管片段并清理对应状态。手写来源拒绝删除，避免破坏用户文件。
- `doctor` 复用 `McpStdioRuntime.discover_tools()`，成功时按配置 ID 报告 ready 与 Tool 数量，失败时只输出有界 `stage/server_id/message`，永不输出 stderr、secret 或原始协议 payload。

首期 doctor 诊断全部 enabled Server，继续保持首次 discovery 全有或全无；不为逐 Server probe 新增第二套 Runtime。若真实使用证明“一台错误导致无法定位其他健康状态”，再给现有 Runtime 增加受控 config subset 输入。

## Skills 本地生命周期

### 来源与存储

```text
package builtin:  src/agent/builtin_skills/<name>/
project:          <workspace>/.agent/skills/<name>/
user managed:     ~/.agent/skills/<name>/
state:            ~/.agent/skills-state.json
```

`skills-state.json` 首版格式同样只记录版本和 disabled 的用户安装名：

```json
{"version":1,"disabled":["reviewer"]}
```

来源规则：

- 保留现有 project-over-builtin 行为，避免破坏已有项目。
- 用户安装名必须满足安全文件名规则，且安装/启用时不得与当前 builtin 或 project 名冲突；冲突明确失败，不静默 shadow。
- enabled user Skill 参与 `discover_skills()`；disabled user Skill 只出现在管理 inventory，不可被 `load_selected_skills()` 选择。
- `skills-state.json` 中名称合法但 user store 已无对应目录的 disabled 项是 orphan：普通 discovery 忽略，`list/doctor` 报告，`enable/disable` 返回非零；同名 `install` 清除 orphan 并 enabled，`remove` 可幂等清理 state-only orphan。
- 如果其他 workspace 后来出现同名 project Skill，discovery 对 user/project 冲突 fail closed，并给出可操作诊断；用户可 rename、disable 或 remove，不采用隐式优先级。
- Skill 内容继续是低信任上下文；安装来源和 enable 状态不能扩大 Tool catalog、绕过 policy/approval 或提高指令优先级。

### 本地包格式

安装源支持：

1. 一个本地目录，根目录直接包含 `SKILL.md`；
2. 本期 `agent skills package` 生成的 `.skill.zip`，归档根同样直接包含 `SKILL.md`。

不支持 URL、Git clone、package manager 名称或 registry ID。用户若要安装网络内容，先自行取得本地文件；本期不替用户下载或执行安装脚本。

候选包校验必须在复制/解压前后同时成立：

- `SKILL.md` 是 UTF-8 普通文件，frontmatter 与现有 parser 兼容；
- managed Skill 名匹配 `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`，并拒绝 Windows 设备保留名、尾随点/空格和大小写折叠后的冲突；
- 最多 128 个普通文件、总未压缩大小最多 8 MiB、单文件最多 1 MiB、`SKILL.md` 最多 256 KiB；
- 拒绝绝对路径、盘符、UNC、`..`、NUL、路径越界、symlink、junction/reparse point、设备文件和 archive symlink；
- 允许 scripts/templates/assets 等普通文件，但安装、validate 和 doctor 都不执行它们；
- `allowed_tools` 继续只是限制提示，未知 Tool 名不会获得能力，运行时仍以 catalog/policy 为准。

### CLI Interface

扩展现有 `agent skills` 命令组：

```text
agent skills list [--cwd PATH]
agent skills show NAME [--cwd PATH]
agent skills validate SOURCE [--cwd PATH]
agent skills install SOURCE [--cwd PATH]
agent skills enable NAME [--cwd PATH]
agent skills disable NAME [--cwd PATH]
agent skills update NAME SOURCE [--cwd PATH]
agent skills package NAME --output PATH [--cwd PATH]
agent skills remove NAME [--cwd PATH]
agent skills doctor [--cwd PATH]
```

- `validate` 检查候选但不写文件。
- `install` 只创建不存在的 user Skill；成功后清除同名 orphan disabled 状态并 enabled，不修改 `default_skills`。
- `enable/disable` 只适用于 user Skill；builtin/project 由 package/project 与现有选择配置管理。
- `update` 要求目标是 user Skill、候选 name 完全相同；先完整校验并 staging，失败时旧版本保持可用。更新保留 disabled 状态。
- `package` 对选中来源做同一安全遍历，使用 stdlib `zipfile` 按稳定路径顺序和规范化元数据生成归档；不打包内部状态、staging 或 backup 文件。`--output` 的父目录必须已存在，目标必须以 `.skill.zip` 结尾，不得是 symlink、不得已存在，也不得位于源目录或 `~/.agent` 用户 store 内；首期不增加 `--force`。归档先写同目录临时文件并完整复验，再以 `os.link(temp, output)` 原子 no-clobber 发布并删除临时名；文件系统不支持 hard link 时明确失败，不回退到可覆盖已有目标的发布方式。可捕获失败时目标不存在，进程崩溃后目标也只能是不存在或完整归档。
- `remove` 只删除 user Skill，builtin/project 明确拒绝；删除失败不得丢失状态或留下半目录。
- `doctor` 检查所有来源、用户状态、同名冲突和 effective `default_skills` 可加载性，但不把正文送给模型、不执行资源。

## 原子性、并发与恢复

所有用户级生命周期写操作遵守同一组内部规则：

1. 先解析并校验全部输入，再触碰目标。
2. `~/.agent/.extension.lock` 使用标准库文件锁：Windows 为 `msvcrt.locking(..., LK_NBLCK, 1)`，POSIX 为 `fcntl.flock(..., LOCK_EX | LOCK_NB)`；按 monotonic deadline 最多等待 5 秒。锁句柄由 OS 在进程退出时释放，不使用 PID/stale-lock 猜测。Runtime/Skill discovery 读取用户 store 时也经过同一锁。
3. 单文件 JSON/TOML 先写同目录临时文件，flush + `os.fsync` 后用 `os.replace` 发布；package 输出使用上述 no-clobber hard-link 发布。支持目录 fsync 的平台再同步父目录，不直接截断现有文件。
4. 任何同时改变目标与状态、或需要替换/删除非空目录的操作，都在同卷 `~/.agent/.extension-transactions/<txid>/` 建立私有事务目录。记录只包含版本、Module、操作、安全 ID/name、旧状态和 `prepared|committed` 阶段；不得保存或信任任意绝对路径，实际路径只能由已校验标识推导。
5. 候选与旧目标分别放在事务目录的固定 `candidate`/`backup` 位置并复验；先原子发布 `prepared` 记录，再按固定顺序更新目标和状态。只有二者都与预期一致后才原子写入 `committed`，随后清理事务目录并返回成功。
6. 每次 Module 读写在取得锁后先恢复自身事务：`prepared` 必须恢复旧目标与旧状态，`committed` 必须保留新状态并完成清理。恢复后重新校验 authoritative target；记录畸形、路径不符、多个冲突事务或恢复失败时 fail closed，由 doctor 报告，不猜测删除。
7. 无事务记录的孤立 staging/backup 只能在名称、位置、所有权标记和目标完整性都确定时清理；否则保留并报诊断。不得递归删除未知目录。
8. 锁超时、磁盘满、权限错误、杀毒软件占用、进程中断或回滚失败都返回非零；新进程只能观察到完整旧状态或完整新状态，不能观察到缺失目标与新旧状态混配。

单次操作的时间与空间复杂度均为 `O(files + bytes)`，并由上述文件数与大小上限约束；不建立数据库、索引或后台 watcher。

## 信任、安全与隐私不变量

- 只有用户级存储可定义 MCP command；项目文件不能调用管理 Module 写入用户配置，也不能自动 enable Server。
- `mcp set` 与 `skills install/update` 一类高信任动作只由显式 CLI 调用触发；Agent Tool、Skill 文本、MCP Tool 或网页请求不能代替用户授权。
- MCP command/args 中不接受 secret 注入机制；secret 继续只通过 `pass_env` 指定的环境变量名进入子进程。
- 管理错误、doctor、测试快照和未来 HTTP payload 不包含环境值、Server stderr、完整 SDK payload 或 Skill 文件正文。
- Skill 安装只是复制不可信数据，不执行 hooks、脚本、构建命令或依赖安装。
- 删除、更新和打包严格限制在解析后的 user store/candidate root；任何 symlink/reparse 或目标越界都 fail closed。
- 不削弱现有 sandbox、approval、redaction、Tool schema、snapshot、durable logs 与 Skill 不可信上下文声明。

## Module 与改动边界

预计实现落点：

- 从 `src/agent/mcp_runtime.py` 抽出 MCP 配置读取/校验到新的 MCP Config Module；Runtime 的同步 Interface `discover_tools/call_tool/close` 不扩大。
- 扩展 `src/agent/core/skills.py` 的 inventory 与用户生命周期；`load_selected_skills()` 和 `build_skills_message()` 保持现有调用形状。
- `src/agent/cli.py` 只做参数解析、调用 Module Interface 和稳定文本投影，不承载文件事务或安全规则。
- 只有 MCP 与 Skills 确实重复的锁、原子文件替换和安全目录遍历才下沉为内部 helper；不创建公开插件框架。
- 测试分别覆盖 Module Interface、CLI Adapter 与现有 runtime/run loop 回归。

## 兼容与迁移

- 现有 `~/.agent/mcp.toml` 无需迁移，Runtime 继续读取；管理命令不改写它。
- 没有 `mcp.d`、state JSON 或 user Skills 时，行为与当前版本逐字兼容。
- 现有 builtin 与 project Skills 的发现、正文预算、`allowed_tools` 和 project-over-builtin 行为保留。
- 新状态文件缺失等价于空状态；未知 version、未知字段、畸形 JSON 或重定向进 workspace 均 fail closed，并给出修复路径。
- 管理变更只影响新建 Runtime/新 turn 使用的 Skill discovery；不修改已经开始的 run catalog 或已注入的 Skill 内容。

## 非目标

- Marketplace、社区 registry、评分、发布者身份、签名与信任网络。
- URL/Git/npm/pip 一键安装、自动下载依赖或执行扩展安装脚本。
- MCP Streamable HTTP/SSE transport、resources/prompts 管理或自动 reconnect/restart；重连属于阶段 2 后续独立的 Runtime 可靠性 spec，不混入本地管理事务。
- Workbench/Frontend vNext 管理页面与用户级写 API。
- 自动修改 `default_skills`、自动选择新 Skill 或按任务推荐扩展。
- Skill 语义版本、在线更新源与跨设备同步；本地 update 由用户显式提供新候选。
- 通用 `Extension` 基类、数据库、后台 watcher、遥测或 daemon。
- Provider 能力声明；它仍是阶段 2 的后续独立 spec。

## 验收标准

### MCP

- 手写 `mcp.toml` 与 managed fragments 可同时读取；同 ID 冲突、状态文件损坏和路径重定向明确失败。
- disabled 的坏 command 不阻断普通 run，且不产生进程；重新 enable 后恢复完整校验。
- `set` 候选失败不改变旧片段；enable/disable 状态在新 Runtime 生效，已有 Runtime 不热替换。
- orphan disabled 项不阻断普通 Runtime；`list/doctor` 可见，`set/remove` 按上述确定语义清理。
- `doctor` 使用真实 stdio fixture 完成 initialize/list/close；成功、缺环境变量、协议失败和进程清理均有证据。
- 管理命令与普通 trace 均不泄漏 secret、stderr 或原始协议 payload。

### Skills

- directory 与本期 zip 可完成 validate/install；zip slip、symlink/reparse、超量、畸形 frontmatter 和 unsafe name 全部拒绝且目标不变。
- install 不改 `default_skills`；enabled user Skill 可被显式选择，disabled Skill 明确失败且正文不进入模型。
- update 成功替换正文，失败完整回滚；remove 只作用 user store；builtin/project 不能被管理命令删除。
- package → validate → install round-trip 保持 `SKILL.md` 与普通资源内容，且归档顺序稳定、不包含内部文件。
- package 拒绝已有目标、symlink、源目录内和用户 store 内输出；写入失败不留下目标或半归档。
- user 与 builtin/project 同名不发生静默覆盖；doctor 能报告冲突和失效 default。

### 全局门禁

- 没有用户扩展状态时，现有 CLI、Chat、Workbench、MCP、Skill、Tool catalog 与安全链回归通过。
- 对每个 `prepared/committed` 事务步骤注入进程终止；随后启动的新进程自动恢复，只能读到完整旧状态或完整新状态，且不存在丢失 Skill 目录、片段/状态混配或未知目录误删。
- 全量 pytest、聚焦 lifecycle/CLI/runtime 测试、`agent doctor` 和 `git diff --check` 通过。
- 所有测试 home、archive、staging、backup 和 fixture 进程位于 `D:\CodexScratch` 或 pytest `tmp_path`，验收后清理。
- 默认 Windows 用户路径 `C:\Users\admin\.agent` 的真实写入验收在实施阶段另行申请许可；申请需说明具体路径、预计小于 10 MiB、D 盘替代验证和恢复/删除方式。

### 真实 CLI 闭环

实施时增加三个只含普通文件的测试 Skill：`reviewer-v1` 与 `reviewer-v2` 的 frontmatter name 都是 `reviewer`，正文分别含唯一标记 `revision:v1`、`revision:v2`；`reviewer-invalid` 同名但不通过候选校验。整个验收块在一个新的 PowerShell 进程中执行，所有实际 CLI 都绑定到当前 checkout 安装出的 D 盘 venv，不调用 PATH 中可能存在的旧 `agent`：

```powershell
$workspace = (Resolve-Path ".").Path
$scratchRoot = [IO.Path]::GetFullPath("D:\CodexScratch")
if (-not (Test-Path -LiteralPath $scratchRoot -PathType Container)) {
    throw "D:\CodexScratch is unavailable"
}
$scratch = Join-Path $scratchRoot ("agent-extension-acceptance-" + [Guid]::NewGuid().ToString("N"))
$home = Join-Path $scratch "home"
$temp = Join-Path $scratch "temp"
$venv = Join-Path $scratch "venv"
$started = Join-Path $scratch "mcp-started.txt"
$zip = Join-Path $scratch "reviewer.skill.zip"
$fixture = Join-Path $workspace "tests\fixtures\mcp_stdio_server.py"
$skillV1 = Join-Path $workspace "tests\fixtures\skills\reviewer-v1"
$skillV2 = Join-Path $workspace "tests\fixtures\skills\reviewer-v2"
$skillInvalid = Join-Path $workspace "tests\fixtures\skills\reviewer-invalid"
$recordedPids = @()

function Invoke-Agent([int]$Expected, [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments) {
    & $script:agent @Arguments
    if ($LASTEXITCODE -ne $Expected) {
        throw "agent $($Arguments -join ' ') exited $LASTEXITCODE, expected $Expected"
    }
}

function Assert-Fixture-Exited {
    if (-not (Test-Path -LiteralPath $script:started)) { throw "fixture did not record a PID" }
    foreach ($pidValue in Get-Content -LiteralPath $script:started) {
        $pidNumber = [int]$pidValue
        $script:recordedPids += $pidNumber
        if (Get-Process -Id $pidNumber -ErrorAction SilentlyContinue) {
            throw "fixture process $pidNumber survived doctor"
        }
    }
}

try {
    New-Item -ItemType Directory -Path $home, $temp -Force | Out-Null
    $env:USERPROFILE = $home
    $env:HOME = $home
    $env:TEMP = $temp
    $env:TMP = $temp
    $env:PIP_CACHE_DIR = Join-Path $scratch "pip-cache"
    $env:PYTHONUSERBASE = Join-Path $scratch "python-user"
    $env:PIP_DISABLE_PIP_VERSION_CHECK = "1"

    $bootstrapPython = (Get-Command python -ErrorAction Stop).Source
    & $bootstrapPython -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
    $python = Join-Path $venv "Scripts\python.exe"
    $script:agent = Join-Path $venv "Scripts\agent.exe"
    & $python -m pip install -e "${workspace}[dev]"
    if ($LASTEXITCODE -ne 0) { throw "editable install failed" }
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw "pip check failed" }
    if ((& $python -c "from pathlib import Path; print(Path.home())") -ne $home) {
        throw "isolated home is not active"
    }

    Invoke-Agent 0 mcp set fixture --command $python "--arg=$fixture" "--arg=--start-file" "--arg=$started" --server-cwd workspace --cwd $workspace
    Invoke-Agent 0 mcp validate fixture --cwd $workspace
    Invoke-Agent 0 mcp doctor --cwd $workspace
    Assert-Fixture-Exited
    Invoke-Agent 0 mcp disable fixture --cwd $workspace
    $list = & $script:agent mcp list --cwd $workspace
    if ($LASTEXITCODE -ne 0 -or $list -notmatch "fixture.*disabled") { throw "disabled state is not visible" }
    Remove-Item -LiteralPath $started -ErrorAction SilentlyContinue
    Invoke-Agent 0 mcp doctor --cwd $workspace
    if (Test-Path -LiteralPath $started) { throw "disabled doctor started the fixture" }
    Invoke-Agent 0 mcp enable fixture --cwd $workspace
    $list = & $script:agent mcp list --cwd $workspace
    if ($LASTEXITCODE -ne 0 -or $list -notmatch "fixture.*enabled") { throw "enabled state is not visible" }
    Invoke-Agent 0 mcp doctor --cwd $workspace
    Assert-Fixture-Exited
    Invoke-Agent 0 mcp remove fixture --cwd $workspace
    $list = & $script:agent mcp list --cwd $workspace
    if ($LASTEXITCODE -ne 0 -or $list -match "fixture") { throw "removed MCP state remains visible" }

    Invoke-Agent 0 skills validate $skillV1 --cwd $workspace
    Invoke-Agent 0 skills install $skillV1 --cwd $workspace
    $show = & $script:agent skills show reviewer --cwd $workspace
    if ($LASTEXITCODE -ne 0 -or $show -notmatch "revision:v1") { throw "installed v1 is not visible" }
    Invoke-Agent 0 skills disable reviewer --cwd $workspace
    Invoke-Agent 1 skills show reviewer --cwd $workspace
    Invoke-Agent 0 skills enable reviewer --cwd $workspace
    Invoke-Agent 0 skills update reviewer $skillV2 --cwd $workspace
    $show = & $script:agent skills show reviewer --cwd $workspace
    if ($LASTEXITCODE -ne 0 -or $show -notmatch "revision:v2") { throw "updated v2 is not visible" }
    Invoke-Agent 1 skills update reviewer $skillInvalid --cwd $workspace
    $show = & $script:agent skills show reviewer --cwd $workspace
    if ($LASTEXITCODE -ne 0 -or $show -notmatch "revision:v2") { throw "failed update changed the installed Skill" }
    Invoke-Agent 0 skills doctor --cwd $workspace
    Invoke-Agent 0 skills package reviewer --output $zip --cwd $workspace
    Invoke-Agent 0 skills remove reviewer --cwd $workspace
    Invoke-Agent 0 skills install $zip --cwd $workspace
    $show = & $script:agent skills show reviewer --cwd $workspace
    if ($LASTEXITCODE -ne 0 -or $show -notmatch "revision:v2") { throw "package round-trip lost v2" }
    Invoke-Agent 0 skills remove reviewer --cwd $workspace
    Invoke-Agent 0 skills doctor --cwd $workspace

    $userSkill = Join-Path $home ".agent\skills\reviewer"
    $transactions = Join-Path $home ".agent\.extension-transactions"
    $skillsState = Join-Path $home ".agent\skills-state.json"
    if (Test-Path -LiteralPath $userSkill) { throw "user Skill was not removed" }
    if ((Test-Path -LiteralPath $transactions) -and (Get-ChildItem -Force -LiteralPath $transactions)) {
        throw "extension transaction residue remains"
    }
    if ((Test-Path -LiteralPath $skillsState) -and (Select-String -Quiet -LiteralPath $skillsState -Pattern '"reviewer"')) {
        throw "Skill state residue remains"
    }

    Invoke-Agent 0 doctor
    & $python -m pytest -q --basetemp (Join-Path $scratch "pytest")
    if ($LASTEXITCODE -ne 0) { throw "full pytest failed" }
}
finally {
    $cleanupErrors = @()
    if (Test-Path -LiteralPath $started) {
        foreach ($pidValue in (Get-Content -LiteralPath $started -ErrorAction SilentlyContinue)) {
            $pidNumber = 0
            if ([int]::TryParse([string]$pidValue, [ref]$pidNumber)) { $recordedPids += $pidNumber }
        }
    }

    try {
        $fixtureProcesses = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.CommandLine -and
            $_.CommandLine.IndexOf($fixture, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $_.CommandLine.IndexOf($started, [StringComparison]::OrdinalIgnoreCase) -ge 0
        })
    }
    catch {
        $fixtureProcesses = @()
        $cleanupErrors += "fixture process enumeration failed"
    }
    foreach ($process in $fixtureProcesses) {
        $recordedPids += [int]$process.ProcessId
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        Wait-Process -Id $process.ProcessId -Timeout 5 -ErrorAction SilentlyContinue
    }

    $resolvedScratch = [IO.Path]::GetFullPath($scratch)
    $allowedPrefix = $scratchRoot.TrimEnd("\") + "\"
    if (-not $resolvedScratch.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        $cleanupErrors += "refusing cleanup outside D:\CodexScratch"
    }
    elseif (Test-Path -LiteralPath $resolvedScratch) {
        try { Remove-Item -LiteralPath $resolvedScratch -Recurse -Force -ErrorAction Stop }
        catch { $cleanupErrors += "acceptance scratch removal failed" }
    }
    if (Test-Path -LiteralPath $resolvedScratch) { $cleanupErrors += "acceptance scratch residue remains" }

    try {
        $remainingFixtureProcesses = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.CommandLine -and
            $_.CommandLine.IndexOf($fixture, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $_.CommandLine.IndexOf($started, [StringComparison]::OrdinalIgnoreCase) -ge 0
        })
        if ($remainingFixtureProcesses) { $cleanupErrors += "fixture process residue remains" }
    }
    catch {
        $cleanupErrors += "fixture process negative check failed"
    }
    if ($cleanupErrors) { throw ($cleanupErrors -join "; ") }
}
```

任何 CLI 未由 `$script:agent` 启动、任何 home/cache/temp 写入落到默认 C 盘、或 finally 后仍有验收目录/fixture 进程，都视为验收失败。

## 实施拆分原则

确认本 spec 后再写 implementation plan，按以下可独立回滚的提交边界推进：

1. MCP Config Module、managed fragments/state 与 CLI 静态管理。
2. MCP live doctor 与真实 stdio 验收。
3. Skills user store、validate/install/enable/disable/remove。
4. Skills update/package/rollback与 round-trip 验收。
5. 文档、全量回归、真实路径验收和完成状态回写。

每一项都先写失败测试；前一项未通过安全与清理门禁，不进入下一项。
