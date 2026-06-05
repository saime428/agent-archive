# Python CLI Agent Core Design

## Goal

Build a Python CLI agent from scratch. The first version should be a stable, extensible core for code development tasks, with a small local document research module for PDF and Office files.

The agent should run from the command line, use DeepSeek as the first real LLM provider, manage local project context, call tools through an internal action protocol, enforce Codex-like safety boundaries, load skills, run lifecycle hooks, and keep Claude-like memory with confirmed writes.

## Non-Goals

- No full-screen TUI in the first version.
- No general web search or browser automation in the first version.
- No complex Office editing, OCR, formula editing, or PowerPoint layout generation.
- No fully automatic long-term memory writes by default.
- No marketplace or remote skill installation in the first version.
- No native binary packaging in the first version, though the structure should allow it later.

## Selected Approach

Use the "extensible minimal core" approach.

The first version includes the core agent loop, context management, internal tool protocol, safety policy, run logging, configuration, skill loading, hooks, and a lightweight memory system. Code development and local document research are implemented as built-in capability modules on top of the same core.

This avoids a throwaway prototype while keeping the scope smaller than a full all-purpose office and coding agent.

## Architecture

The system is split into clear layers:

- CLI Layer: parses commands, options, and interactive prompts.
- Agent Core: owns the run loop, context assembly, action execution, recovery, and final summary.
- LLM Layer: provides a unified `LLMClient` interface. The first real provider is `DeepSeekClient`; tests use `FakeLLMClient`.
- Tool Layer: provides controlled operations for files, shell commands, git, documents, and reports.
- Policy Layer: enforces sandbox and approval rules before tools run.
- Memory Layer: loads relevant memory automatically and writes long-term memory only after confirmation.
- Skill Layer: loads folder-based skills from `SKILL.md` files.
- Hook Layer: exposes lifecycle extension points.
- Logging Layer: writes run logs, tool calls, summaries, and memory candidates.

The LLM never directly touches files or the shell. It emits structured actions. The core parses, validates, authorizes, executes, records, and returns observations.

## Run Flow

For `agent run "<task>"`:

1. CLI receives the task and options.
2. Config is loaded from defaults, global config, project config, and CLI overrides.
3. A `RunContext` is created with task, mode, workspace, sandbox, approval policy, and run id.
4. Project instructions, memory, skills, and recent context are loaded.
5. `PromptBuilder` creates a compact context pack for the LLM.
6. The LLM returns a strict JSON action envelope.
7. `ActionParser` validates the action.
8. `Policy` checks whether the action is allowed, needs confirmation, or must be denied.
9. `ToolExecutor` runs the tool and returns an observation.
10. The observation is logged and sent back into the loop.
11. The loop stops on `done`, `blocked`, `need_user_confirm`, or a configured iteration limit.
12. The agent writes `summary.md`, tool call logs, and memory candidates.
13. Candidate memory is written only if the user accepts it, or if `--memory-auto-write` is set.

## Core Data Types

- `RunContext`: task, working directory, mode, sandbox, approval policy, selected skills, run id, and timestamps.
- `ContextPack`: compact context sent to the model, including instructions, memory, skills, file summaries, and recent observations.
- `Action`: structured model request such as `read_file`, `apply_patch`, or `run_command`.
- `Observation`: structured result returned to the model after tool execution.
- `ToolResult`: raw tool outcome including stdout, stderr, exit code, changed files, and errors.
- `RunLog`: persistent record of tool calls, confirmations, decisions, and final outcome.
- `MemoryCandidate`: proposed long-term memory item extracted at the end of a run.

## LLM Interface

The core depends on an abstract interface:

```python
class LLMClient:
    def chat(self, messages: list[dict], *, temperature: float | None = None) -> dict:
        ...
```

First implementations:

- `DeepSeekClient`: calls the DeepSeek API using `httpx`. The API key is read from `DEEPSEEK_API_KEY` or config.
- `FakeLLMClient`: deterministic fake responses for tests and dry runs.

The model provider is not allowed to define the internal tool protocol. Provider-specific formats are adapted at the LLM layer.

## Action Protocol

The model must return a strict JSON envelope:

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

Supported terminal actions include:

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
- `read_pdf`
- `read_docx`
- `read_xlsx`
- `read_pptx`
- `write_markdown_report`
- `write_docx_report`

If the model returns invalid JSON, the core enters a repair loop and asks the model to emit a valid action. Unknown tools or invalid arguments produce an observation error instead of running anything.

## CLI Commands

Primary commands:

```text
agent run "<task>"
agent "<task>"
agent chat
agent status
```

Run history:

```text
agent runs list
agent runs show <run-id>
```

Memory:

```text
agent memory list
agent memory add
agent memory review
agent memory edit
```

Skills:

```text
agent skills list
agent skills show <name>
```

Tools and config:

```text
agent tools list
agent config show
agent config doctor
agent doctor
```

Core options:

```text
--mode step|guided|auto|plan-first
--sandbox read-only|workspace-write|danger-full-access
--approval risky-confirm|always|never
--skill <name>
--memory-auto-write
--dry-run
--cwd <path>
```

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

Low-risk examples:

- Read files inside the workspace.
- Search with `rg`.
- Run `git status` and `git diff`.
- Run known test, lint, or format commands.
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

Each tool call is logged with action, args, approval result, and observation.

## Tools

Code development tools:

- `read_file`
- `write_file`
- `apply_patch`
- `search_files`
- `list_dir`
- `run_command`
- `git_status`
- `git_diff`

Document tools:

- `read_pdf`: extract text from local PDF files.
- `read_docx`: extract paragraphs and headings.
- `read_xlsx`: list sheets, columns, sample rows, and basic shape.
- `read_pptx`: extract slide titles and text.
- `write_markdown_report`: write a Markdown report.
- `write_docx_report`: write a Word report.

The first version supports reading and summarizing local PDF, Word, Excel, and PowerPoint files, then generating Markdown or Word reports. It does not edit existing Office documents in place.

## Memory

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

1. Load `AGENTS.md` if present.
2. Load `.agent/memory/MEMORY.md` if present.
3. Select relevant memory files by simple keyword matching and optional model-assisted selection.
4. Add the selected memory snippets to the context pack.

Write path:

1. At run end, extract candidate memories from user preferences, project facts, repeated corrections, and durable workflow rules.
2. Show candidates to the user.
3. Accept, reject, or edit candidates.
4. Write accepted candidates to the right memory file and update `MEMORY.md`.

`--memory-auto-write` bypasses confirmation for the current run, but the default remains confirmation before writing.

## Skills

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

First built-in skills:

- `code-dev`
- `doc-research`

Future skill directories may contain scripts, templates, and resources, but the first version only needs to load instructions and metadata.

## Hooks

The first version supports these lifecycle hooks:

- `before_run`
- `before_tool`
- `after_tool`
- `after_run`
- `before_memory_write`

Hooks are optional. The first implementation can be local Python callables or config-driven commands, with a simple event payload. Hook failures are logged. By default, hook failures should not crash the run unless configured as blocking.

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

## Output and Logs

Terminal output is structured and concise:

```text
[run] Goal: fix failing tests
[context] Loaded AGENTS.md, 2 memories, code-dev skill
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
- `memory_candidates.md`

## Project Structure

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
        deepseek.py
        fake.py
      tools\
        filesystem.py
        shell.py
        git.py
        documents.py
        reports.py
      policy\
        sandbox.py
        approvals.py
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

Runtime dependencies:

- `typer`
- `rich`
- `pydantic`
- `httpx`
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

Test coverage should focus on behavior and safety:

- Config merge precedence.
- Action JSON parsing and repair failures.
- Unknown tool and invalid argument handling.
- Workspace sandbox path checks.
- Risky command detection and approval behavior.
- Skill discovery and `SKILL.md` loading.
- Memory index loading and candidate write confirmation.
- PDF, Word, Excel, and PowerPoint extraction smoke tests.
- Run logging.
- End-to-end run loop using `FakeLLMClient`.

DeepSeek integration should be covered by `agent doctor` and optional manual tests, not required in the default automated test suite.

## Acceptance Criteria

The first version is acceptable when:

- `agent run "<task>"` can execute a simple fake or real code task through the action loop.
- The CLI exposes the agreed basic command surface.
- DeepSeek config can be diagnosed.
- Workspace write boundaries are enforced.
- Risky commands require confirmation under the default policy.
- Skills can be listed, shown, and loaded.
- Memory can be listed and candidate writes can be reviewed.
- PDF, Word, Excel, and PowerPoint files can be read at a basic level.
- Markdown and Word reports can be generated.
- Each run produces durable logs and a summary.
- Tests cover the core parser, policy, config, skill, memory, and fake end-to-end flow.

## First-Version Defaults

- DeepSeek model default: `deepseek-chat`, configurable through global config, project config, or CLI override.
- Hook implementation: in-process Python hook registry only. Shell-command hooks are postponed because they need their own approval and sandbox policy.
- Built-in skill location: package-provided built-in skills, with project overrides and additions loaded from `.agent/skills`.
- Memory retrieval: deterministic keyword and filename matching only. Embeddings and model-assisted memory selection are postponed.
- Report output: Markdown is the default report format; Word reports are generated only when requested.

These defaults keep the first implementation deterministic, testable, and safe while leaving clear extension points.
