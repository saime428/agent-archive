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

v0.1 intentionally uses `FakeLLMClient`. Real provider support, skills, memory,
hooks, and document tools are staged for later releases.
