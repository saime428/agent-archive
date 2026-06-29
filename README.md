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
Invoke-RestMethod -Uri http://127.0.0.1:8765/api/health
Invoke-RestMethod -Uri http://127.0.0.1:8765/api/runs
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

The Provider Notice banner shows whether the Workbench is using FakeLLM or
DeepSeek. It reports `provider_notice` from `/api/health`; it does not write
config files or store API keys.

The Patch Review Helper completes the read-only coding workflow. It combines
Task Review, Workflow Hints, Failure Summary, and snapshots into one checklist
with `risk_level`, checks, verification commands, and a next action. It does
not run tests, create commits, or generate patches.

v0.8 closeout is recorded in `docs/v0.8-acceptance.md`. v0.8 manual smoke:

```powershell
$env:PYTHONPATH="src"
python -m agent.cli ui --cwd F:\agent
Invoke-RestMethod -Uri http://127.0.0.1:8765/api/health
Invoke-RestMethod -Uri http://127.0.0.1:8765/api/runs
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
http://127.0.0.1:8765
```

The workbench shows a Runs Dashboard, effective config, tool catalog, run
summary, and tool-call trace. It also supports a basic browser chat turn from
the bottom input dock; each turn creates the same durable `.agent/runs` and
`.agent/chats` records as terminal chat.

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
session, DeepSeek key presence, and last refresh time. Auto-refresh updates
health and runs every 10 seconds without replacing an open file editor or
pending approval, and the Refresh button performs the same safe refresh on
demand. The Task Review panel summarizes the selected run's latest action, last
observation, changed files, snapshot count, and suggested manual checks.
Current v0.6 limits: browser chat is synchronous, the file editor is a single
textarea, token-level UI streaming and Electron packaging are deferred to later
slices.

v0.6 manual smoke:

```powershell
$env:PYTHONPATH="src"
python -m agent.cli run --cwd F:\agent "inspect project"
python -m agent.cli ui --cwd F:\agent
Invoke-RestMethod -Uri http://127.0.0.1:8765/api/health
python -m pytest tests/test_ui.py tests/test_cli.py tests/test_docs.py -q
python -m pytest -q
git diff --check
```

workbench success criteria:

- Runs Dashboard loads recent runs and selecting a run shows summary, trace, and snapshots.
- Status Bar shows workspace, provider, model, session, DeepSeek key presence, and last refresh.
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
```

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
- File access is constrained to the workspace.
- Risky actions such as `write_file`, `apply_patch`, and `run_command` require
  approval and fail fast in the non-interactive v0.1 CLI.
- `--dry-run` skips write tools and commands without side effects.
- Durable logs are redacted before they are written.
- `AGENTS.md`, command output, git diffs, and document contents are untrusted
  context and cannot override policy or tool schemas.

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
agent memory list
agent memory undo <entry-id>
```

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

The diagnostics report whether `pypdf`, `python-docx`, `openpyxl`, and
`python-pptx` are present. Missing optional document dependencies make only the
matching document tool return a diagnostic `TOOL_FAILED` observation.

v0.3 manual smoke:

```powershell
$env:PYTHONPATH="src"
python -m agent.cli tools list
python -m agent.cli doctor
python -m agent.cli config doctor --cwd F:\agent
python -m pytest tests/test_actions.py tests/test_documents.py tests/test_loop.py tests/test_cli.py tests/test_docs.py -q
python -m pytest -q
git diff --check
```

Word report generation remains staged for later v0.3 slices.
