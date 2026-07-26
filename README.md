# Agent

A minimal Python CLI agent core for local code-development workflows.

The v0.1 release focuses on a safe core: structured actions, bounded tool output,
workspace sandboxing, approval fail-fast behavior, dry-run support, durable logs,
redaction, snapshots, and fake-model end-to-end runs.

## Quickstart

Run a fake agent task:

```powershell
agent run "inspect project"
```

Run in a specific workspace:

```powershell
agent run --cwd F:\agent "inspect project"
```

Inspect available tools and effective configuration:

```powershell
agent tools list
agent config show --cwd F:\agent
agent config doctor --cwd F:\agent
agent doctor
```

Dry-run records intent and skips write tools and shell commands:

```powershell
agent run --dry-run "write a note"
```

Inspect run logs:

```powershell
agent runs list
agent runs show <run-id>
```

Runs write durable files under `.agent/runs/<run-id>/`. Write tools create
snapshot records before changing files; `agent runs show <run-id>` displays
snapshot paths and restore hints when a run changed files.

### OpenAI-compatible providers (local models)

```toml
# .agent/config.toml
provider = "openai-compat"
base_url = "http://localhost:11434/v1"   # e.g. Ollama
model = "llama3"
# api_key_env = "OPENAI_API_KEY"         # optional; empty key sends no Authorization header
# native_tools = true                    # use native tool calling (requires endpoint tool support)
```

With `native_tools = true` the agent uses native function calling with `tool_choice: "auto"` (thinking-mode models such as DeepSeek reject `"required"`); a plain-text reply without a tool call is routed through the repair channel. Endpoints without tool support should keep it `false`.

### Local stdio MCP tools

Local MCP servers are configured only in the user-level `~/.agent/mcp.toml`.
Project `.agent/config.toml` files and repository files cannot grant permission
to start an MCP process.

```toml
[servers.example]
command = "C:/Python313/python.exe"
args = ["D:/mcp/example_server.py", "--workspace", "{workspace}"]
cwd = "config"                 # "config" (default) or "workspace"
pass_env = ["EXAMPLE_API_KEY"] # variable names only; values come from the environment
```

On Windows, `command` must resolve to a native `.exe` or `.com`; relative paths
are rejected. An argument equal to `{workspace}` is replaced with the resolved
workspace path. `cwd = "workspace"` is explicit trust: imports and configuration
discovery performed by that server can then be influenced by project files, so
prefer the default `config` working directory.

Adding a server is startup authorization. The server process has the Agent
user's OS permissions and may access files, the network, or child processes;
the Agent workspace sandbox does not contain code running inside that process.
Every exposed MCP Tool call is separately classified as
`confirmation-required`. `sandbox = "read-only"`, dry-run, and
`approval = "never"` can still start a configured server for discovery, but
they never send `tools/call`.

Secrets belong in environment variables named by `pass_env`, never in
`command`, `args`, or TOML values. MCP metadata and results are untrusted,
schema-checked, bounded, redacted, and routed through the same catalog,
approval, observation, and trace path as built-in Tools. Public names use
`mcp__<server-id>__<normalized-tool-name>`; collisions and unsafe schemas fail
closed before the model is called.

Configuration is snapshotted for the lifetime of the CLI/Workbench process;
restart it after editing `mcp.toml`. Configuration errors fail before server
startup, while initialize or discovery failures stop the run/chat job before a
model call and close processes already started by that Runtime. This first
catalog remains all-or-nothing. After the Runtime is ready, a request timeout,
EOF, process exit, or transport/protocol failure retires only the affected
server; healthy servers and built-in Tools remain available. Calls are never
replayed, reconnected, or restarted automatically. Failure to stop one owner
within the close grace period, or failure of the shared Runtime loop, still
closes the whole Runtime. This first slice supports local stdio Tools only:
there is no remote transport,
Marketplace, management UI, automatic reconnect, or install/update lifecycle.
`agent tools list` intentionally remains a built-in-only inventory and does
not start configured MCP servers.

### Managed MCP configuration

Hand-written `~/.agent/mcp.toml` keeps working unchanged. Managed servers add
`~/.agent/mcp.d/<server-id>.toml` fragments plus `~/.agent/mcp-state.json`,
which records only the disabled server IDs:

```powershell
agent mcp list
agent mcp show <server-id>
agent mcp validate <server-id>
agent mcp set <server-id> --command C:\Python313\python.exe --arg D:\mcp\server.py --pass-env EXAMPLE_API_KEY
agent mcp enable <server-id>
agent mcp disable <server-id>
agent mcp remove <server-id>
agent mcp doctor
```

`list`, `show`, `validate`, `set`, `enable`, `disable`, and `remove` are
static: they never start a server process. `agent mcp show` prints one server's
source, enabled state, static status, and parsed command/args/pass_env names.
Only `agent mcp doctor` starts the currently
enabled servers, and it does so through one Runtime that always closes in a
single `finally`. Manual `mcp.toml` entries are read-only to these commands;
`set` and `remove` refuse to touch them. A state entry whose source has
disappeared is reported as an `orphan`, is ignored by normal runs, and can be
cleaned with `agent mcp remove`.

Configuration is still snapshotted per process. `enable`, `disable`, and `set`
never change a Runtime that has already discovered its tools; restart the CLI
or Workbench, or start a new run, before the new state applies.

### Managed local skills

Skills load from three sources: packaged builtins, project
`.agent/skills/<name>/`, and user `~/.agent/skills/<name>/`. Project skills
still override builtins. A user skill that collides with a builtin or project
name fails closed with an actionable diagnostic instead of silently shadowing
it; `~/.agent/skills-state.json` records only the disabled user skill names.

```powershell
agent skills list
agent skills show <name>
agent skills validate <source>
agent skills install <source>
agent skills enable <name>
agent skills disable <name>
agent skills update <name> <source>
agent skills package <name> --output D:\out\<name>.skill.zip
agent skills remove <name>
agent skills doctor
```

A source is either a local directory whose root contains `SKILL.md`, or a
`.skill.zip` archive produced by `agent skills package` whose root contains
`SKILL.md`. URLs, Git clones, and registry IDs are not supported; fetch the
files yourself first. The frontmatter `name` is authoritative, so a source
directory may carry a version suffix while the installed directory always
matches the frontmatter name.

Candidates are validated before and after staging: at most 128 regular files,
8 MiB total, 1 MiB per file, and 256 KiB for `SKILL.md`. Absolute paths, drive
letters, UNC paths, `..`, NUL, symlinks, junctions, reparse points, and device
files are rejected, and archives are streamed member by member instead of
being unpacked wholesale. Scripts, templates, and other ordinary resources are
copied but never executed by `validate`, `install`, `update`, `package`, or
`doctor`.

`install` only creates a new skill and enables it without touching
`default_skills`; `update` requires an existing user skill and a candidate with
the same name, keeps the disabled state, and leaves the old version in place if
the candidate fails. `package` writes a temporary file next to the output,
verifies the whole archive, and then publishes it with a no-clobber hard link,
so an existing target is never overwritten. `enable`, `disable`, `update`,
`package`, and `remove` apply to user skills only; builtin and project skills
are managed by the package and the project.

Skill content stays untrusted context. Installing or enabling a skill never
widens the Tool catalog, bypasses policy or approval, or raises instruction
priority; `allowed_tools` can only narrow what a run may call.

### Hooks and managed project config

`agent hooks list` prints every builtin hook with its enabled/blocking state
and flags config references to unknown hook names; unknown names also produce
a `config warning:` line in `agent doctor` and `agent config show`.

```powershell
agent hooks list
agent config set <key> <value...>
agent config unset <key>
```

`agent config set` writes one validated key to the project
`.agent/config.toml` through the same atomic publish path the Workbench uses;
list keys such as `default_skills` take multiple values. It refuses
`sandbox danger-full-access` and `approval never` because project config
cannot widen those settings; edit the global config by hand instead.
`agent config unset` removes a project key so the global or default value
applies again. The top-level `agent doctor` now also prints one-line MCP and
Skills summaries and points to `agent mcp doctor` / `agent skills doctor` for
detail.

### Recovering managed extensions

Every user-level write takes `~/.agent/.extension.lock`, publishes single files
through a temporary file plus `os.replace`, and routes directory or
state changes through `~/.agent/.extension-transactions/`. A new process
recovers its own interrupted transaction before reading, so it observes either
the complete old state or the complete new state, never a missing target or a
mixed pair.

If a command reports a malformed record, several conflicting transactions, an
untrusted ownership marker, or a failed recovery, it fails closed and keeps the
evidence rather than guessing what to delete. Run `agent mcp doctor` and
`agent skills doctor` to see what is affected, then remove only the reported
item with `agent mcp remove` or `agent skills remove`.

This slice stays local: there is no Marketplace, registry, URL or Git install,
Workbench lifecycle UI for MCP/Skills, automatic reconnect, or Provider
capability negotiation.

### Additional command allowlist

`run_command` keeps a small safe default set. Add explicit argv prefixes only when a project needs more commands:

```toml
# .agent/config.toml
allowed_commands = ["python", "pip show", "npm test"]
```

Prefixes match complete argv tokens. The executable token is case-insensitive and ignores a trailing `.exe`; later tokens are case-sensitive, so `pip Show` does not match `pip show`. Short prefixes grant more capability, so prefer the narrowest useful entry.

An allowlist cannot override hard-denied shell wrappers, network commands, or dangerous commands. Allowlisting only passes command admission: under the default policy, `run_command` still requires approval and its argv still passes the existing workspace path checks. Approved commands run as local processes with the agent's OS permissions. Those path checks do not fully contain file, network, or subprocess access from inside the process; `allowed_commands` is capability authorization and approval is execution confirmation, not an OS or container sandbox. Commands such as `pytest` and `python -m pytest` execute project code.

For example, `allowed_commands = ["git commit"]` intentionally bypasses the default read-only Git restriction, but `git commit` still requires approval before execution.

### Run mode for coding tasks

The default `guided` mode allows three actions, which is useful for short conversations but often too small for a coding task that must inspect, edit, and verify files. Select `auto` in Workbench Settings, or set it in project configuration:

```toml
# .agent/config.toml
mode = "auto"
```

`auto` raises the action budget to ten without changing approval or sandbox rules.

## v1.0 Release Prep

`agent start` is the one-command Workbench startup alias. It reuses `agent ui`
and starts the same local stdlib Workbench without a new server layer:

```powershell
agent start --cwd F:\agent
python -m agent.cli start --cwd F:\agent
```

Settings Readiness is backed by `/api/health`. It shows the active provider,
model, provider-specific API-key requirement/presence, base URL readiness,
loaded config files, and warnings. The current Settings page can save a narrow
set of non-secret project options through `/api/config`; API keys stay in the
environment or `.agent/secrets.env`, and config publication is atomic.

The historical v1.0 Settings Page Decision is recorded in
`docs/v1.0-settings-page-decision.md`. It kept browser settings read-only for
that release; later Workbench slices superseded that restriction for the
bounded non-secret fields described above.

Check release readiness without running tests or network calls:

```powershell
agent release doctor --cwd F:\agent
```

The output includes `release readiness: complete`, legacy local-baseline route
completion, `startup command: agent start`, provider/model, settings write policy,
packaging status, and the verification commands to run manually.

v1.0 Packaging Decision is recorded in `docs/v1.0-packaging-decision.md`:
binary packaging is deferred; `agent start` remains the release startup path.

v1.0 closeout is recorded in `docs/v1.0-acceptance.md`. The local visual agent
release prep is frozen around `agent start`, Settings Readiness, release
readiness doctor, and deferred binary packaging.

post-v1.0 Polish Backlog is recorded in
`docs/post-v1.0-polish-backlog.md`; it keeps copy, manual smoke, accessibility,
safe secret flow, and packaged executable work ordered after v1.0.

post-v1.0 Manual Smoke Checklist is recorded in
`docs/post-v1.0-manual-smoke.md` for release readiness, DeepSeek terminal chat,
and Workbench browser chat.

post-v1.0 Polish Closeout is recorded in
`docs/post-v1.0-polish-closeout.md`; speculative polish is frozen until there
is user-directed feature work.

Local DeepSeek secrets can live in `.agent/secrets.env`, which is ignored by
git:

```text
DEEPSEEK_API_KEY=...
```

`agent doctor`, `agent config show`, `agent config doctor`, `agent release doctor`,
provider smoke, terminal chat, and the Workbench read this file before checking
key presence. A real environment variable still wins if both are set.
Do not put API keys in `.agent/config.toml`.

## Frontend vNext runtime assets

The React/Vite Workbench is the default, with stable preview and legacy entries:

| URL | Current runtime entry |
| --- | --- |
| `/` | React `preview/index.html` |
| `/preview/` | React `preview/index.html` |
| `/legacy/` | Legacy `index.html` |

`src/agent/web/static/preview/**` is a tracked runtime asset. Node.js belongs
only to development and build workflows. The Python runtime never invokes npm
and serves the packaged files directly.

After changing frontend source, rebuild and verify the complete bundle:

```powershell
Set-Location frontend
npm ci
npm run build:preview
Set-Location ..
git diff --exit-code -- src/agent/web/static/preview
git ls-files --others --exclude-standard -- src/agent/web/static/preview
agent start --cwd . --port 8767
```

Commit the complete generated bundle with its source change; a clean tree must
reproduce it with `npm run build:preview` and no Git drift. Open
`http://127.0.0.1:8767/` for the default React Workbench. `/preview/` remains a
compatible React entry and `/legacy/` remains the explicit rollback entry during
the stability window; rolling back the default does not require rebuilding assets
or migrating workspace data.

Run the complete frontend gate from `frontend/` with `npm run check`. The Phase 2,
Readiness, and Cutover evidence is recorded under `docs/verification/`.

## v0.7 Product Shell Decision

v0.7 starts by keeping the Workbench shell boring: no Vue, Vite, Electron, or
Tauri until the static UI actually hurts. The decision record lives at
`docs/v0.7-shell-decision.md` and defines the migration triggers for a future
frontend or desktop shell. The Workbench also has a Task Review panel for the
selected run: latest action, last observation, changed files, snapshot count,
and suggested manual checks.

v0.7 closeout is recorded in `docs/v0.7-acceptance.md`. v0.7 manual smoke:

```powershell
$env:PYTHONPATH="src"
python -m agent.cli ui --cwd F:\agent
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/health
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/runs
python -m pytest tests/test_ui.py tests/test_docs.py tests/test_cli.py -q
python -m pytest -q
git diff --check
```

## v0.8 Stronger Coding Workflow

v0.8 starts with a read-only Workflow Hints panel in the Workbench. The selected
run now includes `workflow.verification_commands` and review steps derived from
Task Review changed files. The panel suggests commands such as targeted pytest
runs and `git diff --check`; it does not execute commands or create commits.

The Workbench also includes a read-only Failure Summary panel. It reads failed
observations from the selected run, shows `latest_failure`, and suggests next
checks. It does not retry tools, edit files, or infer a fix on its own.

The Provider Notice banner is derived from the same Provider registry as the
CLI. It reports FakeLLM, DeepSeek, or OpenAI-compatible base URL/auth readiness
without storing or exposing API-key values.

The Patch Review Helper completes the read-only coding workflow. It combines
Task Review, Workflow Hints, Failure Summary, and snapshots into one checklist
with `risk_level`, checks, verification commands, and a next action. It does
not run tests, create commits, or generate patches.

v0.8 closeout is recorded in `docs/v0.8-acceptance.md`. v0.8 manual smoke:

```powershell
$env:PYTHONPATH="src"
python -m agent.cli ui --cwd F:\agent
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/health
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/runs
python -m pytest tests/test_ui.py tests/test_docs.py tests/test_cli.py -q
python -m pytest -q
git diff --check
```

## v0.9 Audit and Resilience

v0.9 starts with a read-only Run Risk Filter in the Workbench. The run list now
shows each run's `status` and `risk_level`, and the sidebar can filter by low,
medium, or attention runs. This improves visual agent progress from a useful
Workbench toward a more dependable visual agent without executing commands from
the browser.

The Workbench also includes a read-only Run Replay panel. It reconstructs the
selected run from stored `tool_calls.jsonl` records, showing each action,
observation status, summary, policy decision, and terminal step. It does not
call the model again, execute tools, or mutate workspace files.

Log Filters narrow the selected run's Trace and Run Replay panels by action,
status, summary text, or terminal/non-terminal steps. Filtering is local and
read-only; it does not change durable logs.

Workspace Risk shows a read-only health hint for uncommitted files, failed
recent runs, and snapshots. It uses the existing `/api/health` refresh path and
does not execute tests, restore files, or mutate the workspace.

Memory Review shows pending memory candidates and active accepted entries in
the Workbench. It is read-only; accepting, rejecting, revising, deleting, and
auditing memory still happens through explicit `agent memory ...` commands.

Failure Recovery adds read-only recovery guidance for failed runs. It reports
whether `rollback_available` is true, points to Trace and Failure Summary, and
keeps retry, patching, and rollback decisions in terminal/manual flows instead
of browser automation.

v0.9 closeout is recorded in `docs/v0.9-acceptance.md`. v0.9 manual smoke:

```powershell
$env:PYTHONPATH="src"
python -m agent.cli ui --cwd F:\agent
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/health
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/runs
python -m pytest tests/test_ui.py tests/test_docs.py tests/test_cli.py -q
python -m pytest -q
git diff --check
```

## v0.6 Visual Workbench

v0.6 starts the Apix-style visual direction with a local web workbench. It
reuses the existing Python core and durable logs; it does not replace
`agent run` or `agent chat`.

Start the workbench:

```powershell
python -m agent.cli ui --cwd F:\agent
```

Open the printed URL, usually:

```text
http://127.0.0.1:8000
```

The workbench shows a Runs Dashboard, effective config, tool catalog, run
summary, and tool-call trace. It also supports a basic browser chat turn from
the bottom input dock; each turn creates the same durable `.agent/runs` and
`.agent/chats` records as terminal chat.

Browser chat streams model output live: thinking (`reasoning_content`) and
tool-argument fragments render into the collapsible 工作过程 area, and plain
content streams into the reply bubble before the final answer replaces it.
An active React chat exposes a Stop control. Cancellation and whole-turn timeout
persist an auditable terminal turn; after refresh or service restart, the next
user message can resume the same session without replaying the previous Tool.
The input dock has three clickable config toggles (联网 / 电脑文件 / 原生工具)
that write through `/api/config`, plus a 工作过程 visibility switch remembered
in localStorage. Other status details live in the settings panel.

Confirmation-required actions use a custom approval panel and then retry the
same message with one approved action. The Files panel lists workspace files
and opens text previews in a minimal file editor. The Save button uses the same
custom approval panel, then calls `/api/file/save`, writes the text file, and
records a run snapshot before the change. The Snapshots panel shows run
snapshot paths and restore hints when a run changed files. The Diff Viewer uses
`/api/diff` to show a read-only unified diff between a snapshot and the current
file. The Restore button uses the same approval panel before restoring or
deleting the changed file from snapshot metadata. The Activity panel shows
status-level live events for browser turns, approval waits, saves, restores,
completion, and failures. The Status Bar shows workspace, provider, model,
session, active-provider API-key status, and last refresh time. Auto-refresh updates
health and runs every 10 seconds without replacing an open file editor or
pending approval, and the Refresh button performs the same safe refresh on
demand. The Task Review panel summarizes the selected run's latest action, last
observation, changed files, snapshot count, and suggested manual checks.
Current v0.6 limits: the file editor is a single textarea and Electron
packaging is deferred. (Browser chat later became asynchronous with SSE, and
token-level UI streaming landed with the workbench streaming slice.)

v0.6 manual smoke:

```powershell
$env:PYTHONPATH="src"
python -m agent.cli run --cwd F:\agent "inspect project"
python -m agent.cli ui --cwd F:\agent
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/health
python -m pytest tests/test_ui.py tests/test_cli.py tests/test_docs.py -q
python -m pytest -q
git diff --check
```

workbench success criteria:

- Runs Dashboard loads recent runs and selecting a run shows summary, trace, and snapshots.
- Status Bar shows workspace, provider, model, session, active-provider API-key status, and last refresh.
- Browser chat turn creates a durable run and shows status/final output.
- Approval panel handles confirmation-required chat retries, file saves, and snapshot restores.
- Files panel opens text files in the file editor; Save button writes through `/api/file/save` with a snapshot.
- Diff Viewer shows `/api/diff` output and Snapshots panel shows restore hints.
- Task Review panel shows latest action, last observation, changed files, snapshot count, and suggested manual checks.
- Refresh does not overwrite an open file editor or pending approval.

## v0.5 Interactive Chat

v0.5 adds an interactive terminal loop on top of the same structured action
protocol. Start a chat in a workspace:

```powershell
agent chat --cwd F:\agent
```

Each turn prints status-level live output such as model calls, parsed actions,
tool execution, and approval waits. With DeepSeek chat, provider token streaming
also prints a `raw model response preview` while the JSON action is arriving.
A completed turn shows `status`,
`completed`, `terminal_reason`, `final`, and the backing run summary path.

```powershell
$env:DEEPSEEK_API_KEY="..."
agent chat --cwd F:\agent --provider deepseek --model deepseek-v4-flash
agent chat --cwd F:\agent --timeout-seconds 900
```

`--timeout-seconds` accepts 1–3600 seconds. Pressing Ctrl+C during a turn cancels
that turn, finalizes its run record, and returns to the chat prompt.

Resume a saved chat session:

```powershell
agent chat --resume <chat-id>
```

Chat sessions are stored under `.agent/chats/<chat-id>/`. Saved session JSON is
redacted before it is written. Each chat turn still creates a normal
`.agent/runs/<run-id>/` directory.

When a write, patch, shell, or report action needs confirmation, chat prints
`approval required` and asks for `approve? [y/N]`. Confirming executes the
same action; denying returns a standard approval-denied observation. Non-chat
`agent run` keeps fail-fast approval behavior.

Reference workspace context explicitly with `@file` or `@dir`:

```powershell
agent chat --cwd F:\agent
agent> summarize @README.md and inspect @src
```

Referenced content is loaded through the workspace sandbox, bounded by the
context budget, and marked as untrusted context.

Chat slash commands are handled locally and do not call the model:

```powershell
/help
/status
/transcript
/exit
```

v0.5 manual smoke:

```powershell
$env:PYTHONPATH="src"
python -m agent.cli chat --cwd F:\agent
python -m agent.cli chat --cwd F:\agent --provider deepseek --model deepseek-v4-flash
python -m agent.cli chat --cwd F:\agent --resume <chat-id>
python -m agent.cli runs show <run-id>
python -m pytest tests/test_chat.py tests/test_cli.py tests/test_deepseek.py tests/test_docs.py -q
python -m pytest -q
git diff --check
```

live chat success criteria:

- `chat_id` is printed when the session starts.
- DeepSeek chat shows `raw model response preview` before the parsed action result.
- Completed turns show `status: ok`, `completed: true`, `terminal_reason: done`, and a natural-language `final`.
- `/status` shows the current turn count and latest result; `/transcript` shows recent turns.
- Denied chat approvals return `APPROVAL_DENIED`; non-chat `agent run` still fails fast for required approvals.

## Safety Model

- Models emit structured JSON actions; the core validates and executes them.
- Built-in file and document tools enforce the configured path policy: workspace-only by default, with explicit read-only computer access when enabled. Command argv path checks do not fully contain access performed inside an approved local process.
- Risky actions such as `write_file`, `apply_patch`, and `run_command` require
  approval and fail fast in the non-interactive v0.1 CLI.
- `--dry-run` skips write tools and commands without side effects.
- Durable logs are redacted before they are written.
- Workbench binds only to loopback addresses, rejects non-loopback Host headers
  and cross-origin writes, and does not claim to be a production HTTP server.
- `AGENTS.md`, command output, git diffs, and document contents are untrusted
  context and cannot override policy or tool schemas.
- Recoverable tool errors are fed back to the model with a consecutive-error budget (`max_consecutive_errors`, default 3). Approval denials and hook blocks always terminate the run immediately.

## Development

Run the test suite:

```powershell
python -m pytest -q
git diff --check
```

## v0.2 Commands

v0.2 keeps `fake` as the default provider. To use DeepSeek, set an API key and
select the provider explicitly:

```powershell
$env:DEEPSEEK_API_KEY="..."
agent run --provider deepseek --model deepseek-v4-flash "inspect project"
```

Provider diagnostics never make a network request:

```powershell
agent doctor
agent config doctor
```

Inspect skills:

```powershell
agent skills list
agent skills show code-dev
agent run --skill code-dev "fix failing tests"
```

Review and manage memory:

```powershell
agent memory review
agent memory accept <candidate-id>
agent memory reject <candidate-id>
agent memory list
agent memory revise <entry-id> "replacement text"
agent memory history <entry-id>
agent memory delete <entry-id>
agent memory undo <entry-id>
```

`undo` remains a compatibility alias for `delete`. Candidate decisions are
single-use, and `list` returns only the current active leaf of each revision
history.

Run explicit local automations:

```powershell
agent automation add "inspect project" --every-minutes 60
agent automation list
agent automation enable <automation-id>
agent automation worker --once
agent automation attempts
agent automation notifications
agent automation cancel <attempt-id>
agent automation disable <automation-id>
```

Automations use fixed UTC minute intervals and run only while the foreground
worker is active; no service or cron job is installed. Approval-required
actions fail instead of being auto-approved. Disabling stops future attempts;
use `cancel` to request cancellation of an active attempt.

Hooks are disabled by default. When explicitly enabled in config, in-process
hooks are logged under `.agent/runs/<run-id>/hooks.jsonl`.

## v0.4 Provider Smoke

v0.4 adds an explicit live smoke path for DeepSeek. It is opt-in: pytest does not require a real DeepSeek API key and does not make network requests.

```powershell
$env:DEEPSEEK_API_KEY="..."
agent provider smoke deepseek --model deepseek-v4-flash
python -m agent.cli run --provider deepseek --model deepseek-v4-flash "inspect project"
python -m agent.cli runs show <run-id>
```

The smoke command makes one non-streaming chat completion request, validates
that the model returned a legal `done` action, prints the provider/model/status,
and does not create `.agent/runs` entries or execute tools.

The live run command creates a normal run under `.agent/runs/<run-id>/`.
Successful runs show `completed: true`, `terminal_reason: done`, and a natural
language `final` value. Failed runs show `completed: false`, a
`terminal_reason`, and the run summary records `failure_explanation` so the
result can be judged without reading raw `tool_calls.jsonl`.

During live runs, successful low-risk tool observations are fed back to the
model as `UNTRUSTED TOOL OBSERVATION` context. The model must still answer with
the internal JSON action protocol; free-form natural language is only surfaced
through `done.final` and the run summary.

Provider token streaming is implemented for DeepSeek chat only. Streaming is a
terminal preview: the core still waits for the full response before parsing and
executing one JSON action, so JSON action parsing stays deterministic.

## v0.3 Document Slice

v0.3 has started with minimal document reading tools in the internal action
protocol. PDF files can be read with `read_pdf`:

```json
{
  "message": "Read the local PDF.",
  "action": {
    "name": "read_pdf",
    "args": {
      "path": "docs/main.pdf",
      "max_chars": 4000
    }
  }
}
```

Word `.docx` files can be read with `read_docx`:

```json
{
  "message": "Read the local DOCX.",
  "action": {
    "name": "read_docx",
    "args": {
      "path": "docs/interview.docx",
      "max_chars": 4000
    }
  }
}
```

Excel `.xlsx` files can be read with `read_xlsx`:

```json
{
  "message": "Read the local XLSX.",
  "action": {
    "name": "read_xlsx",
    "args": {
      "path": "docs/data.xlsx",
      "max_chars": 4000
    }
  }
}
```

PowerPoint `.pptx` files can be read with `read_pptx`:

```json
{
  "message": "Read the local PPTX.",
  "action": {
    "name": "read_pptx",
    "args": {
      "path": "docs/slides.pptx",
      "max_chars": 4000
    }
  }
}
```

Source-grounded Markdown reports can be written with `write_markdown_report`:

```json
{
  "message": "Write the report.",
  "action": {
    "name": "write_markdown_report",
    "args": {
      "path": "reports/summary.md",
      "title": "Research Summary",
      "body": "Findings grounded in the cited source material.",
      "sources": ["docs/main.pdf"],
      "create_parents": true
    }
  }
}
```

`read_pdf` extracts text with `pypdf`, `read_docx` extracts paragraph text with
optional `python-docx`, and `read_xlsx` extracts sheet names, shape, headers,
and sample rows with optional `openpyxl`. `read_pptx` extracts slide titles and
text with optional `python-pptx`. These tools apply the workspace sandbox,
budget the returned text, and wrap extracted content with
`UNTRUSTED DOCUMENT SOURCE MATERIAL` so document text cannot override
instructions, policy, approval, sandbox, or tool schemas.

Install all optional Office readers with:

```powershell
python -m pip install -e ".[documents]"
```

The extra includes `defusedxml` because the openpyxl project recommends it for
protection against malicious XML expansion.

`write_markdown_report` requires approval in the non-interactive CLI, creates a
snapshot before writing, and inserts a source-grounding notice plus a Sources
section into the report.

Document read tools are low-risk read-only actions. write_markdown_report is confirmation-required,
and dry-run skips it without writing files or snapshots.

document dependency diagnostics are visible through doctor commands:

```powershell
python -m agent.cli doctor
python -m agent.cli config doctor --cwd F:\agent
```

The diagnostics report whether `pypdf`, `defusedxml`, `python-docx`, `openpyxl`,
and `python-pptx` are present. Missing parser packages make only the matching
document tool return a diagnostic `TOOL_FAILED` observation; the `defusedxml`
line separately exposes whether the recommended XML hardening is installed.

v0.3 manual smoke:

```powershell
$env:PYTHONPATH="src"
python -m agent.cli tools list
python -m agent.cli doctor
python -m agent.cli config doctor --cwd F:\agent
python -m pytest tests/core/test_actions_parse.py tests/core/test_actions_observations.py tests/test_documents.py tests/core/test_loop_core.py tests/core/test_loop_modes.py tests/test_cli.py tests/test_docs.py -q
python -m pytest -q
git diff --check
```

Word report generation remains staged for later v0.3 slices.
