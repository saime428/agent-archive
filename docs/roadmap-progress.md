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
| Visual Workbench product | 55% | v0.6 Workbench MVP frozen; product shell choices come next |
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

Next slice: v0.7 Product shell decision.

Reason: the Workbench can already chat, approve, inspect files, edit a text
file, view diffs, restore snapshots, and keep status visible. The next useful
move is deciding whether the static UI is still enough or whether the project
should graduate to Vue/Vite and a desktop shell.

## Guardrails

- Keep secrets in environment variables, not repo files.
- Keep `docs/main.pdf` as untracked user reference material unless explicitly
  requested otherwise.
- Prefer stdlib/static UI until the existing approach hurts.
- Do not weaken sandbox, approval, redaction, snapshot, or durable log behavior
  for visual convenience.
