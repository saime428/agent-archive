# Agent Roadmap Progress

Last updated: 2026-06-28

## Product Goal

Build a local, safe coding agent that starts as a reliable CLI engine and grows
into a visual Workbench: chat with a real model, inspect files, review diffs,
approve writes, recover snapshots, and keep durable audit logs.

The reference direction is an Apix-style local development console, but the
project keeps a smaller rule: core safety first, visual polish only after the
workflow is actually useful.

## Current Progress Estimate

| Track | Estimate | Status |
| --- | ---: | --- |
| Core agent engine | 80% | Stable enough for v0.1-v0.5 workflows |
| Visual Workbench product | 64% | v0.8 read-only workflow hints are implemented |
| Overall final goal | 65-70% | Core and first visual shell are usable; packaging and stronger coding workflow remain |

These percentages are product estimates, not exact engineering metrics.

## Completed Milestones

| Version | Theme | Completed capabilities |
| --- | --- | --- |
| v0.1 | Safe core | Structured actions/observations, file tools, shell/git tools, approval, dry-run, redaction, context budget, repair loop, durable runs, snapshots |
| v0.2 | Providers and extensions | DeepSeek provider/config, skills, memory, hooks, diagnostics |
| v0.3 | Document tools | PDF/DOCX/XLSX/PPTX readers, Markdown report writer, source-grounded document handling |
| v0.4 | Real model loop | DeepSeek smoke, live provider run, observation feedback, readable final/summary output |
| v0.5 | Terminal agent | `agent chat`, session history, resume, interactive approval, `@file`/`@dir`, slash commands, DeepSeek streaming preview |
| v0.6 | Visual Workbench | Local web UI, browser chat, browser confirmation, run trace, file tree, file preview, file editor, snapshots, diff viewer, snapshot restore |
| v0.7 | Product shell and review | Static shell decision, migration triggers, read-only task review panel, acceptance closeout |
| v0.8 | Stronger coding workflow | Read-only Workflow Hints panel with suggested verification commands |

## Active v0.6 Plan

1. Browser live events
   - Show immediate UI state for model calls, tool execution, approval waits,
     and run completion.
   - Keep action parsing unchanged; live events are display-only.
   - Done: Activity panel for browser turns, approval waits, saves, restores,
     completion, and failures.

2. Custom approval panel
   - Replace `window.confirm`.
   - Show action name, arguments, affected files, snapshot/diff context, and
     Approve/Deny buttons.
   - Done: browser chat approvals, snapshot restore approvals, and file save
     approvals use the custom panel.

3. Minimal file editor
   - Start with textarea editing, not Monaco.
   - Save through existing approval and snapshot paths.
   - Done: text file saves use `/api/file/save`, custom approval, and durable
     run snapshots.

4. Auto-refresh and status bar
   - Refresh runs after browser turns and restores.
   - Surface provider/model/API-key presence/session status in one place.
   - Done: Status Bar, DeepSeek key presence, manual Refresh, and 10-second
     safe auto-refresh.

5. v0.6 closeout
   - Freeze Workbench MVP docs, manual smoke steps, and acceptance checklist.
   - Done: v0.6 freeze status, success criteria, and next-step roadmap are
    documented.

## Active v0.7 Plan

1. Product shell decision
   - Decide whether to keep the static Workbench or scaffold Vue/Vite and a
     desktop shell.
   - Done: `docs/v0.7-shell-decision.md` keeps the stdlib static shell and
     records migration triggers.

2. Workbench task review panel
   - Add a read-only view of latest action, last observation, changed files,
     snapshots, and suggested manual checks.
   - Done: the run detail API returns `review`, and the static Workbench renders
     the Task Review panel without a new framework.

3. v0.7 closeout
   - Freeze v0.7 docs, manual smoke, and deferred shell work.
   - Done: `docs/v0.7-acceptance.md` records v0.7 freeze status and v0.8 next step.

## Active v0.8 Plan

1. Workflow Hints panel
   - Derive suggested verification commands from the selected run's changed
     files and Task Review metadata.
   - Done: run detail payload exposes `workflow.verification_commands`, and the
     static Workbench renders the read-only Workflow Hints panel.

2. Failure summary
   - Summarize failed observations and likely next checks without retrying tools.
   - Keep it read-only and log-backed.

## Later Roadmap

| Version | Goal | Notes |
| --- | --- | --- |
| v0.7 | Product shell decision | Move to Vue/Vite only when static UI state becomes painful; package with Electron/Tauri only after browser UI stabilizes |
| v0.8 | Stronger coding workflow | Test suggestions, failure reading, patch review, git checkpoint UI, branch/commit helpers |
| v0.9 | Audit and resilience | Run replay, log filters, workspace risk hints, memory review UI, stronger failure recovery |
| v1.0 | Local product release | One-command startup, settings page, model switching, desktop packaging, stable docs and smoke tests |

## Current Recommendation

Completed slice: v0.6 Browser Live Events.

Completed slice: v0.6 Auto-refresh and Status Bar.

Completed slice: v0.6 closeout.

Completed slice: v0.7 Product shell decision.

Completed slice: v0.7 Workbench task review panel.

Completed slice: v0.7 closeout.

Reason: the Workbench can already chat, approve, inspect files, edit a text
file, view diffs, restore snapshots, keep status visible, and summarize the
selected run in a read-only review panel.

Completed slice: v0.8 Workflow Hints panel.

Next slice: v0.8 failure summary.

Reason: the Workflow Hints panel now suggests verification commands without
executing them. The next useful helper is a failure summary over existing
observations and run logs.

## Guardrails

- Keep secrets in environment variables, not repo files.
- Keep `docs/main.pdf` as untracked user reference material unless explicitly
  requested otherwise.
- Prefer stdlib/static UI until the existing approach hurts.
- Do not weaken sandbox, approval, redaction, snapshot, or durable log behavior
  for visual convenience.
