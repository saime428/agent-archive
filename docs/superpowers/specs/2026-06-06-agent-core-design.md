# Python CLI Agent Core Design

## Goal

Build a Python CLI agent from scratch. The first releases should create a stable, extensible core for code development tasks first, then add provider, skill, memory, and local document research capabilities in later increments.

The agent should run from the command line, manage local project context, call tools through a versioned internal action protocol, enforce Codex-like safety boundaries, and keep durable run logs. DeepSeek, skills, memory, hooks, and local PDF/Office document tools are staged after the core safety and protocol layer is working.

## Non-Goals

- No full-screen TUI in the first version.
- No general web search or browser automation in the first version.
- No complex Office editing, OCR, formula editing, or PowerPoint layout generation.
- No fully automatic long-term memory writes by default.
- No marketplace or remote skill installation in the first version.
- No native binary packaging in the first version, though the structure should allow it later.
- No document tools in `v0.1`; PDF and Office support starts in `v0.3`.

## Selected Approach

Use the "extensible minimal core" approach.

The first version is split into three increments:

- `v0.1 Core MVP`: CLI run and doctor commands, config merge, `AGENTS.md` loading, fake LLM, versioned action and observation schemas, code-development tools, workspace sandbox, risky-confirm approval, non-interactive approval failure semantics, shell network disabled by default, write snapshots with restore guidance, context budget limits, redacted run logs, and core tests.
- `v0.2 Provider + Skills + Memory + Hooks`: DeepSeek provider, skills list/show/load with progressive disclosure, memory list/review/confirmed write, memory provenance, timestamps, undo support, retrieval budget limits, and disabled-by-default hooks.
- `v0.3 Documents`: PDF and Office reading, Markdown and Word report writing, and explicit document prompt-injection isolation.

This avoids a throwaway prototype while keeping each release small enough to test and trust.

## Architecture

The system is split into clear layers:

- CLI Layer: parses commands, options, and interactive prompts.
- Agent Core: owns the run loop, context assembly, action execution, recovery, and final summary.
- LLM Layer: provides a unified `LLMClient` interface. `v0.1` uses `FakeLLMClient`; `v0.2` adds `DeepSeekClient`.
- Tool Layer: provides controlled operations for files, shell commands, git, documents, and reports as each release enables them.
- Policy Layer: enforces sandbox and approval rules before tools run.
- Memory Layer: added in `v0.2`; loads relevant memory automatically and writes long-term memory only after confirmation.
- Skill Layer: added in `v0.2`; loads folder-based skills from `SKILL.md` files without bypassing policy.
- Hook Layer: added in `v0.2` after the core policy path exists; hooks are disabled by default and are policy-checked before execution.
- Logging Layer: writes run logs, tool calls, summaries, and, in `v0.2+`, memory candidates.

The LLM never directly touches files or the shell. It emits structured actions. The core parses, validates, authorizes, executes, records, and returns observations.

## Run Flow

For `agent run "<task>"`:

1. CLI receives the task and options.
2. Config is loaded from defaults, global config, project config, and CLI overrides.
3. A `RunContext` is created with task, mode, workspace, sandbox, approval policy, and run id.
4. `AGENTS.md` project instructions are loaded in `v0.1`; memory, skills, and recent context are loaded when later releases support them.
5. `PromptBuilder` creates a compact context pack for the LLM.
6. The LLM returns a strict, versioned JSON action envelope.
7. `ActionParser` validates the action.
8. `Policy` checks whether the action is allowed, needs confirmation, or must be denied.
9. If the action needs confirmation but the run is non-interactive or `approval=never`, the core returns an `APPROVAL_REQUIRED` or `POLICY_DENIED` observation immediately instead of waiting.
10. If the action will write files, `ToolExecutor` saves affected-file snapshots before modifying anything.
11. `ToolExecutor` runs the tool and returns an observation.
12. The observation is logged and sent back into the loop.
13. The loop stops on `done`, `blocked`, `need_user_confirm`, a policy failure that cannot proceed, or a configured iteration limit.
14. The agent writes `summary.md`, tool call logs, and restore guidance for any snapshots.
15. In `v0.2+`, candidate memory is written only if the user accepts it, or if `--memory-auto-write` is set.

## Core Data Types

- `RunContext`: task, working directory, mode, sandbox, approval policy, selected skills, run id, protocol version, and timestamps.
- `ContextPack`: compact context sent to the model, including instructions, memory, skills, file summaries, and recent observations.
- `Action`: structured internal request with `protocol_version`, `run_id`, `action_id`, `created_at`, tool name, and arguments. The core generates or overwrites all protocol metadata.
- `Observation`: structured result returned after tool execution with matching ids, status, error code, output summary, and optional data.
- `ToolResult`: raw tool outcome including stdout, stderr, exit code, changed files, and errors.
- `RunLog`: persistent record of tool calls, confirmations, decisions, and final outcome.
- `ContextBudget`: per-run limits for context assembly, tool output excerpts, observations, repair turns, and loop iterations. `v0.1` uses character and item limits, not token-perfect accounting.
- `FileSnapshot`: pre-write copy or metadata record for an affected path, including original path, snapshot path, hash when available, action id, timestamp, and whether the original file existed.
- `RunSnapshot`: collection of `FileSnapshot` records for a run, stored under `.agent/runs/<run-id>/snapshots/` with restore instructions.
- `MemoryCandidate`: proposed long-term memory item with source run id, source excerpt, timestamps, status, and revision metadata.

## LLM Interface

The core depends on an abstract interface:

```python
class LLMClient:
    def chat(self, messages: list[dict], *, temperature: float | None = None) -> dict:
        ...
```

Implementations by release:

- `v0.1`: `FakeLLMClient` with deterministic fake responses for tests and dry runs.
- `v0.2`: `DeepSeekClient`, which calls the DeepSeek API using `httpx`. The API key is read from `DEEPSEEK_API_KEY` or config.

The model provider is not allowed to define the internal tool protocol. Provider-specific formats are adapted at the LLM layer.

## Action Protocol

The model must return a strict JSON envelope, but it is not trusted to provide protocol metadata. The model output contains only user-visible message text and a requested tool action:

```json
{
  "message": "I need to inspect the project structure first.",
  "action": {
    "name": "search_files",
    "args": {
      "query": "*.py"
    }
  }
}
```

After parsing, the core creates the internal versioned action by injecting `protocol_version`, `run_id`, `action_id`, and `created_at`. If a model includes these metadata fields anyway, the core ignores them or overwrites them. Model-provided ids and timestamps must never be used for log correlation, approval state, or observation matching.

Internal action shape:

```json
{
  "protocol_version": "agent-action-v1",
  "run_id": "20260606-120000-a1b2c3",
  "action_id": "act_000001",
  "created_at": "2026-06-06T12:00:00Z",
  "message": "I need to inspect the project structure first.",
  "action": {
    "name": "search_files",
    "args": {
      "query": "*.py"
    }
  }
}
```

Every tool execution returns an `Observation`:

```json
{
  "protocol_version": "agent-observation-v1",
  "run_id": "20260606-120000-a1b2c3",
  "action_id": "act_000001",
  "observation_id": "obs_000001",
  "created_at": "2026-06-06T12:00:01Z",
  "status": "ok",
  "error": null,
  "summary": "Found 3 Python files.",
  "data": {
    "matches": ["src/agent/cli.py", "src/agent/core/loop.py"]
  }
}
```

Error observations use the same schema:

```json
{
  "protocol_version": "agent-observation-v1",
  "run_id": "20260606-120000-a1b2c3",
  "action_id": "act_000002",
  "observation_id": "obs_000002",
  "created_at": "2026-06-06T12:00:03Z",
  "status": "error",
  "error": {
    "code": "POLICY_DENIED",
    "message": "Command is denied by policy.",
    "details": {
      "category": "dangerous_delete"
    }
  },
  "summary": "Denied command before execution.",
  "data": null
}
```

Standard error codes:

- `INVALID_JSON`
- `UNSUPPORTED_PROTOCOL_VERSION`
- `MISSING_REQUIRED_FIELD`
- `UNKNOWN_TOOL`
- `INVALID_ARGUMENT`
- `SANDBOX_VIOLATION`
- `APPROVAL_REQUIRED`
- `APPROVAL_DENIED`
- `POLICY_DENIED`
- `TOOL_FAILED`
- `TIMEOUT`
- `INTERNAL_ERROR`

## Context Budget

`ContextBudget` exists in `v0.1` because even the minimal core must protect itself from unbounded prompts, logs, and observations. The first implementation does not need exact tokenizer accounting; deterministic character and item limits are enough.

Budgeted inputs and outputs include:

- `AGENTS.md` content loaded into the prompt.
- `read_file` excerpts and large file handling.
- `search_files` match count and per-match excerpt length.
- `run_command` stdout and stderr excerpts.
- Observation `summary` and `data` payload size.
- Repair loop turns after invalid JSON.
- Maximum action loop iterations per run.

When content exceeds budget, the core must truncate with an explicit truncation marker, preserve source path and locator metadata where possible, and log that truncation happened. Large files should be chunked only when the tool explicitly supports chunking; otherwise the tool returns a bounded observation that asks for a narrower read.

Supported `v0.1` terminal actions:

- `done`: finish with a final answer.
- `ask_user`: request clarification or approval.
- `read_file`
- `write_file`
- `apply_patch`
- `search_files`
- `list_dir`
- `run_command`
- `git_status`
- `git_diff`

Supported `v0.3` document actions:

- `read_pdf`
- `read_docx`
- `read_xlsx`
- `read_pptx`
- `write_markdown_report`
- `write_docx_report`

If the model returns invalid JSON, the core enters a bounded repair loop and asks the model to emit a valid action. Unknown tools or invalid arguments produce an error observation instead of running anything. The repair loop must not execute partial or inferred actions.

## CLI Commands

`v0.1` primary commands:

```text
agent run "<task>"
agent "<task>"
agent doctor
agent runs list
agent runs show <run-id>
```

`v0.2+` commands:

```text
agent chat
agent status
agent skills list
agent skills show <name>
agent memory list
agent memory add
agent memory review
agent memory undo <memory-id>
```

Run history:

```text
agent runs list
agent runs show <run-id>
```

`agent runs show <run-id>` is part of `v0.1` because write snapshots are not useful unless the user can inspect where they were stored and how to restore them. `agent runs list` may be a minimal listing in `v0.1`.

Tools and config:

```text
agent tools list
agent config show
agent config doctor
```

Core options:

```text
--mode step|guided|auto|plan-first
--sandbox read-only|workspace-write|danger-full-access
--approval risky-confirm|always|never
--skill <name>               # v0.2+
--memory-auto-write          # v0.2+
--dry-run
--cwd <path>
```

In `v0.1`, `--dry-run` parses and validates the planned action flow but does not execute write tools or shell commands. A dry run may call the fake model, build context, classify actions, and report which actions would need approval.

Defaults:

```text
mode = guided
sandbox = workspace-write
approval = risky-confirm
memory writes = confirm first
```

## Modes

- `step`: execute at most one action, then stop for user input.
- `guided`: default. Run several safe actions but stop for important decisions and risky actions.
- `auto`: continue within safety boundaries until done, blocked, or iteration limit.
- `plan-first`: produce a plan and wait for approval before executing changes.

## Safety Policy

Sandbox modes:

- `read-only`: read files and inspect state only.
- `workspace-write`: default. Read and write only inside the current workspace.
- `danger-full-access`: reserved for explicit use; not recommended as a default.

Approval modes:

- `risky-confirm`: low-risk actions run automatically; risky actions require confirmation.
- `always`: every tool action requires confirmation.
- `never`: no interactive approvals; unsafe actions are denied.

Non-interactive approval behavior:

- If stdin is not a TTY, the user requested `--approval never`, or the host process marks the run as non-interactive, an action that needs approval must fail fast.
- Fail-fast observations use `APPROVAL_REQUIRED` when the action could be allowed with user approval, and `POLICY_DENIED` when it is categorically denied.
- The core must never block indefinitely waiting for approval in a one-shot CLI run.

Low-risk examples:

- Read files inside the workspace.
- Search with `rg`.
- Run `git status` and `git diff`.
- Run package-provided known-safe test commands.
- Create normal project files inside the workspace.

Risky examples:

- Delete files or directories.
- Write outside the workspace.
- Install dependencies.
- Execute network commands.
- Run unknown scripts.
- Modify system paths.
- Clear directories.
- Handle content that looks like secrets.
- Use shell commands that appear to access the network.

Each tool call is logged with action, args, approval result, and observation.

Sandbox checks must use resolved filesystem paths, not string prefix checks. The implementation must:

- Resolve the configured workspace root to a canonical path.
- Resolve each target path before access.
- Normalize path casing on case-insensitive filesystems such as Windows.
- Reject paths that resolve outside the workspace in `workspace-write`.
- Reject symlink and junction escapes even when the original input path starts with the workspace path.
- Treat missing write targets by resolving the nearest existing parent and checking that parent stays inside the workspace.

`run_command` must use structured argv, not a raw shell string, unless a command is explicitly classified as requiring a shell. The policy checks the executable and arguments before execution.

Command categories:

- Allowed by default: built-in read-only commands such as `git status`, `git diff`, `rg`, read-only directory listing, and package-provided known-safe test commands such as `pytest` when arguments stay inside the workspace.
- Requires confirmation: project-configured test/lint/format commands, dependency installation, package-manager commands, commands that write many files, scripts from the repository, long-running commands, and commands with shell metacharacters.
- Denied by default: recursive delete, disk formatting, permission changes outside the workspace, writing system paths, credential exfiltration patterns, shell pipelines that hide subcommands, and commands that target paths outside the sandbox.

Shell network policy:

- `v0.1` shell network access is disabled by default.
- Network-like commands such as `curl`, `wget`, `Invoke-WebRequest`, `Invoke-RestMethod`, `ssh`, `scp`, `rsync`, package registry access, and repository cloning are denied or require explicit confirmation according to policy.
- The DeepSeek HTTP provider in `v0.2` is a separate configured client capability and does not imply shell network permission.
- Project config cannot silently enable shell network commands.

Project config must not upgrade commands into the allowlist. Every project-configured command is parsed into structured argv and classified by the same policy as model-requested commands. Unknown project-configured commands require confirmation by default.

`run_command` logs argv, working directory, environment allowlist, timeout, policy decision, exit code, stdout/stderr summaries, whether output was truncated, and whether redaction changed the output.

Before any durable log write, the logging layer must redact secret-like values from tool args, environment values, stdout, stderr, observations, summaries, and document excerpts. Raw stdout/stderr persistence is disabled by default. The default log contains summaries and truncated, redacted excerpts only. If output contains likely credentials, API keys, tokens, private keys, or authorization headers, the observation is marked with a redaction warning and any follow-up action that would expose the secret is denied or requires explicit confirmation.

## Tools

`v0.1` code development tools:

- `read_file`
- `write_file`
- `apply_patch`
- `search_files`
- `list_dir`
- `run_command`
- `git_status`
- `git_diff`

`write_file` and `apply_patch` must pass sandbox and policy checks before modifying anything. For patches, the executor must parse all affected file paths before applying the patch and validate each target. Patch deletion, rename, mode changes, binary patches, absolute paths, parent-directory traversal, and paths resolving outside the workspace are denied by default or require explicit confirmation according to policy. A patch must be applied atomically where practical; partial application after a denied target is not allowed.

Before `write_file` or `apply_patch` changes a file, the executor stores an affected-file snapshot under `.agent/runs/<run-id>/snapshots/`. Existing files are copied or otherwise captured with enough metadata to restore them. Newly created files record a snapshot entry that marks the previous state as non-existent. `summary.md` and `agent runs show <run-id>` must include snapshot locations and restore instructions. `v0.1` does not auto-commit every tool change to git; run snapshots are the default recovery mechanism.

`v0.3` document tools:

- `read_pdf`: extract text from local PDF files.
- `read_docx`: extract paragraphs and headings.
- `read_xlsx`: list sheets, columns, sample rows, and basic shape.
- `read_pptx`: extract slide titles and text.
- `write_markdown_report`: write a Markdown report.
- `write_docx_report`: write a Word report.

Document contents are untrusted data. Extracted PDF and Office text must be wrapped in a context section that says it is source material only, not instructions. Document text must not override system, developer, user, policy, memory, or skill instructions. Malicious document text such as "ignore previous instructions" is summarized as document content and must never trigger a tool call or change the agent policy.

Document tool output enters the prompt only as a quoted source-material block with source path, extraction timestamp, page/sheet/slide locator when available, and a fixed warning that the block is data, not instructions. The document block has a configurable maximum length and must be summarized before inclusion when it exceeds the limit. Document-derived text cannot directly create an action. The agent may only execute a follow-up tool call when the user task or an existing trusted instruction requests that operation; instructions found inside the document are never treated as trusted requests.

## Memory

Memory starts in `v0.2`.

Memory uses a Claude-like lite design:

```text
.agent/
  memory/
    MEMORY.md
    user_preferences.md
    project_context.md
    coding_style.md
    feedback.md
  runs/
    <run-id>/
      log.md
      tool_calls.jsonl
      summary.md
      memory_candidates.md
```

Read path:

1. Load `.agent/memory/MEMORY.md` if present.
2. Select relevant memory files by simple keyword matching and optional model-assisted selection.
3. Apply the run `ContextBudget` to memory item count and snippet length.
4. Add the selected memory snippets to the context pack.

Write path:

1. At run end, extract candidate memories from user preferences, project facts, repeated corrections, and durable workflow rules.
2. Show candidates to the user.
3. Accept, reject, or edit candidates.
4. Write accepted candidates to the right memory file and update `MEMORY.md`.
5. Record provenance and revision metadata.

`--memory-auto-write` bypasses confirmation for the current run, but the default remains confirmation before writing.

Each memory item must include:

- Stable memory id.
- Source run id.
- Source excerpt or source summary.
- Created timestamp.
- Updated timestamp.
- Status: `active`, `superseded`, or `deleted`.
- Optional replacement memory id.

Memory undo must be reversible. The first implementation uses tombstones or revision history instead of silently deleting historical entries.

## Skills

Skills start in `v0.2`.

Skills are folder-based:

```text
.agent/
  skills/
    code-dev/
      SKILL.md
    doc-research/
      SKILL.md
```

`SKILL.md` supports frontmatter:

```yaml
---
name: code-dev
description: Code development, bug fixing, tests, and refactoring
allowed_tools:
  - read_file
  - apply_patch
  - run_command
---
```

The body contains instructions loaded into the context. Skills can be selected automatically by description matching or manually with `--skill`.

Skill priority:

```text
CLI --skill > project config default_skills > automatic task matching > package default skills
```

Skills cannot grant permissions that global policy or sandbox denies. A skill may suggest or narrow allowed tools for the task, but all tool calls still pass through policy. Project skills are untrusted unless explicitly enabled by config or CLI.

Skill loading uses progressive disclosure in `v0.2`:

1. Discovery loads only name, description, path, and declared tool hints.
2. Selection uses CLI `--skill`, project config, automatic matching, or package defaults according to the priority order above.
3. The full `SKILL.md` body is loaded only after a skill is selected.
4. Loaded skill text is subject to `ContextBudget` and cannot override system, developer, current user, policy, sandbox, approval, or redaction rules.

First built-in skills in `v0.2`:

- `code-dev`
- `doc-research`

Future skill directories may contain scripts, templates, and resources, but `v0.2` only needs to load instructions and metadata.

## Hooks

Hooks start after the core policy path exists. The first hook implementation supports these lifecycle hooks:

- `before_run`
- `before_tool`
- `after_tool`
- `after_run`
- `before_memory_write`

Hooks are disabled by default.

The first implementation only supports:

- Package-provided built-in hooks.
- Project hooks that are explicitly enabled in config.

Every hook execution is represented as an internal action and must pass through policy before it runs. Shell-command hooks are postponed until a dedicated approval and sandbox policy exists. Hook failures are logged. By default, hook failures do not crash the run unless configured as blocking.
Hooks belong to `v0.2`. They are not required for `v0.1` acceptance and should not be scaffolded in the `v0.1` implementation unless a minimal no-op interface is needed to keep module boundaries stable.

## Configuration

Config precedence:

```text
defaults < ~/.agent/config.toml < .agent/config.toml < CLI options
```

Important config keys:

- `provider`
- `model`
- `deepseek_api_key_env`
- `mode`
- `sandbox`
- `approval`
- `default_skills`
- `memory.auto_write`
- `memory.max_items`
- `commands.test`
- `commands.lint`
- `commands.format`

`agent config show` displays the merged config. `agent config doctor` checks config files, API key availability, writable directories, and document dependencies.
In `v0.1`, `agent doctor` only checks local environment, config readability, workspace permissions, and core command availability. DeepSeek checks start in `v0.2`; document dependency checks start in `v0.3`.

`AGENTS.md` loading in `v0.1` is read-only and lower priority than system, developer, and current user instructions. It can provide project conventions and workflow notes, but it cannot widen sandbox permissions, bypass approval, disable redaction, or redefine policy.

## Output and Logs

Terminal output is structured and concise:

```text
[run] Goal: fix failing tests
[context] Loaded workspace config
[tool] run_command: pytest
[result] 3 failed, 21 passed
[edit] apply_patch: src/example.py
[verify] pytest
[done] Tests passed. Summary written.
```

The agent shows short reasons, planned actions, tool names, and results. It does not print long hidden reasoning chains.

Each run writes:

- `log.md`
- `tool_calls.jsonl`
- `summary.md`
- `memory_candidates.md` in `v0.2+`

## Project Structure

The structure is staged. `v0.1` should only create modules required for the core MVP; later directories are added when their release starts.

`v0.1` minimum structure:

```text
F:\agent\
  pyproject.toml
  README.md
  AGENTS.md
  src\
    agent\
      __init__.py
      cli.py
      config.py
      core\
        loop.py
        context.py
        actions.py
        prompts.py
      llm\
        base.py
        fake.py
      tools\
        filesystem.py
        shell.py
        git.py
      policy\
        sandbox.py
        approvals.py
      logging\
        run_log.py
  tests\
  docs\
    superpowers\
      specs\
        2026-06-06-agent-core-design.md
```

Later releases add provider, memory, skills, hooks, and document modules:

```text
F:\agent\
  src\
    agent\
      llm\
        deepseek.py
      tools\
        documents.py
        reports.py
      memory\
        store.py
        retrieval.py
        extraction.py
      skills\
        loader.py
      hooks\
        manager.py
      logging\
        run_log.py
  tests\
  docs\
    superpowers\
      specs\
        2026-06-06-agent-core-design.md
```

## Dependencies

Use `uv` and `pyproject.toml`.

`v0.1` runtime dependencies:

- `typer`
- `rich`
- `pydantic`

`v0.2` runtime dependencies:

- `httpx`

`v0.3` runtime dependencies:

- `pypdf`
- `python-docx`
- `openpyxl`
- `python-pptx`

Development dependencies:

- `pytest`
- optional: `ruff`

The CLI entry point is exposed through a console script named `agent`.

## Packaging

First version:

- Install and run with `uv`.
- Support `uv tool install` or `pipx install` once packaged.

Future:

- Package as a single executable with PyInstaller or Nuitka.
- Keep the CLI and core independent from packaging details.

## Testing

`v0.1` tests:

- Config merge precedence.
- `AGENTS.md` loading.
- Action and observation schema validation.
- Core-generated action metadata; model-provided metadata is ignored or overwritten.
- Standard error codes.
- Action JSON parsing and bounded repair failures.
- Unknown tool and invalid argument handling.
- Workspace sandbox path checks.
- Symlink or junction escape rejection.
- Risky command detection and approval behavior.
- Project-configured commands require confirmation by default.
- Dangerous command denial.
- Shell network command denial or confirmation under default policy.
- Non-interactive approval failure for actions that require confirmation.
- `--dry-run` has no file-write or shell-command side effects.
- Log redaction of secret-like values.
- Context budget truncation for `AGENTS.md`, file reads, command output, observations, repair loop, and iteration limits.
- `apply_patch` multi-path sandbox and denied-target handling.
- Pre-write snapshots and restore guidance for `write_file` and `apply_patch`.
- Run logging.
- End-to-end run loop using `FakeLLMClient`.

`v0.2` tests:

- DeepSeek config diagnosis.
- Skill discovery, priority, and permission boundaries.
- Skill progressive disclosure and context budget enforcement.
- Memory index loading.
- Memory retrieval budget limits.
- Confirmed memory write.
- Memory undo through tombstone or revision history.
- Hooks disabled by default, explicit enablement, and policy checks before execution.

`v0.3` tests:

- PDF, Word, Excel, and PowerPoint extraction smoke tests.
- Document prompt-injection isolation.
- Markdown and Word report generation.
- Malicious document text cannot trigger tool calls or mutate instructions.

DeepSeek integration should be covered by `agent doctor` and optional manual tests, not required in the default automated test suite.

## Acceptance Criteria

`v0.1 Core MVP` is acceptable when:

- `agent run "<task>"` can execute a simple fake code task through the action loop.
- `agent doctor` can inspect the local environment.
- `agent runs show <run-id>` can display run logs, snapshot locations, and restore guidance.
- `AGENTS.md` is loaded as read-only project instruction context when present.
- Config merge works across defaults, global config, project config, and CLI overrides.
- The versioned Action and Observation schemas are enforced.
- Action metadata used for logs and observations is generated by the core, not trusted from the model.
- Standard error codes are emitted for parser, policy, sandbox, and tool failures.
- Workspace write boundaries are enforced.
- Symlink and junction escapes are rejected.
- Risky commands require confirmation under the default policy.
- Actions that require confirmation fail fast in non-interactive runs.
- `--dry-run` performs no write-tool or shell-command side effects.
- Shell network commands are disabled, denied, or confirmation-gated according to policy.
- Project-configured commands do not bypass approval.
- Denied commands never execute.
- Context budget limits are enforced with explicit truncation markers.
- Durable logs are redacted before write.
- Patch operations validate every affected path before applying.
- Write tools create pre-change snapshots with restore guidance.
- Each run produces durable logs and a summary.
- Tests cover config, parser, observation schema, policy, sandbox, run logs, and fake end-to-end flow.

`v0.2 Provider + Skills + Memory + Hooks` is acceptable when:

- DeepSeek config can be diagnosed.
- Skills can be listed, shown, and loaded according to priority rules.
- Skills cannot bypass policy or sandbox.
- Memory can be listed and candidate writes can be reviewed.
- Accepted memory writes include source, time, status, and revision metadata.
- Memory undo marks entries as deleted or superseded without silent deletion.
- Hooks are disabled by default, can be explicitly enabled, and pass through policy before execution.

`v0.3 Documents` is acceptable when:

- PDF, Word, Excel, and PowerPoint files can be read at a basic level.
- Markdown and Word reports can be generated.
- Extracted document text is treated as untrusted source material.
- Document content enters prompts only in quoted source-material blocks with source metadata and length limits.
- Malicious document instructions cannot override agent instructions or trigger tool calls.

## First-Version Defaults

- DeepSeek model default in `v0.2`: `deepseek-chat`, configurable through global config, project config, or CLI override.
- Hook implementation in `v0.2`: in-process Python hook registry only. Shell-command hooks are postponed because they need their own approval and sandbox policy.
- Built-in skill location in `v0.2`: package-provided built-in skills, with explicitly enabled project overrides and additions loaded from `.agent/skills`.
- Memory retrieval: deterministic keyword and filename matching only. Embeddings and model-assisted memory selection are postponed.
- Report output in `v0.3`: Markdown is the default report format; Word reports are generated only when requested.

These defaults keep the first implementation deterministic, testable, and safe while leaving clear extension points.

## Explicitly Deferred

The first implementation should learn from leading coding agents without copying features that would make the MVP too wide. These items are intentionally deferred:

- Full permission profiles beyond `sandbox`, `approval`, and command policy presets.
- Subagents, forked workers, and worktree isolation.
- MCP servers, browser automation, plugin marketplaces, remote skill installation, HTTP hooks, and prompt hooks.
- Aider-style automatic git commits after every change. `v0.1` uses run snapshots instead; optional git checkpointing can be considered later.
