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

`read_pdf` extracts text with `pypdf`, `read_docx` extracts paragraph text with
optional `python-docx`, and `read_xlsx` extracts sheet names, shape, headers,
and sample rows with optional `openpyxl`. `read_pptx` extracts slide titles and
text with optional `python-pptx`. These tools apply the workspace sandbox,
budget the returned text, and wrap extracted content with
`UNTRUSTED DOCUMENT SOURCE MATERIAL` so document text cannot override
instructions, policy, approval, sandbox, or tool schemas.

Markdown report generation and Word report generation remain staged for later
v0.3 slices.
