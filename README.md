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

## v0.5 Interactive Chat

v0.5 adds an interactive terminal loop on top of the same structured action
protocol. Start a chat in a workspace:

```powershell
agent chat --cwd F:\agent
```

Each turn prints status-level live output such as model calls, parsed actions,
tool execution, and approval waits. A completed turn shows `status`,
`completed`, `terminal_reason`, `final`, and the backing run summary path.

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

Provider token streaming remains deferred; v0.5 focuses on status-level live
output so JSON action parsing stays deterministic.

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
