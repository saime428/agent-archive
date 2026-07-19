# 实施计划：可管理的本地 MCP 与 Skills 生命周期

- 日期：2026-07-18
- 状态：已审查，待实施
- 设计：[2026-07-18-managed-extension-lifecycle-design.md](../specs/2026-07-18-managed-extension-lifecycle-design.md)
- Implementation base：`a8f824e4d8c09e9458bf6d57984d4c25addf3715`
- 工作分支：`codex/mcp-server-fault-isolation`

## 完成定义

本计划只完成 Project vNext 阶段 2 的第一份后端切片：MCP 本地配置管理、启停与 live doctor，以及 Skills 用户级本地生命周期。只有以下条件同时成立，才可把本计划标为已执行：

1. 手写 `~/.agent/mcp.toml` 保持只读兼容，managed fragments/state 与 user Skills 能从安装到移除形成真实 CLI 闭环。
2. Runtime、Skill loader、Tool catalog、policy、approval、redaction、trace 与进程清理仍是唯一执行链；没有第二套 MCP Runtime 或 Skill 注入路径。
3. 锁竞争、磁盘/权限失败、进程崩溃和恢复后，新进程只看到完整旧状态或完整新状态。
4. Marketplace、URL/Git 安装、Workbench 写接口、自动重连、Provider 能力声明和通用插件框架都未进入实现。
5. 聚焦测试、全量 pytest、doctor、真实 D 盘隔离 CLI 验收、清理负向检查与最终双轴审查全部通过。
6. 默认 `C:\Users\admin\.agent` 的写入验证已事先取得用户许可并通过；若用户明确不授权或豁免，必须如实记录，不能冒充已验证。

## Module、Interface 与 seam

| Module | Interface | 拥有的 Implementation | 明确不拥有 |
| --- | --- | --- | --- |
| `agent._user_store` | 内部锁、原子文件发布和安全 store path helper | Windows/POSIX 文件锁、同目录临时文件、fsync、路径/链接约束 | MCP/Skill 字段、CRUD 转发、通用 transaction callback 框架 |
| `agent.mcp_config` | `McpConfigStore` 的 inventory、enabled snapshot、set、set-enabled、remove | manual/managed/state 合并、静态校验、窄 TOML 序列化、MCP 事务恢复 | Server 进程、SDK session、Tool discovery/call |
| `agent.mcp_runtime` | 现有 `discover_tools/call_tool/close` | SDK transport、owner task、snapshot、调用与关闭 | 配置写入、热重载、管理 CLI |
| `agent.core.skills` | 现有 discovery/load Interface，加 `SkillStore` 本地生命周期 Interface | 三来源 inventory、候选校验、用户 store、事务恢复、zip round-trip | Tool 执行、依赖安装、在线来源、通用 Extension 类型 |
| `agent.cli` | `agent mcp ...` 与扩展后的 `agent skills ...` | 参数解析、调用 Module、稳定安全文本投影、退出码 | 文件事务、安全遍历、MCP 协议实现 |

`McpStdioRuntime` 继续由 `workspace/home/environ` 构造，只把首次 discovery 的配置读取替换为 `McpConfigStore.load_enabled_configs()`；公共同步 Interface 不增加方法。`discover_skills()` 与 `load_selected_skills()` 保持现有调用形状，只允许增加测试需要的 keyword-only `home`，现有调用者无需修改。

共享 helper 必须等两个真实调用点都出现后才提取。MCP 与 Skills 的 `prepared/committed` 恢复顺序、旧状态解释和 authoritative target 校验留在各自 Module；不得创建 `ExtensionManager`、`kind=mcp|skill` 分派器或通用 CRUD Interface。

## 全局实施约束

- 每个非平凡分支先写失败测试，再做最小实现；测试只跨公开/既有 Interface，私有故障注入只存在于测试进程。
- 不新增依赖。TOML 写入只覆盖 Agent 自有窄 schema，并用 `tomllib` round-trip 自检；Skill zip 使用 stdlib `zipfile`。
- manual `mcp.toml`、builtin Skill 与 project Skill 永不由管理命令改写或删除。
- disabled MCP 不启动进程；除 `mcp doctor` 外，所有管理命令都不得启动 Server。Skill 管理命令不执行任何包内脚本或资源。
- CLI/错误/trace 不输出完整 MCP argv、stderr、环境变量值、原始协议 payload 或 Skill 正文；`skills show` 是用户显式读取的既有例外。
- 普通 run/chat/Workbench 只在新 Runtime/新 turn 读取新状态；不热重载，不隐式重启。
- 所有非项目 test home、venv、cache、archive、staging 与 basetemp 放在 `D:\CodexScratch`，每次门禁后做不存在/无进程负向检查。
- 未取得许可前不写 `C:\Users\admin\.agent`；读取本地代码与 Git 状态不构成该授权。
- 每个 Task 完成后先跑该 Task 门禁并检查工作区范围；前一 Task 未绿，不进入下一 Task。

## Task 1：MCP Config Module 与静态管理闭环

**Files**

- Create: `src/agent/mcp_config.py`
- Create: `tests/test_mcp_config.py`
- Create: `tests/fixtures/extension_crash_worker.py`
- Modify: `src/agent/mcp_runtime.py`
- Modify: `src/agent/cli.py`
- Modify: `tests/test_mcp_runtime.py`
- Modify: `tests/test_cli.py`

### 1.1 先锁定 MCP 自用的 store primitive

先写失败测试：

1. 第二进程占有 `.extension.lock` 时当前进程按 monotonic deadline 在 5 秒内明确失败；owner 正常退出或被终止后 OS 释放锁，不解析 PID 或删除所谓 stale lock。
2. Windows 锁文件固定写入/锁住第 1 byte 并在每次尝试前 seek(0)；POSIX 使用 non-blocking exclusive flock。两端都由同一 context manager 释放句柄。
3. agent root、lock、临时文件或目标若是 symlink、junction/reparse、设备路径、workspace 内重定向或 canonical 越界，全部 fail closed。
4. 单文件发布在 flush/fsync/replace 任一步失败时保留旧文件；只清理由 helper 创建且 ownership/name 可证明的临时文件。

最小 Implementation 先把锁、canonical path 校验和原子 bytes/text/JSON 发布写成 `mcp_config.py` 私有函数；当前只有 MCP 一个真实调用方，不提前创建共享 `_user_store`。不在此时写 transaction manager、archive helper 或 domain record。

### 1.2 抽出 MCP Config Module

把现有配置 dataclass、ID/字段校验、PATH/PATHEXT 净化、command/cwd/pass_env 解析和 `load_mcp_server_configs()` 从 `mcp_runtime.py` 移入 `mcp_config.py`。`mcp_runtime.py` 继续 re-export 现有公开名称，避免当前 imports 破坏；配置专属旧测试迁移到 `tests/test_mcp_config.py`，不得复制两套断言。

`McpConfigStore` 首期 Interface 固定为：

- `inventory()`：返回 manual/managed/orphan、enabled 状态与有界静态诊断；不启动进程。
- `validate(server_id=None)`：对选中或全部来源执行完整静态 command/PATH/env 校验；不修改状态。
- `load_enabled_configs()`：只给 Runtime 返回冻结后的有效 `McpServerConfig` tuple。
- `set_server(...)`：只 create/replace managed fragment。
- `set_enabled(server_id, enabled)`：只改 state。
- `remove_server(server_id)`：只删除 managed 来源或 state-only orphan。

读取顺序为 manual → 按 case-aware 安全 ID 稳定排序的 fragments → state。覆盖总量上限后再生成 enabled snapshot；manual/managed 同 ID、casefold 文件冲突、未知字段/version、非法链接与 state 损坏均 fail closed。合法 orphan 不计入 Server 上限且不阻断 Runtime。disabled 来源仍解析 TOML/ID，但跳过 command/PATH/env。

### 1.3 增加受管写入与恢复

1. managed fragment 使用固定窄 TOML 字段顺序；所有 string/array 先序列化，再由 `tomllib` 读回并与候选等值比较后发布。
2. 新 `set` 清同名 orphan 并 enabled；replace 保留状态；manual 同名拒绝。`remove` 对 managed/state-only orphan 幂等，对 manual 拒绝。
3. 单文件替换先走 `mcp_config` 私有 primitive；fragment + state 的多路径操作由 `mcp_config` 自己建立固定 `candidate`/`backup` 位并写 `prepared/committed` record。record 只存 version、module、操作、安全 ID、旧状态和 phase，绝对路径全部由 Module 推导并复验。
4. 每次 inventory/load/mutation 取得锁后先恢复本 Module transaction：prepared 从固定 backup 恢复旧 fragment 与旧 state，committed 保留并复验新 fragment/state 后清理。畸形/冲突 record、candidate/backup 链接或 authoritative target 不符均 fail closed。
5. `extension_crash_worker.py` 只在子进程 monkeypatch 私有 I/O seam，并用 `os._exit` 覆盖 candidate 校验、prepared、旧 fragment backup、新 fragment publish、state publish、committed 与 cleanup 每个边界；下一进程必须只读到完整旧状态或完整新状态。生产代码不增加测试开关。

### 1.4 接入 CLI Adapter

新增 `mcp_app` 与 `list/validate/set/enable/disable/remove`。CLI 只创建 `McpConfigStore`、调用方法、输出稳定的 `id/source/enabled/status` 和有界错误；默认不打印完整 argv。每个命令的 Typer 测试同时断言退出码、输出和“未创建 fixture start-file/未启动进程”。

聚焦门禁：

```powershell
python -m pytest tests/test_mcp_config.py tests/test_mcp_runtime.py tests/test_cli.py -q --basetemp D:\CodexScratch\agent-managed-extension-task1
git diff --check
```

Task 1 完成条件：无 managed 文件时 Runtime 行为逐字兼容；manual + managed + state 合并、所有静态 CLI、崩溃恢复与临时文件清理全绿。

## Task 2：MCP live doctor 与 Runtime 真实验收

**Files**

- Modify: `src/agent/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_mcp_runtime.py`
- Reuse: `tests/fixtures/mcp_stdio_server.py`

先写失败测试：

1. 无 enabled Server 时 `agent mcp doctor` 退出 0、报告 0 台且不创建进程。
2. enabled fixture 时只构造一套 `McpStdioRuntime`，调用现有 `discover_tools()`，按 Server ID 统计 Tool，最终只在一个 `finally` 调用 `close()`。
3. command/env/config、initialize/protocol/discovery 和 close 失败都返回非零与有界 `stage/server_id/message`，不输出 stderr、secret 或 raw payload。
4. disabled 坏 command 不阻断 doctor 且不启动；重新 enable 后恢复完整静态校验。
5. doctor 成功、失败和 Ctrl+C 后 fixture PID/子进程树均消失；关闭失败不能覆盖更早的安全诊断，但仍使退出码非零。
6. state-only orphan 在 doctor 中可见但不启动进程；`set/remove` 后按定义消失。
7. Runtime 首次 discovery 后管理 enable/disable/set 不改变其冻结 snapshot；新建 Runtime 才读取新状态并启动对应进程。

最小实现复用当前 Runtime 和现有 close 错误处理形状；不增加 per-Server probe、config subset、第二个 Runtime、热重载或自动重连。成功结果才按 snapshot 中的 target.server_id 聚合数量；首次 discovery 仍全有或全无。

聚焦门禁：

```powershell
python -m pytest tests/test_cli.py tests/test_mcp_runtime.py -q --basetemp D:\CodexScratch\agent-managed-extension-task2
git diff --check
```

Task 2 完成条件：真实 SDK initialize/list/close 有 PID 级证据，所有失败路径无遗留进程，静态命令仍从未启动 Server。

## Task 3：Skills user store 与基本生命周期

**Files**

- Create: `src/agent/_user_store.py`
- Modify: `src/agent/core/skills.py`
- Modify: `src/agent/mcp_config.py`
- Modify: `src/agent/cli.py`
- Create: `tests/test_user_store.py`
- Modify: `tests/test_mcp_config.py`
- Modify: `tests/test_skills.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/core/test_loop_core.py`
- Modify: `tests/fixtures/extension_crash_worker.py`
- Create: `tests/fixtures/skills/reviewer-v1/SKILL.md`

### 3.1 深化现有 Skills Module

保留 `discover_skills()`、`load_selected_skills()`、`build_skills_message()` 的既有 Interface 和 project-over-builtin 行为。新增 domain-specific `SkillStore`，由运行时 discovery/load 与 CLI 共同使用；不在 CLI 重写文件规则。

先写失败测试覆盖：

1. builtin、project、enabled user 的稳定 inventory 与选择；project 仍覆盖 builtin，user 与任一有效来源同名时 fail closed，不引入新优先级。
2. disabled user 只出现在 inventory，`show/load_selected_skills` 明确报 disabled 且正文不进入模型；普通 run 未选择它时不受影响。
3. user store 与 workspace/project root 重合或解析进入 workspace、目录名/frontmatter name 不一致、unsafe/casefold/Windows device name、symlink/junction/reparse 全部拒绝。
4. orphan disabled 项不阻断 discovery；list/doctor 可见；enable/disable 对无来源项失败；install/remove 按 spec 清理。
5. 目录候选只遍历普通文件，强制 128 files/8 MiB/1 MiB/256 KiB 上限，复制前后都复验；validate/install 不执行 scripts/assets。

### 3.2 实现 validate/install/enable/disable/remove

1. `SkillStore` 增加 inventory、validate_directory、install、set_enabled、remove；现有 loader 通过同一 effective catalog 读取正文。
2. install 先校验到同卷 transaction candidate，再以 prepared/committed record 发布；成功 enabled 且不改 `.agent/config.toml`/`default_skills`。
3. remove 只处理 user 目标/state-only orphan；builtin/project 明确拒绝。删除/状态更新失败由 transaction recovery 恢复。
4. 此时 MCP 与 Skills 已有第二个真实调用点，才把已经重复的锁、canonical path、原子文件发布、record schema 原子读写与 transaction directory allocation 提取到 `_user_store.py`，并让 MCP 改用同一 helper；rollback、authoritative target 与状态解释仍留在各自 Module。迁移原有 primitive 测试，不保留两套实现或重复断言。
5. 扩展 `agent skills list/show`，新增 `validate/install/enable/disable/remove`；CLI 输出 source/enabled/status，不把正文带入 list/doctor。

核心 integration 测试显式选择 enabled user Skill，断言唯一正文标记进入低信任 Skills message、`allowed_tools` 仍只能收窄 Tool；disabled/collision 时模型请求中没有该正文。再固定一个已开始 turn 的 Skill snapshot，执行 disable/remove 后断言当前 turn 不变、下一 turn 才读取新状态。保持 run loop、catalog 与 policy 调用顺序不变。

聚焦门禁：

```powershell
python -m pytest tests/test_user_store.py tests/test_mcp_config.py tests/test_skills.py tests/test_cli.py tests/core/test_loop_core.py -q --basetemp D:\CodexScratch\agent-managed-extension-task3
git diff --check
```

Task 3 完成条件：directory validate → install → disable/enable → remove 闭环可重复，旧 builtin/project 行为与安全链回归不变，崩溃后没有缺失目录或 state 混配。

## Task 4：Skills update、package、doctor 与恢复闭环

**Files**

- Modify: `src/agent/core/skills.py`
- Modify: `src/agent/cli.py`
- Modify: `tests/test_skills.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/fixtures/extension_crash_worker.py`
- Create: `tests/fixtures/skills/reviewer-v2/SKILL.md`
- Create: `tests/fixtures/skills/reviewer-invalid/SKILL.md`
- Add ordinary resource fixtures under: `tests/fixtures/skills/reviewer-v1/` and `tests/fixtures/skills/reviewer-v2/`

### 4.1 update 与 crash recovery

先写失败测试：

1. 同名 v1 → v2 update 成功替换全部正文/资源并保留 disabled 状态；不同 name、非法候选或来源非 user 返回非零且 v1 不变。
2. 在 candidate 校验、prepared、旧目录 backup、新目录 publish、state publish、committed、cleanup 每个边界终止子进程；下一进程恢复后只能看到完整 v1 或完整 v2。
3. transaction record 畸形、冲突、路径不符、backup/candidate 被链接或 authoritative target 复验失败时 fail closed，doctor 报告且不猜测删除。
4. 磁盘满、权限/杀毒占用、replace/rename/cleanup 失败时命令不写成功；恢复失败保留证据。

### 4.2 zip validate/package round-trip

1. validate/install 支持根含 `SKILL.md` 的 `.skill.zip`；先检查 member count、声明大小与路径，再逐文件有界流式复制，禁止 `extractall()`。
2. 拒绝绝对/盘符/UNC/`..`/NUL、duplicate/casefold collision、archive symlink、设备/特殊文件、超量与解压后越界；解压后重新走目录候选校验。
3. package 以稳定 path 顺序、固定时间/权限/UTF-8 元数据写同目录 temp，复验完整 zip 后用 `os.link(temp, output)` no-clobber 发布；已有/symlink/source 内/user store 内/非 `.skill.zip` 输出拒绝。hard link 不可用时明确失败，不回退覆盖。
4. package → validate → install 保持 SKILL.md 和普通资源 bytes；重复 package 的 archive bytes 一致，不包含 state/transaction/temp/backup。

### 4.3 skills doctor

`agent skills doctor` 从 `load_config()` 接收 effective `default_skills`，只检查三来源、state/orphan/collision、transaction、包结构与默认 Skill 可加载性；不加载正文进模型、不执行资源。正常为空或健康时退出 0；任一不可恢复项退出 1并给出安全修复动作。

聚焦门禁：

```powershell
python -m pytest tests/test_user_store.py tests/test_skills.py tests/test_cli.py tests/core/test_loop_core.py -q --basetemp D:\CodexScratch\agent-managed-extension-task4
git diff --check
```

Task 4 完成条件：完整 validate → install → enable/disable → update → package → remove 与 zip round-trip 均可重复，失败/崩溃恢复、no-clobber 和 doctor 全绿。

## Task 5：文档、全量门禁与真实路径验收

**Files**

- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/project-vnext-direction.md`
- Modify: `docs/roadmap-progress.md`
- Modify: `docs/superpowers/specs/2026-07-18-managed-extension-lifecycle-design.md`
- Modify: `docs/superpowers/plans/2026-07-18-managed-extension-lifecycle.md`
- Modify: `tests/test_docs.py`

### 5.1 文档只描述真实能力

README 记录 manual/managed 布局、全部 CLI、restart 语义、local-only 来源、安全/隐私边界和恢复动作；CHANGELOG 记录可管理生命周期。方向/roadmap 只把本切片标为完成，不得把 Provider 能力、Frontend Hub、Marketplace、重连、阶段 2 或完整生态标成完成。

`tests/test_docs.py` 锁定：Spec/Plan 状态与互链、README 命令/非目标、roadmap 当前/下一切片、CHANGELOG 条目。不得复制整份文档文本进测试。

### 5.2 自动门禁

先为本次门禁创建唯一 `D:\CodexScratch\agent-managed-extension-gate-<guid>`，将 `USERPROFILE`、`HOME`、`TEMP`、`TMP`、`PIP_CACHE_DIR` 全部指向其子目录，并在确认解析后的 gate root 位于 `D:\CodexScratch` 后，才在同一 PowerShell 进程执行以下命令。`finally` 必须恢复原环境、只删除该唯一 gate root，并确认目录与 fixture 进程都不存在；不得直接使用默认 C 盘 home/temp。以下是必须纳入验收脚本的门禁主体，不允许只复制中间四条命令而省略环境设置与清理：

```powershell
$scratchRoot = [IO.Path]::GetFullPath('D:\CodexScratch')
$gateRoot = Join-Path 'D:\CodexScratch' ('agent-managed-extension-gate-' + [Guid]::NewGuid().ToString('N'))
$gateRoot = [IO.Path]::GetFullPath($gateRoot)
if (-not $gateRoot.StartsWith($scratchRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'unsafe gate root' }
$saved = @{}; 'USERPROFILE','HOME','TEMP','TMP','PIP_CACHE_DIR' | ForEach-Object { $saved[$_] = [Environment]::GetEnvironmentVariable($_, 'Process') }
$fixture = [IO.Path]::GetFullPath((Join-Path (Resolve-Path '.').Path 'tests\fixtures\mcp_stdio_server.py'))
function Invoke-Checked([scriptblock]$Command) { & $Command; if ($LASTEXITCODE -ne 0) { throw "gate command exited $LASTEXITCODE" } }
function Get-GateFixtureProcess { @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($fixture, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and $_.CommandLine.IndexOf($gateRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 }) }
try {
    New-Item -ItemType Directory -Force -Path (Join-Path $gateRoot 'home'),(Join-Path $gateRoot 'temp'),(Join-Path $gateRoot 'pip-cache') | Out-Null
    $env:USERPROFILE = Join-Path $gateRoot 'home'; $env:HOME = $env:USERPROFILE
    $env:TEMP = Join-Path $gateRoot 'temp'; $env:TMP = $env:TEMP; $env:PIP_CACHE_DIR = Join-Path $gateRoot 'pip-cache'
    Invoke-Checked { python -m pytest tests/test_user_store.py tests/test_mcp_config.py tests/test_mcp_runtime.py tests/test_skills.py tests/test_cli.py tests/core/test_loop_core.py tests/core/test_loop_mcp.py tests/test_docs.py -q -rs --basetemp (Join-Path $gateRoot 'pytest-focused') }
    Invoke-Checked { python -m pytest -q -rs --basetemp (Join-Path $gateRoot 'pytest-full') }
    Invoke-Checked { python -m agent.cli doctor }
    Invoke-Checked { git diff --check }
    if (Get-GateFixtureProcess) { throw 'fixture process survived automatic gate' }
} finally {
    $cleanupErrors = @()
    foreach ($name in $saved.Keys) { try { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') } catch { $cleanupErrors += "failed to restore $name" } }
    try { $fixtureProcesses = @(Get-GateFixtureProcess) } catch { $fixtureProcesses = @(); $cleanupErrors += 'fixture process enumeration failed' }
    foreach ($process in $fixtureProcesses) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        Wait-Process -Id $process.ProcessId -Timeout 5 -ErrorAction SilentlyContinue
        if (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue) { $cleanupErrors += "fixture process $($process.ProcessId) survived cleanup" }
    }
    try { if (Test-Path -LiteralPath $gateRoot) { Remove-Item -LiteralPath $gateRoot -Recurse -Force -ErrorAction Stop } } catch { $cleanupErrors += 'gate cleanup failed' }
    if (Test-Path -LiteralPath $gateRoot) { $cleanupErrors += 'gate residue remains' }
    try { if (Get-GateFixtureProcess) { $cleanupErrors += 'fixture process residue remains' } } catch { $cleanupErrors += 'fixture process negative check failed' }
    if ($cleanupErrors) { throw ($cleanupErrors -join '; ') }
}
```

之后完整执行 Spec“真实 CLI 闭环”的独立 PowerShell 块：唯一 D 盘 run root、当前 checkout 的全新 venv、`pip install -e "${workspace}[dev]"`、`pip check`、MCP PID 负向检查、Skills v1/v2/失败 update/zip round-trip、full pytest 与 finally 清理。该块必须 AST 可解析、可重复运行，且结束后 run root 与匹配 fixture 进程都不存在。

### 5.3 默认 Windows 路径授权门

D 盘全部通过后暂停并询问用户是否允许一次默认路径验收：

- 具体路径：`C:\Users\admin\.agent\mcp.d\codex-acceptance.toml`、`mcp-state.json`、`skills\codex-acceptance\`、`skills-state.json`、锁与 transaction 临时目录。
- 预计峰值：小于 10 MiB。
- 必要性：只证明 `Path.home()` 默认 Windows 路径、Developer Mode 下 symlink/junction 拒绝和真实 ACL/杀毒占用语义；功能正确性已有 D 盘替代证据。
- 恢复：先备份同名既有测试目标（若存在则停止，不覆盖），只删除本次带 `codex-acceptance` 标识的内容，保留用户其他配置，并做负向检查。

未授权前不得创建上述 C 盘内容。若用户不授权，记录“默认路径未验收（未授权）”，保持 Draft，不能把该门禁写成通过。

### 5.4 最终审查

以 Implementation base 为固定点做一次 Standards/Spec 双轴审查；修完所有 P1/P2 后重跑受影响聚焦门禁和全量门禁，并确认工作区只含计划内变更。产品实现是否完成只由 Spec 验收与本节门禁决定，不把远端发布状态伪装成产品能力。

## 提交边界

1. `docs: plan managed extension lifecycle`（本计划与已确认 Spec 状态）
2. `feat: manage local MCP configurations`（Task 1）
3. `feat: diagnose managed MCP servers`（Task 2）
4. `feat: manage local skills`（Task 3）
5. `feat: update and package local skills`（Task 4）
6. `docs: close managed extension lifecycle`（Task 5）

每个实现 commit 必须单独可运行、可回滚且不削弱前一阶段门禁。不得把所有生产代码压成一个最终 commit，也不得在完整方向完成前把现有 Draft PR 转为 Ready。

## 用户授权后的交付清单

在用户要求提交/发布后，才检查本地 HEAD = 远端 branch head = Draft PR head、工作区干净且 PR 仍为 Draft。推送、转 Ready 与合并是交付状态，不属于上述 Spec 完成条件；只有用户另行明确要求，才可转 Ready 或合并。
