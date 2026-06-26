# Agent Roadmap Progress

Last updated: 2026-06-26

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
| Visual Workbench product | 45% | Usable shell with files, diffs, restore, and browser chat |
| Overall final goal | 60-65% | Past "can it run", now improving "is it pleasant and safe to use" |

These percentages are product estimates, not exact engineering metrics.

## Completed Milestones

| Version | Theme | Completed capabilities |
| --- | --- | --- |
| v0.1 | Safe core | Structured actions/observations, file tools, shell/git tools, approval, dry-run, redaction, context budget, repair loop, durable runs, snapshots |
| v0.2 | Providers and extensions | DeepSeek provider/config, skills, memory, hooks, diagnostics |
| v0.3 | Document tools | PDF/DOCX/XLSX/PPTX readers, Markdown report writer, source-grounded document handling |
| v0.4 | Real model loop | DeepSeek smoke, live provider run, observation feedback, readable final/summary output |
| v0.5 | Terminal agent | `agent chat`, session history, resume, interactive approval, `@file`/`@dir`, slash commands, DeepSeek streaming preview |
| v0.6 | Visual Workbench | Local web UI, browser chat, browser confirmation, run trace, file tree, file preview, snapshots, diff viewer, snapshot restore |

## Active v0.6 Plan

1. Browser live events
   - Show immediate UI state for model calls, tool execution, approval waits,
     and run completion.
   - Keep action parsing unchanged; live events are display-only.

2. Custom approval panel
   - Replace `window.confirm`.
   - Show action name, arguments, affected files, snapshot/diff context, and
     Approve/Deny buttons.

3. Minimal file editor
   - Start with textarea editing, not Monaco.
   - Save through existing approval and snapshot paths.

4. Auto-refresh and status bar
   - Refresh runs after browser turns and restores.
   - Surface provider/model/API-key presence/session status in one place.

5. v0.6 closeout
   - Freeze Workbench MVP docs, manual smoke steps, and acceptance checklist.

## Later Roadmap

| Version | Goal | Notes |
| --- | --- | --- |
| v0.7 | Product shell decision | Move to Vue/Vite only when static UI state becomes painful; package with Electron/Tauri only after browser UI stabilizes |
| v0.8 | Stronger coding workflow | Test suggestions, failure reading, patch review, git checkpoint UI, branch/commit helpers |
| v0.9 | Audit and resilience | Run replay, log filters, workspace risk hints, memory review UI, stronger failure recovery |
| v1.0 | Local product release | One-command startup, settings page, model switching, desktop packaging, stable docs and smoke tests |

## Current Recommendation

Next slice: v0.6 Browser Live Events.

Reason: the Workbench can already chat, inspect files, view diffs, and restore
snapshots. The biggest user-experience gap is that the browser still waits
synchronously after Send. Live status makes the UI feel alive without adding a
new editing surface or a frontend framework.

## Guardrails

- Keep secrets in environment variables, not repo files.
- Keep `docs/main.pdf` as untracked user reference material unless explicitly
  requested otherwise.
- Prefer stdlib/static UI until the existing approach hurts.
- Do not weaken sandbox, approval, redaction, snapshot, or durable log behavior
  for visual convenience.
