# Project Context

Last updated: 2026-07-17

## One-line Summary

This is a minimal Python 3.11+ local coding agent: a CLI engine plus a static local Workbench, built around safe structured actions, workspace sandboxing, approvals, snapshots, redacted durable logs, and optional DeepSeek provider support.

## Current State

- Roadmap is effectively complete through v1.0 and post-v1.0 polish.
- The next ecosystem horizon is defined in `docs/project-vnext-direction.md`;
  frontend work is one child track, not the whole project roadmap.
- `agent start` is the preferred local startup command; it reuses the existing `agent ui` server path.
- Browser settings remain read-only for v1.0. Config changes stay in terminal commands or explicit config-file edits.
- Binary packaging, desktop shell, and browser-side settings writes are optional trigger-based work, not open release blockers.
- `core/loop.py` recovers from recoverable tool errors: error observations are fed back to the model with a consecutive-error budget (`max_consecutive_errors`, default 3). The former Chinese-only direct helpers have been removed; all input goes through the model path.

## Main Code Map

- `src/agent/cli.py`: Typer CLI entry point.
- `src/agent/core/`: action protocol, run loop, context budget, durable run store, redaction, memory, hooks, skills, project instructions.
- `src/agent/policy/`: approval and workspace sandbox rules.
- `src/agent/tools/`: filesystem, shell, git, web, and document tools.
- `src/agent/llm/`: fake provider plus DeepSeek client/factory.
- `src/agent/web/`: stdlib local Workbench server and static UI assets.
- `tests/`: pytest coverage aligned with the modules above.

## Useful Commands

```powershell
python -m pytest -q
git diff --check
python -m agent.cli doctor
python -m agent.cli release doctor --cwd .
python -m agent.cli start --cwd .
```

## Guardrails

- Keep secrets in environment variables or `.agent/secrets.env`; never commit API keys.
- Keep `docs/main.pdf` untracked unless the user explicitly asks to commit it.
- Keep the existing static Workbench as the fallback until Frontend vNext reaches verified feature parity.
- Do not weaken sandbox, approval, redaction, snapshot, or durable-log behavior for UI convenience.
- Follow `AGENTS.md`: Chinese replies, Ponytail/minimal diffs, and commit newly created files.

## Existing Docs

- `README.md`: user-facing overview and command reference.
- `docs/project-vnext-direction.md`: project-wide ecosystem direction and dependency order.
- `docs/frontend-vnext-direction.md`: product experience and frontend migration child direction.
- `docs/roadmap-progress.md`: current roadmap status and completed slices.
- `docs/agent-interview-summary.md`: longer interview-style project pitch; useful background, but older than the v1.0 roadmap.
