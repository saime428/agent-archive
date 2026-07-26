# Agent Roadmap Progress

Last updated: 2026-07-25

Status update (2026-07-25): this file keeps the completed local-baseline
milestones and records completed Project vNext slices separately. The
project-wide direction lives in
[Project vNext Direction](project-vnext-direction.md).

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
| Core agent engine | 100% | Required local core route is complete |
| Visual Workbench product | 100% | Required local visual route is complete |
| Overall final goal | 100% | Required legacy roadmap is complete; packaging and desktop shell are trigger-based options, while bounded browser config writes are available in `/preview/` |
| Project vNext core (Phase 0–3) | — | In progress: Phase 0–2、default-entry cutover 与 Phase 3A–3I 已完成；只剩最终全量缺陷清零 |

These percentages are product estimates for the legacy local-baseline roadmap,
not a claim that the full Project vNext ecosystem is complete.

## Project vNext Extension Track

| Slice | Status | Evidence / next gap |
| --- | --- | --- |
| Phase 1: stdio MCP dynamic Tools | Complete | User-only config, SDK lifecycle, unified catalog/safety chain, and real CLI/Chat/Workbench acceptance |
| Phase 2 slice 1: managed MCP and Skills lifecycle | Complete | Managed MCP fragments/state with a live `mcp doctor`, user Skill install/update/package/remove, one shared user-store transaction layer, and crash-recovery evidence |
| Frontend vNext Phase 1: App Shell + Chat | Complete | React/Vite chat vertical slice covers C1-C9, H1/H2, S1/S2/S5 with real REST/SSE adapters, themes, responsive spatial shell, approval paths, Canvas, and regression evidence |
| Frontend vNext Phase 2: Core functional parity | Complete | Files, Runs, System, bounded non-secret config writes, visual baselines, and visible-browser acceptance are complete |
| Frontend vNext Default Entry Cutover | Complete | Root `/` serves React and `/preview/` remains compatible; the later 3I slice retired `/legacy/` and the old shell |
| Phase 3A: recoverable task lifecycle | Complete | CLI/HTTP/React share cancel, timeout, workspace lease, durable terminal, restart recovery and safe new-message resume; full source/wheel/browser evidence is recorded |
| Phase 3B: auditable Memory lifecycle | Complete | Candidate accept/reject is single-terminal; revise/delete/history preserve provenance; list/retrieve/Workbench expose only current active leaves; source/wheel/real-CLI evidence is recorded |
| Phase 3C: auditable Automation | Complete | Foreground fixed-interval worker, idempotent slot claims, shared runtime/safety chain, durable attempts/notifications, cancel/recovery and source/wheel/real-CLI evidence are complete |
| Phase 3D: stable Eval | Complete | Four fixed FakeLLM cases run through the real loop with deterministic completion/error/Tool metrics, bounded atomic reports, stable exit codes and source/wheel evidence |
| Phase 3E: Editor/Search | Complete | Lazy desktop Monaco, shared mobile textarea fallback, multi-tab dirty state, bounded recursive search/line jump, snapshot saves, Worker/package/browser evidence are complete |
| Phase 3F: Git/Diff | Complete | Read-only porcelain status and staged/unstaged diff cover repository boundaries, sandboxing, bounded output, Git edge states, React/browser/source/wheel evidence |
| Phase 3G: Terminal | Complete | Explicit enablement, shared command/path policy, structured argv, cursor output, line-mode stdin, tree stop/timeout/close, React/source/wheel/browser evidence are complete |
| Phase 3H: Command/Layout | Complete | Nine existing actions, Ctrl/Cmd+K, bounded non-sensitive layout persistence, dirty/modal/focus safeguards, React/source/wheel/browser evidence are complete |
| Phase 3I: Legacy retirement | Complete | Fourteen old static files, `/legacy/`, the synchronous chat shim and dead helpers are gone; React/source/wheel/served/browser evidence is consistent |
| Project vNext core (Phase 0–3) | In progress | Phase 3A–3I are complete; only the final conversation/generation/frontend/backend/CLI/package/browser bug pass remains |
| Phase 4–5 demand-triggered pool | Not started by design | Ecosystem UI, distribution, remote, and community work start only after their documented real-user triggers; they do not block core completion |

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
| v0.8 | Stronger coding workflow | Read-only Workflow Hints, Failure Summary, Provider Notice, Patch Review Helper |
| v0.9 | Audit and resilience | Run Risk Filter, Run Replay, Log Filters, Workspace Risk, Memory Review, Failure Recovery |
| v1.0 | Release prep | One-command startup alias, Settings Readiness, settings page decision, release readiness doctor, packaging decision, closeout |
| post-v1.0 | Polish and local secrets | Ordered polish backlog, copy pass, manual smoke, accessibility, local secret flow |
| v2.0 | Tokenicode Workbench | Tokenicode-style visual refresh, SSE browser chat, dark theme, resizable columns, conversation tabs, resource detail panels |
| vNext Phase 1 slice | Open extension kernel | Local stdio MCP dynamic Tools share the built-in Tool catalog, approval, observation, redaction, trace, and composition-root lifecycle |
| Frontend vNext Phase 1 | Spatial App Shell + Chat | Parallel React preview, typed REST/SSE seam, real chat/approval/history flow, six theme-mode sets, responsive rail, one state-driven Canvas, and Lucide-only accessible product chrome |
| Frontend vNext Phase 2 | Workspace functional parity | Files, Runs, System diagnostics, bounded config writes, snapshot review/restore confirmation, and deterministic responsive visual coverage |
| Frontend vNext Cutover | Default React entry | Root React Workbench with `/preview/` compatibility and `/legacy/` rollback |
| Frontend vNext Phase 3I | Single React runtime | Old static shell, `/legacy/`, synchronous chat compatibility and dual-frontend tests retired after independent source/wheel/browser acceptance |

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
   - Done: run detail payload exposes `failure.latest_failure`, and the static
     Workbench renders the read-only Failure Summary panel.

3. Provider notice
   - Show whether the Workbench is using FakeLLM or DeepSeek.
   - Done: `/api/health` exposes `provider_notice`, and the static Workbench
     renders it without storing API keys or writing config.

4. Patch review helper
   - Build a read-only review checklist over diffs, snapshots, workflow hints,
     and failure summary.
   - Done: run detail payload exposes `patch_review`, and the static Workbench
     renders the read-only Patch Review Helper panel.
   - Kept advisory only; no browser-side command
     execution or automatic patching.

5. v0.8 closeout
   - Done: `docs/v0.8-acceptance.md` records frozen read-only coding workflow
     status and v0.9 audit/resilience as the next track.

## Active v0.9 Plan

1. Run risk filters
   - Add `status` and `risk_level` to `/api/runs`.
   - Render status/risk on the sidebar run list.
   - Done: Run Risk Filter can show all, low, medium, or attention runs.

2. Run replay
   - Done: run detail payload exposes read-only `replay`, and the Workbench
     renders a Run Replay panel from stored tool calls without executing tools.

3. Log filters
   - Done: Log Filters narrow Trace and Run Replay by text and terminal state
     without changing logs.

4. Workspace risk hints
   - Done: `/api/health` exposes read-only `workspace_risk`, and the Workbench
     renders Workspace Risk hints for uncommitted files, snapshots, and failed
     recent runs.

5. Memory review UI
   - Done: `/api/health` exposes read-only `memory_review`, and the Workbench
     renders pending memory candidates and active entries without accept/undo.

6. Stronger failure recovery
   - Done: run detail payload exposes read-only `recovery`, and the Workbench
     renders Failure Recovery guidance without automatic rollback or retry.

7. v0.9 closeout
   - Done: `docs/v0.9-acceptance.md` records freeze status, manual smoke, and
     v1.0 deferrals.

## Active v1.0 Plan

1. One-command startup
   - Done: `agent start` is a thin alias for `agent ui`, reusing the same
     config validation and Workbench server path.

2. Settings readiness
   - Done: `/api/health` exposes read-only `settings_readiness`, and the
     Workbench renders provider/model/key/config checks without writing config.

3. Settings page decision
   - Done: `docs/v1.0-settings-page-decision.md` keeps browser settings
     read-only for v1.0 and defers config writes until a safe secret flow exists.

4. Release readiness doctor
   - Done: `agent release doctor` prints startup, provider/model, key
     presence, settings write policy, packaging status, and verification
     commands without running tests or network checks.

5. Packaging decision
   - Done: `docs/v1.0-packaging-decision.md` defers PyInstaller/Nuitka until
     there is a clear executable distribution need.

6. v1.0 closeout
   - Done: `docs/v1.0-acceptance.md` records freeze status, manual smoke, and
     post-v1.0 deferrals.

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

Completed slice: v0.8 failure summary.

Completed slice: v0.8 Workbench provider notice.

Completed slice: v0.8 patch review helper.

Completed slice: v0.8 closeout.

Reason: the Workbench can now suggest verification commands, explain failed
observations, say plainly whether it is using FakeLLM or DeepSeek, and present
a read-only patch review checklist.

Completed slice: v0.9 run risk filters.

Completed slice: v0.9 run replay.

Completed slice: v0.9 log filters.

Completed slice: v0.9 workspace risk hints.

Completed slice: v0.9 memory review UI.

Completed slice: v0.9 stronger failure recovery.

Completed slice: v0.9 closeout.

Reason: run list filtering surfaces risky or failed runs quickly, Run Replay
shows the stored timeline without rerunning anything, and Log Filters tame noisy
trace detail. Workspace Risk now summarizes uncommitted files, snapshots, and
failed recent runs. Memory Review makes pending candidates and active entries
visible without browser-side writes. Failure Recovery now gives a read-only path
for failed runs by pointing to Trace, Failure Summary, rollback availability,
and terminal verification. v0.9 closeout freezes this audit/resilience layer.

v1.0 release prep is complete.

Completed slice: v1.0 one-command startup alias.

Completed slice: v1.0 settings readiness.

Completed slice: v1.0 settings page decision.

Completed slice: v1.0 release readiness doctor.

Completed slice: v1.0 packaging decision.

Completed slice: v1.0 closeout.

Reason: v1.0 should first reduce startup friction without changing the stable
Workbench internals. `agent start` gives the product a clear launch command
while keeping `agent ui` intact for compatibility. Settings Readiness makes the
current provider/model/API-key/config state visible before adding any browser
write path. The settings page decision keeps those settings read-only for v1.0
instead of adding a fragile browser-side config writer. Release readiness
doctor gives a concise terminal check before packaging work. Packaging is
deferred because `agent start` covers local startup without build artifacts.
v1.0 closeout freezes the local visual agent release prep.

Completed slice: post-v1.0 polish backlog.

Completed slice: post-v1.0 first polish item.

Completed slice: post-v1.0 manual smoke checklist.

Completed slice: post-v1.0 accessibility pass.

Completed slice: post-v1.0 closeout.

Completed slice: post-v1.0 local secret flow.

Completed slice: final route completion.

Completed slice: v2.0 Tokenicode Workbench UI refresh.

Reason: after v1.0, the cheapest way to keep momentum is to order polish work
instead of adding speculative UI. The backlog separates immediate copy/manual
smoke/accessibility work from later browser settings writes, packaged executable,
and desktop-shell work. The first polish pass tightens Workbench copy and empty
states without changing behavior. The manual smoke checklist fixes the real
DeepSeek and browser-chat validation path without adding automation debt. The
accessibility pass adds basic labels to the existing static controls. The
local secret flow lets terminal and Workbench entries read `.agent/secrets.env`
without committing API keys. The closeout freezes speculative polish until a
user-directed feature needs it. Final route completion marks the required local
visual agent roadmap as 100%; packaging, a desktop shell, and browser settings
writes were optional trigger-based work rather than unfinished v1.0 release gates.
Frontend vNext Phase 2 has since added bounded non-secret browser config writes;
secrets and approval bypasses remain excluded.
The v2.0 Tokenicode refresh upgrades the existing static Workbench into a
denser coding-IDE style surface with streaming browser chat, tabs, resizable
columns, theme switching, and compact resource inspection while keeping the
stdlib server and local safety model intact.

Next slice: optional trigger-based work only if explicitly needed.

Completed slice: Project vNext Phase 2 managed MCP and Skills lifecycle, then
provider capability declaration.

Completed slice: Project vNext Phase 2 extension management closeout (hook
warnings and `hooks list`, `mcp show`, doctor extension summaries, and the
shared `config set/unset` write path).

Completed slice: Frontend vNext Phase 1 App Shell and Chat vertical slice.

Completed slice: Frontend vNext Phase 2 core functional parity, including Files,
Runs, System, bounded non-secret config writes, visual baselines, and visible-browser
acceptance.

Frontend vNext 默认入口切换就绪。

The completed Readiness slice is designed in
[`2026-07-25-frontend-vnext-default-entry-cutover-readiness-design.md`](superpowers/specs/2026-07-25-frontend-vnext-default-entry-cutover-readiness-design.md)
and implemented by
[`2026-07-25-frontend-vnext-default-entry-readiness.md`](superpowers/plans/2026-07-25-frontend-vnext-default-entry-readiness.md).
The candidate Git tree and Python wheel contain the React runtime bundle.

Frontend vNext 默认入口已切换。

The Cutover is designed in
[`2026-07-25-frontend-vnext-default-entry-cutover-design.md`](superpowers/specs/2026-07-25-frontend-vnext-default-entry-cutover-design.md)
and implemented by
[`2026-07-25-frontend-vnext-default-entry-cutover.md`](superpowers/plans/2026-07-25-frontend-vnext-default-entry-cutover.md).
Root `/` now serves React and `/preview/` remains compatible. Phase 3I subsequently
passed separate stability evidence and review, then removed `/legacy/`, the old shell
and its synchronous chat compatibility route.
The final cross-Interface defect pass remains the required next track. Marketplace,
registry, remote sources, distribution, and ecosystem UI remain demand-triggered Phase 4–5 items.

Completed slices: Phase 3A recoverable task lifecycle, 3B auditable Memory,
3C auditable Automation, 3D stable Eval, 3E Editor/Search, 3F Git/Diff, 3G Terminal,
3H Command/Layout, and 3I Legacy retirement. The next required step is the final
cross-Interface defect pass; this does not yet declare Project vNext core complete.

## Guardrails

- Keep secrets in environment variables or `.agent/secrets.env`, not repo files.
- Keep `docs/main.pdf` as untracked user reference material unless explicitly
  requested otherwise.
- Keep the stdlib Python server and tracked React runtime; do not require Node.js at product runtime or restore a second frontend.
- Do not weaken sandbox, approval, redaction, snapshot, or durable log behavior
  for visual convenience.
