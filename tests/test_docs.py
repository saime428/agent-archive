from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
V03_TARGETED_TEST_COMMAND = (
    "python -m pytest tests/core/test_actions_parse.py tests/core/test_actions_observations.py "
    "tests/test_documents.py tests/core/test_loop_core.py tests/core/test_loop_modes.py "
    "tests/test_cli.py tests/test_docs.py -q"
)
V05_TARGETED_TEST_COMMAND = "python -m pytest tests/test_chat.py tests/test_cli.py tests/test_deepseek.py tests/test_docs.py -q"
WORKBENCH_TARGETED_TEST_COMMAND = "python -m pytest tests/test_ui.py tests/test_docs.py tests/test_cli.py -q"


def test_package_version_matches_v21_route() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    init_text = (ROOT / "src" / "agent" / "__init__.py").read_text(encoding="utf-8")

    assert pyproject["project"]["version"] == "2.1.0"
    assert '__version__ = "2.1.0"' in init_text


def test_document_reader_extra_declares_optional_parsers_and_xml_hardening() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    documents = pyproject["project"]["optional-dependencies"]["documents"]

    assert any(item.startswith("python-docx") for item in documents)
    assert any(item.startswith("openpyxl") for item in documents)
    assert any(item.startswith("python-pptx") for item in documents)
    assert any(item.startswith("defusedxml") for item in documents)


def test_changelog_records_v21_security_hardening() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "## 2.1.0" in changelog
    assert "安全硬化" in changelog


def test_duplicate_interview_docx_removed() -> None:
    assert not (ROOT / "docs" / "agent-interview-summary.docx").exists()


def test_roadmap_progress_no_longer_has_stale_later_roadmap_table() -> None:
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "## Later Roadmap" not in roadmap


def test_project_context_documents_error_recovery() -> None:
    context = (ROOT / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")

    assert "max_consecutive_errors" in context
    assert "direct helpers have been removed" in context


def test_readme_quickstart_documents_core_cli_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "agent run" in readme
    assert "agent runs list" in readme
    assert "agent runs show" in readme
    assert "agent config show" in readme
    assert "agent config doctor" in readme
    assert "--dry-run" in readme
    assert "snapshot" in readme.lower()


def test_readme_documents_command_allowlist_security_boundaries() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'allowed_commands = ["python", "pip show", "npm test"]' in readme
    assert 'allowed_commands = ["git commit"]' in readme
    assert "intentionally bypasses the default read-only Git restriction" in readme
    assert "The executable token is case-insensitive" in readme
    assert "later tokens are case-sensitive" in readme
    assert "hard-denied shell wrappers, network commands, or dangerous commands" in readme
    assert "still requires approval" in readme
    assert "Approved commands run as local processes with the agent's OS permissions." in readme
    assert "do not fully contain file, network, or subprocess access" in readme
    assert "`allowed_commands` is capability authorization" in readme
    assert "not an OS or container sandbox" in readme
    assert "`pytest` and `python -m pytest` execute project code" in readme
    assert "Built-in file and document tools enforce the configured path policy" in readme
    assert "workspace-only by default, with explicit read-only computer access when enabled" in readme


def test_readme_documents_auto_mode_for_coding_tasks() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'mode = "auto"' in readme
    assert "default `guided` mode allows three actions" in readme
    assert "without changing approval or sandbox rules" in readme


def test_next_feature_handoff_marks_command_allowlist_complete() -> None:
    handoff = (ROOT / "docs" / "next-feature-candidates.md").read_text(encoding="utf-8")

    assert "命令白名单扩展（已完成）" in handoff


def test_v01_acceptance_checklist_records_statuses_and_deferrals() -> None:
    checklist = (ROOT / "docs" / "v0.1-acceptance.md").read_text(encoding="utf-8")

    assert "v0.1 Acceptance Checklist" in checklist
    assert "Implemented" in checklist
    assert "Tested" in checklist
    assert "Deferred to v0.2" in checklist
    assert "Deferred to v0.3" in checklist
    assert "DeepSeek" in checklist
    assert "Documents" in checklist
    assert "v0.1 freeze status" in checklist


def test_v02_acceptance_checklist_records_provider_skills_memory_and_hooks() -> None:
    checklist = (ROOT / "docs" / "v0.2-acceptance.md").read_text(encoding="utf-8")

    assert "v0.2 Acceptance Checklist" in checklist
    assert "DeepSeek" in checklist
    assert "Skills" in checklist
    assert "Memory" in checklist
    assert "Hooks" in checklist
    assert "Deferred to v0.3" in checklist


def test_readme_documents_v02_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "agent skills list" in readme
    assert "agent memory review" in readme
    assert "--provider deepseek" in readme
    assert "DEEPSEEK_API_KEY" in readme


def test_v03_acceptance_checklist_records_document_slice_and_deferrals() -> None:
    checklist = (ROOT / "docs" / "v0.3-acceptance.md").read_text(encoding="utf-8")

    assert "v0.3 Acceptance Checklist" in checklist
    assert "read_pdf" in checklist
    assert "read_docx" in checklist
    assert "read_xlsx" in checklist
    assert "read_pptx" in checklist
    assert "document dependency diagnostics" in checklist
    assert "v0.3 freeze status" in checklist
    assert "Core Document MVP is frozen" in checklist
    assert "write_markdown_report" in checklist
    assert "write_docx_report" in checklist
    assert "Real binary Office fixtures" in checklist
    assert "Complex report orchestration" in checklist
    assert "Implemented / Tested" in checklist
    assert "Deferred" in checklist
    assert "prompt-injection" in checklist


def test_readme_documents_v03_document_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "read_pdf" in readme
    assert "read_docx" in readme
    assert "read_xlsx" in readme
    assert "read_pptx" in readme
    assert "write_markdown_report" in readme
    assert "document dependency" in readme
    assert "python -m agent.cli doctor" in readme
    assert V03_TARGETED_TEST_COMMAND in readme
    assert "Document read tools are low-risk read-only actions" in readme
    assert "write_markdown_report is confirmation-required" in readme
    assert "v0.3 manual smoke" in readme
    assert "UNTRUSTED DOCUMENT SOURCE MATERIAL" in readme


def test_readme_documents_v04_provider_smoke() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "agent provider smoke deepseek --model deepseek-v4-flash" in readme
    assert "python -m agent.cli runs show <run-id>" in readme
    assert "pytest does not require a real DeepSeek API key" in readme
    assert "completed: true" in readme
    assert "terminal_reason: done" in readme
    assert "completed: false" in readme
    assert "failure_explanation" in readme


def test_v04_acceptance_checklist_records_provider_smoke() -> None:
    checklist = (ROOT / "docs" / "v0.4-acceptance.md").read_text(encoding="utf-8")

    assert "v0.4 Acceptance Checklist" in checklist
    assert "provider smoke" in checklist
    assert "DeepSeek" in checklist
    assert "Implemented / Tested" in checklist
    assert "default provider remains `fake`" in checklist
    assert "automated tests do not require a real API key" in checklist
    assert "observation feedback" in checklist
    assert "completed" in checklist
    assert "terminal_reason" in checklist
    assert "CLI failure summary" in checklist
    assert "complex planner" in checklist


def test_readme_documents_v05_chat_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "agent chat --cwd F:\\agent" in readme
    assert "agent chat --resume <chat-id>" in readme
    assert "approval required" in readme
    assert "@README.md" in readme
    assert "status-level live output" in readme
    assert "raw model response preview" in readme
    assert "provider token streaming" in readme
    assert "agent chat --cwd F:\\agent --provider deepseek --model deepseek-v4-flash" in readme
    assert "/help" in readme
    assert "/status" in readme
    assert "/transcript" in readme


def test_v05_acceptance_checklist_records_chat_slice() -> None:
    checklist = (ROOT / "docs" / "v0.5-acceptance.md").read_text(encoding="utf-8")

    assert "v0.5 Acceptance Checklist" in checklist
    assert "v0.5 freeze status" in checklist
    assert "Interactive Terminal Agent MVP is frozen" in checklist
    assert "agent chat" in checklist
    assert "ConversationState" in checklist
    assert "interactive approval" in checklist
    assert "session persistence" in checklist
    assert "@file" in checklist
    assert "status-level live output" in checklist
    assert "| provider token streaming | Implemented / Tested" in checklist
    assert "slash commands" in checklist
    assert "transcript" in checklist
    assert "manual smoke" in checklist
    assert "live chat success criteria" in checklist
    assert "Deferred" in checklist


def test_readme_documents_v05_manual_smoke_and_success_criteria() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "v0.5 manual smoke" in readme
    assert "python -m agent.cli chat --cwd F:\\agent" in readme
    assert "python -m agent.cli chat --cwd F:\\agent --provider deepseek --model deepseek-v4-flash" in readme
    assert "python -m agent.cli runs show <run-id>" in readme
    assert V05_TARGETED_TEST_COMMAND in readme
    assert "live chat success criteria" in readme
    assert "raw model response preview" in readme
    assert "chat_id" in readme
    assert "terminal_reason: done" in readme
    assert "APPROVAL_DENIED" in readme


def test_readme_documents_v06_workbench_smoke() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "v0.6 Visual Workbench" in readme
    assert "python -m agent.cli ui --cwd F:\\agent" in readme
    assert "http://127.0.0.1:8000" in readme
    assert "browser chat turn" in readme
    assert "custom approval panel" in readme
    assert "Files panel" in readme
    assert "Snapshots panel" in readme
    assert "Diff Viewer" in readme
    assert "/api/diff" in readme
    assert "Restore button" in readme
    assert "file editor" in readme
    assert "Save button" in readme
    assert "/api/file/save" in readme
    assert "Activity panel" in readme
    assert "Auto-refresh" in readme
    assert "Status Bar" in readme
    assert "Refresh button" in readme
    assert "active-provider API-key status" in readme
    assert "Task Review panel" in readme
    assert "Runs Dashboard" in readme
    assert "workbench success criteria" in readme
    assert "Status Bar shows workspace, provider, model, session, active-provider API-key status, and last refresh" in readme
    assert "Refresh does not overwrite an open file editor or pending approval" in readme
    assert "Snapshots panel shows restore hints" in readme


def test_v06_acceptance_checklist_records_workbench_slice() -> None:
    checklist = (ROOT / "docs" / "v0.6-acceptance.md").read_text(encoding="utf-8")

    assert "v0.6 Acceptance Checklist" in checklist
    assert "v0.6 freeze status" in checklist
    assert "Visual Workbench MVP is frozen" in checklist
    assert "Visual Workbench" in checklist
    assert "agent ui" in checklist
    assert "browser chat turn" in checklist
    assert "custom approval panel" in checklist
    assert "Files panel" in checklist
    assert "Snapshots panel" in checklist
    assert "Diff Viewer" in checklist
    assert "/api/diff" in checklist
    assert "Restore button" in checklist
    assert "file editor" in checklist
    assert "/api/file/save" in checklist
    assert "Activity panel" in checklist
    assert "Auto-refresh and Status Bar" in checklist
    assert "DeepSeek key presence" in checklist
    assert "workbench success criteria" in checklist
    assert "Refresh does not overwrite open editors or approvals" in checklist
    assert "health/config/tools/runs" in checklist
    assert "Implemented / Tested" in checklist
    assert "Deferred" in checklist


def test_roadmap_progress_records_overall_plan() -> None:
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "Product Goal" in roadmap
    assert "Current Progress Estimate" in roadmap
    assert "| Overall final goal | 100%" in roadmap
    assert "v0.6 Browser Live Events" in roadmap
    assert "Activity panel" in roadmap
    assert "v0.6 Auto-refresh and Status Bar" in roadmap
    assert "Completed slice: v0.6 closeout" in roadmap
    assert "Completed slice: v0.7 Product shell decision" in roadmap
    assert "Completed slice: v0.7 Workbench task review panel" in roadmap
    assert "Completed slice: v0.7 closeout" in roadmap
    assert "Completed slice: v0.8 Workflow Hints panel" in roadmap
    assert "Completed slice: v0.8 failure summary" in roadmap
    assert "Completed slice: v0.8 patch review helper" in roadmap
    assert "Completed slice: v0.8 closeout" in roadmap
    assert "Completed slice: v0.9 run risk filters" in roadmap
    assert "Completed slice: v0.9 run replay" in roadmap
    assert "Completed slice: v0.9 log filters" in roadmap
    assert "Completed slice: v0.9 workspace risk hints" in roadmap
    assert "Completed slice: v0.9 memory review UI" in roadmap
    assert "Completed slice: v0.9 stronger failure recovery" in roadmap
    assert "Completed slice: v0.9 closeout" in roadmap
    assert "v1.0 release prep is complete" in roadmap
    assert "Completed slice: v1.0 settings readiness" in roadmap
    assert "Completed slice: v1.0 settings page decision" in roadmap
    assert "Completed slice: v1.0 release readiness doctor" in roadmap
    assert "Completed slice: v1.0 packaging decision" in roadmap
    assert "Completed slice: v1.0 closeout" in roadmap
    assert "Completed slice: post-v1.0 polish backlog" in roadmap
    assert "Completed slice: post-v1.0 first polish item" in roadmap
    assert "Completed slice: post-v1.0 manual smoke checklist" in roadmap
    assert "Completed slice: post-v1.0 accessibility pass" in roadmap
    assert "Completed slice: post-v1.0 closeout" in roadmap
    assert "Completed slice: post-v1.0 local secret flow" in roadmap
    assert "Completed slice: final route completion" in roadmap
    assert "Next slice: optional trigger-based work only if explicitly needed" in roadmap
    assert "Core agent engine" in roadmap
    assert "Visual Workbench product" in roadmap


def test_stdio_mcp_docs_record_config_security_scope_and_acceptance() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    direction = (ROOT / "docs" / "project-vnext-direction.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")
    spec = (
        ROOT / "docs" / "superpowers" / "specs" / "2026-07-17-stdio-mcp-dynamic-tools-design.md"
    ).read_text(encoding="utf-8")
    plan = (
        ROOT / "docs" / "superpowers" / "plans" / "2026-07-17-stdio-mcp-dynamic-tools.md"
    ).read_text(encoding="utf-8")

    assert "~/.agent/mcp.toml" in readme
    assert 'pass_env = ["EXAMPLE_API_KEY"]' in readme
    assert 'cwd = "workspace"' in readme
    assert "{workspace}" in readme
    assert "confirmation-required" in readme
    assert "they never send `tools/call`" in readme
    assert "OS permissions" in readme
    assert "agent tools list" in readme and "built-in-only inventory" in readme
    assert "Marketplace, management UI, automatic reconnect" in readme
    assert "本地 stdio MCP Tool" in changelog
    assert "MCP 后端切片已完成" in direction
    assert "尚无 MCP runtime" not in direction
    assert "Project vNext Extension Track" in roadmap
    assert "Project vNext core (Phase 0–3) | In progress" in roadmap
    assert "Phase 4–5 demand-triggered pool | Not started by design" in roadmap
    assert "状态：已实施（自动门禁与真实本地验收通过）" in spec
    assert "实施与验收证据（2026-07-18）" in spec
    assert "不代表 Marketplace、管理 UI、远程 transport 或完整生态已经完成" in spec
    assert "状态：** 已完成（2026-07-18）" in plan
    assert "- [ ] Step" not in plan


def test_v07_shell_decision_keeps_static_workbench_until_needed() -> None:
    decision = (ROOT / "docs" / "v0.7-shell-decision.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "v0.7 Product Shell Decision" in decision
    assert "Decision: keep the stdlib static Workbench shell for now" in decision
    assert "Do not add Vue, Vite, Electron, or Tauri in this slice" in decision
    assert "Migration triggers" in decision
    assert "state management starts duplicating across panels" in decision
    assert "desktop-only integration becomes required" in decision
    assert "Task review panel is now implemented" in decision
    assert "v0.7 Product Shell Decision" in readme
    assert "Task Review panel" in readme
    assert "docs/v0.7-shell-decision.md" in readme
    assert "Completed slice: v0.7 Product shell decision" in roadmap
    assert "Completed slice: v0.7 Workbench task review panel" in roadmap


def test_v07_acceptance_closeout_records_workbench_freeze() -> None:
    checklist = (ROOT / "docs" / "v0.7-acceptance.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "v0.7 Acceptance Checklist" in checklist
    assert "v0.7 freeze status" in checklist
    assert "Visual Workbench product shell is frozen" in checklist
    assert "Task Review panel" in checklist
    assert "static Workbench shell" in checklist
    assert "manual smoke" in checklist
    assert "Implemented / Tested" in checklist
    assert "Deferred" in checklist
    assert "Vue/Vite migration" in checklist
    assert "Electron/Tauri packaging" in checklist
    assert "v0.8 stronger coding workflow" in checklist
    assert "v0.7 manual smoke" in readme
    assert "docs/v0.7-acceptance.md" in readme
    assert "Completed slice: v0.7 closeout" in roadmap
    assert "Completed slice: v0.8 Workflow Hints panel" in roadmap
    assert "Completed slice: v0.8 failure summary" in roadmap
    assert "Completed slice: v0.8 patch review helper" in roadmap
    assert "Completed slice: v0.8 closeout" in roadmap
    assert "Completed slice: v0.9 run risk filters" in roadmap
    assert "Completed slice: v0.9 run replay" in roadmap
    assert "Completed slice: v0.9 log filters" in roadmap
    assert "Completed slice: v0.9 workspace risk hints" in roadmap
    assert "Completed slice: v0.9 memory review UI" in roadmap
    assert "Completed slice: v0.9 stronger failure recovery" in roadmap
    assert "Completed slice: v0.9 closeout" in roadmap
    assert "v1.0 release prep is complete" in roadmap
    assert "Completed slice: v1.0 settings readiness" in roadmap
    assert "Completed slice: v1.0 settings page decision" in roadmap
    assert "Completed slice: v1.0 release readiness doctor" in roadmap
    assert "Completed slice: v1.0 packaging decision" in roadmap
    assert "Completed slice: v1.0 closeout" in roadmap
    assert "Completed slice: post-v1.0 polish backlog" in roadmap
    assert "Completed slice: post-v1.0 first polish item" in roadmap
    assert "Completed slice: post-v1.0 manual smoke checklist" in roadmap
    assert "Completed slice: post-v1.0 accessibility pass" in roadmap
    assert "Completed slice: post-v1.0 closeout" in roadmap
    assert "Completed slice: post-v1.0 local secret flow" in roadmap
    assert "Next slice: optional trigger-based work only if explicitly needed" in roadmap


def test_v08_acceptance_records_workflow_hints_slice() -> None:
    checklist = (ROOT / "docs" / "v0.8-acceptance.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "v0.8 Acceptance Checklist" in checklist
    assert "Workflow Hints panel" in checklist
    assert "verification_commands" in checklist
    assert "Failure Summary panel" in checklist
    assert "latest_failure" in checklist
    assert "Provider Notice" in checklist
    assert "provider_notice" in checklist
    assert "Patch Review Helper" in checklist
    assert "v0.8 freeze status" in checklist
    assert "v0.8 read-only coding workflow is frozen" in checklist
    assert "failed observations" in checklist
    assert "does not retry tools" in checklist
    assert "read-only" in checklist
    assert "does not execute commands" in checklist
    assert "git checkpoint UI" in checklist
    assert "Implemented / Tested" in checklist
    assert "Deferred" in checklist
    assert "v0.8 Stronger Coding Workflow" in readme
    assert "Workflow Hints panel" in readme
    assert "Failure Summary panel" in readme
    assert "Provider Notice" in readme
    assert "Patch Review Helper" in readme
    assert "read-only coding workflow" in readme
    assert "v0.8 closeout" in readme
    assert "v0.8 manual smoke" in readme
    assert "docs/v0.8-acceptance.md" in readme
    assert "Completed slice: v0.8 Workflow Hints panel" in roadmap
    assert "Completed slice: v0.8 failure summary" in roadmap
    assert "Completed slice: v0.8 Workbench provider notice" in roadmap
    assert "Completed slice: v0.8 patch review helper" in roadmap
    assert "Completed slice: v0.8 closeout" in roadmap
    assert "Completed slice: v0.9 run risk filters" in roadmap
    assert "Completed slice: v0.9 run replay" in roadmap
    assert "Completed slice: v0.9 log filters" in roadmap
    assert "Completed slice: v0.9 workspace risk hints" in roadmap
    assert "Completed slice: v0.9 memory review UI" in roadmap
    assert "Completed slice: v0.9 stronger failure recovery" in roadmap
    assert "Completed slice: v0.9 closeout" in roadmap
    assert "v1.0 release prep is complete" in roadmap
    assert "Completed slice: v1.0 settings readiness" in roadmap
    assert "Completed slice: v1.0 settings page decision" in roadmap
    assert "Completed slice: v1.0 release readiness doctor" in roadmap
    assert "Completed slice: v1.0 packaging decision" in roadmap
    assert "Completed slice: v1.0 closeout" in roadmap
    assert "Completed slice: post-v1.0 polish backlog" in roadmap
    assert "Completed slice: post-v1.0 first polish item" in roadmap
    assert "Completed slice: post-v1.0 manual smoke checklist" in roadmap
    assert "Completed slice: post-v1.0 accessibility pass" in roadmap
    assert "Completed slice: post-v1.0 closeout" in roadmap
    assert "Next slice: optional trigger-based work only if explicitly needed" in roadmap


def test_v09_acceptance_records_run_risk_filters_slice() -> None:
    checklist = (ROOT / "docs" / "v0.9-acceptance.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "v0.9 Acceptance Checklist" in checklist
    assert "Run Risk Filter" in checklist
    assert "risk_level" in checklist
    assert "status" in checklist
    assert "Run Replay" in checklist
    assert "stored tool calls" in checklist
    assert "does not execute tools" in checklist
    assert "Log Filters" in checklist
    assert "Trace and Run Replay" in checklist
    assert "Workspace Risk" in checklist
    assert "workspace_risk" in checklist
    assert "Memory Review" in checklist
    assert "memory_review" in checklist
    assert "Failure Recovery" in checklist
    assert "rollback_available" in checklist
    assert "v0.9 freeze status" in checklist
    assert "Audit and Resilience Workbench is frozen" in checklist
    assert "v0.9 manual smoke" in checklist
    assert "read-only" in checklist
    assert "v0.9 Audit and Resilience" in readme
    assert "Run Risk Filter" in readme
    assert "Run Replay" in readme
    assert "Log Filters" in readme
    assert "Workspace Risk" in readme
    assert "Memory Review" in readme
    assert "Failure Recovery" in readme
    assert "v0.9 closeout" in readme
    assert "docs/v0.9-acceptance.md" in readme
    assert WORKBENCH_TARGETED_TEST_COMMAND in readme
    assert "visual agent progress" in readme
    assert "Completed slice: v0.9 run risk filters" in roadmap
    assert "Completed slice: v0.9 run replay" in roadmap
    assert "Completed slice: v0.9 log filters" in roadmap
    assert "Completed slice: v0.9 workspace risk hints" in roadmap
    assert "Completed slice: v0.9 memory review UI" in roadmap
    assert "Completed slice: v0.9 stronger failure recovery" in roadmap
    assert "Completed slice: v0.9 closeout" in roadmap
    assert "v1.0 release prep is complete" in roadmap
    assert "Completed slice: v1.0 settings readiness" in roadmap
    assert "Completed slice: v1.0 settings page decision" in roadmap
    assert "Completed slice: v1.0 release readiness doctor" in roadmap
    assert "Completed slice: v1.0 packaging decision" in roadmap
    assert "Completed slice: v1.0 closeout" in roadmap
    assert "Completed slice: post-v1.0 polish backlog" in roadmap
    assert "Completed slice: post-v1.0 first polish item" in roadmap
    assert "Completed slice: post-v1.0 manual smoke checklist" in roadmap
    assert "Completed slice: post-v1.0 accessibility pass" in roadmap
    assert "Completed slice: post-v1.0 closeout" in roadmap
    assert "Next slice: optional trigger-based work only if explicitly needed" in roadmap


def test_v10_release_prep_documents_start_command() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "v1.0 Release Prep" in readme
    assert "agent start --cwd F:\\agent" in readme
    assert "python -m agent.cli start --cwd F:\\agent" in readme
    assert "Settings Readiness" in readme
    assert "Completed slice: v1.0 one-command startup alias" in roadmap
    assert "Completed slice: v1.0 settings readiness" in roadmap
    assert "Completed slice: v1.0 settings page decision" in roadmap
    assert "Completed slice: v1.0 release readiness doctor" in roadmap
    assert "Completed slice: v1.0 packaging decision" in roadmap
    assert "Completed slice: v1.0 closeout" in roadmap
    assert "Completed slice: post-v1.0 polish backlog" in roadmap
    assert "Completed slice: post-v1.0 first polish item" in roadmap
    assert "Completed slice: post-v1.0 manual smoke checklist" in roadmap
    assert "Completed slice: post-v1.0 accessibility pass" in roadmap
    assert "Completed slice: post-v1.0 closeout" in roadmap
    assert "Next slice: optional trigger-based work only if explicitly needed" in roadmap


def test_v10_settings_page_decision_keeps_settings_read_only() -> None:
    decision = (ROOT / "docs" / "v1.0-settings-page-decision.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "v1.0 Settings Page Decision" in decision
    assert "Decision: keep browser settings read-only for v1.0" in decision
    assert "Do not write API keys from the browser" in decision
    assert "Settings Readiness" in decision
    assert "agent config show" in decision
    assert "v1.0 Settings Page Decision" in readme
    assert "docs/v1.0-settings-page-decision.md" in readme
    assert "Completed slice: v1.0 settings page decision" in roadmap
    assert "Completed slice: v1.0 release readiness doctor" in roadmap
    assert "Completed slice: v1.0 packaging decision" in roadmap
    assert "Completed slice: v1.0 closeout" in roadmap
    assert "Completed slice: post-v1.0 polish backlog" in roadmap
    assert "Completed slice: post-v1.0 first polish item" in roadmap
    assert "Completed slice: post-v1.0 manual smoke checklist" in roadmap
    assert "Completed slice: post-v1.0 accessibility pass" in roadmap
    assert "Completed slice: post-v1.0 closeout" in roadmap
    assert "Next slice: optional trigger-based work only if explicitly needed" in roadmap


def test_v10_release_readiness_doctor_is_documented() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "agent release doctor --cwd F:\\agent" in readme
    assert "release readiness" in readme
    assert "startup command: agent start" in readme
    assert "Completed slice: v1.0 release readiness doctor" in roadmap
    assert "Completed slice: v1.0 packaging decision" in roadmap
    assert "Completed slice: v1.0 closeout" in roadmap
    assert "Completed slice: post-v1.0 polish backlog" in roadmap
    assert "Completed slice: post-v1.0 first polish item" in roadmap
    assert "Completed slice: post-v1.0 manual smoke checklist" in roadmap
    assert "Completed slice: post-v1.0 accessibility pass" in roadmap
    assert "Completed slice: post-v1.0 closeout" in roadmap
    assert "Next slice: optional trigger-based work only if explicitly needed" in roadmap


def test_v10_packaging_decision_defers_binary_packaging() -> None:
    decision = (ROOT / "docs" / "v1.0-packaging-decision.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "v1.0 Packaging Decision" in decision
    assert "Decision: defer binary packaging for v1.0" in decision
    assert "PyInstaller" in decision
    assert "agent start" in decision
    assert "v1.0 Packaging Decision" in readme
    assert "docs/v1.0-packaging-decision.md" in readme
    assert "Completed slice: v1.0 packaging decision" in roadmap
    assert "Completed slice: v1.0 closeout" in roadmap
    assert "Completed slice: post-v1.0 polish backlog" in roadmap
    assert "Completed slice: post-v1.0 first polish item" in roadmap
    assert "Completed slice: post-v1.0 manual smoke checklist" in roadmap
    assert "Completed slice: post-v1.0 accessibility pass" in roadmap
    assert "Completed slice: post-v1.0 closeout" in roadmap
    assert "Next slice: optional trigger-based work only if explicitly needed" in roadmap


def test_v10_acceptance_closeout_records_release_freeze() -> None:
    checklist = (ROOT / "docs" / "v1.0-acceptance.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "v1.0 Acceptance Checklist" in checklist
    assert "v1.0 freeze status" in checklist
    assert "Local visual agent release prep is frozen" in checklist
    assert "agent start" in checklist
    assert "Settings Readiness" in checklist
    assert "release readiness doctor" in checklist
    assert "packaging deferred" in checklist
    assert "Implemented / Tested" in checklist
    assert "Deferred" in checklist
    assert "v1.0 closeout" in readme
    assert "docs/v1.0-acceptance.md" in readme
    assert "Completed slice: v1.0 closeout" in roadmap
    assert "Completed slice: post-v1.0 polish backlog" in roadmap
    assert "Completed slice: post-v1.0 first polish item" in roadmap
    assert "Completed slice: post-v1.0 manual smoke checklist" in roadmap
    assert "Completed slice: post-v1.0 accessibility pass" in roadmap
    assert "Completed slice: post-v1.0 closeout" in roadmap
    assert "Next slice: optional trigger-based work only if explicitly needed" in roadmap


def test_post_v10_polish_backlog_records_priorities() -> None:
    backlog = (ROOT / "docs" / "post-v1.0-polish-backlog.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "post-v1.0 Polish Backlog" in backlog
    assert "Do next" in backlog
    assert "Do later" in backlog
    assert "Do not do yet" in backlog
    assert "Tighten Workbench copy and empty states. Done." in backlog
    assert "Review accessibility basics for buttons, labels, and panel headings. Done." in backlog
    assert "safe local secret flow" in backlog
    assert ".agent/secrets.env" in backlog
    assert "packaged executable" in backlog
    assert "post-v1.0 Polish Backlog" in readme
    assert "docs/post-v1.0-polish-backlog.md" in readme
    assert ".agent/secrets.env" in readme
    assert "Do not put API keys in `.agent/config.toml`" in readme
    assert "Completed slice: post-v1.0 polish backlog" in roadmap
    assert "Completed slice: post-v1.0 first polish item" in roadmap
    assert "Completed slice: post-v1.0 manual smoke checklist" in roadmap
    assert "Completed slice: post-v1.0 accessibility pass" in roadmap
    assert "Completed slice: post-v1.0 closeout" in roadmap
    assert "Completed slice: post-v1.0 local secret flow" in roadmap
    assert "Next slice: optional trigger-based work only if explicitly needed" in roadmap


def test_post_v10_manual_smoke_checklist_is_documented() -> None:
    checklist = (ROOT / "docs" / "post-v1.0-manual-smoke.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "post-v1.0 Manual Smoke Checklist" in checklist
    assert "DeepSeek terminal chat" in checklist
    assert "Workbench browser chat" in checklist
    assert "agent release doctor" in checklist
    assert "expected result" in checklist
    assert "post-v1.0 Manual Smoke Checklist" in readme
    assert "docs/post-v1.0-manual-smoke.md" in readme
    assert "Completed slice: post-v1.0 manual smoke checklist" in roadmap
    assert "Completed slice: post-v1.0 accessibility pass" in roadmap
    assert "Completed slice: post-v1.0 closeout" in roadmap
    assert "Next slice: optional trigger-based work only if explicitly needed" in roadmap


def test_post_v10_polish_closeout_records_freeze() -> None:
    closeout = (ROOT / "docs" / "post-v1.0-polish-closeout.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "post-v1.0 Polish Closeout" in closeout
    assert "Polish pass is frozen" in closeout
    assert "copy and empty states" in closeout
    assert "manual smoke checklist" in closeout
    assert "accessibility labels" in closeout
    assert "safe local secret flow" in closeout
    assert ".agent/secrets.env" in closeout
    assert "post-v1.0 Polish Closeout" in readme
    assert "docs/post-v1.0-polish-closeout.md" in readme
    assert "Completed slice: post-v1.0 closeout" in roadmap
    assert "Completed slice: post-v1.0 local secret flow" in roadmap
    assert "Next slice: optional trigger-based work only if explicitly needed" in roadmap


def test_managed_extension_lifecycle_docs_record_commands_scope_and_status() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    direction = (ROOT / "docs" / "project-vnext-direction.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")
    spec = (
        ROOT / "docs" / "superpowers" / "specs" / "2026-07-18-managed-extension-lifecycle-design.md"
    ).read_text(encoding="utf-8")
    plan = (
        ROOT / "docs" / "superpowers" / "plans" / "2026-07-18-managed-extension-lifecycle.md"
    ).read_text(encoding="utf-8")

    for command in (
        "agent mcp list",
        "agent mcp validate",
        "agent mcp set",
        "agent mcp enable",
        "agent mcp disable",
        "agent mcp remove",
        "agent mcp doctor",
        "agent skills validate",
        "agent skills install",
        "agent skills enable",
        "agent skills disable",
        "agent skills update",
        "agent skills package",
        "agent skills remove",
        "agent skills doctor",
    ):
        assert command in readme

    assert "~/.agent/mcp.d/<server-id>.toml" in readme
    assert "~/.agent/mcp-state.json" in readme
    assert "~/.agent/skills/<name>/" in readme
    assert "~/.agent/skills-state.json" in readme
    assert "never start a server process" in readme
    assert "restart the CLI" in readme
    assert ".skill.zip" in readme
    assert "URLs, Git clones, and registry IDs are not supported" in readme
    assert "never executed by" in readme
    assert "no-clobber hard link" in readme
    assert "~/.agent/.extension.lock" in readme
    assert "complete old state or the complete new state" in readme
    assert "fails closed and keeps the" in readme
    assert "there is no Marketplace, registry, URL or Git install" in readme

    assert "可管理的本地扩展生命周期" in changelog
    assert "MCP Server 故障隔离" in changelog

    assert "Phase 2 slice 1: managed MCP and Skills lifecycle | Complete" in roadmap
    assert "Frontend vNext Phase 2: Core functional parity | Complete" in roadmap
    assert "Frontend vNext Default Entry Cutover | Complete" in roadmap
    assert "Project vNext core (Phase 0–3) | In progress" in roadmap
    assert "Phase 4–5 demand-triggered pool | Not started by design" in roadmap
    assert "Completed slice: Project vNext Phase 2 managed MCP and Skills lifecycle, then" in roadmap
    assert "Completed slice: Frontend vNext Phase 1 App Shell and Chat vertical slice" in roadmap
    assert "Completed slice: Frontend vNext Phase 2 core functional parity" in roadmap

    assert "Provider 能力声明（均已完成）" in direction
    assert "2026-07-18-managed-extension-lifecycle-design.md" in direction
    assert "仍缺自动重连、远程来源、registry 与 Workbench 写接口" in direction

    assert "状态：已实施" in spec
    assert "实施与验收证据" in spec
    assert "状态：已执行" in plan
    assert "- [ ] Step" not in plan


def test_frontend_vnext_default_entry_cutover_readiness_spec_records_boundaries() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    verification = (
        ROOT / "docs" / "verification" / "frontend-vnext-default-entry-readiness.md"
    ).read_text(encoding="utf-8")
    spec = (
        ROOT
        / "docs"
        / "superpowers"
        / "specs"
        / "2026-07-25-frontend-vnext-default-entry-cutover-readiness-design.md"
    ).read_text(encoding="utf-8")
    plan = (
        ROOT
        / "docs"
        / "superpowers"
        / "plans"
        / "2026-07-25-frontend-vnext-default-entry-readiness.md"
    ).read_text(encoding="utf-8")

    assert "`src/agent/web/static/preview/**` is a tracked runtime asset" in readme
    assert "The Python runtime never invokes npm" in readme
    assert "npm run build:preview" in readme
    assert "Frontend vNext 默认入口切换就绪。" in verification
    assert "根 `/` 仍返回旧 Workbench" in verification
    assert "Cutover 仍需再次明确授权" in verification
    assert "默认入口已切换。" not in verification
    assert "旧壳已退役。" not in verification

    assert "状态：Readiness 门禁通过；根 `/` 未切换" in spec
    assert "本切片结束时根 `/` **仍返回旧 Workbench**" in spec
    assert "不增加运行时 feature flag" in spec
    assert "Cutover（需再次明确授权）" in spec
    assert "状态：** 已执行，仅完成 Readiness" in plan
    assert "- [ ]" not in plan


def test_frontend_vnext_default_entry_cutover_docs_record_current_state() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")
    project_direction = (ROOT / "docs" / "project-vnext-direction.md").read_text(encoding="utf-8")
    frontend_direction = (ROOT / "docs" / "frontend-vnext-direction.md").read_text(encoding="utf-8")
    spec = (
        ROOT
        / "docs"
        / "superpowers"
        / "specs"
        / "2026-07-25-frontend-vnext-default-entry-cutover-design.md"
    ).read_text(encoding="utf-8")
    plan = (
        ROOT
        / "docs"
        / "superpowers"
        / "plans"
        / "2026-07-25-frontend-vnext-default-entry-cutover.md"
    ).read_text(encoding="utf-8")
    verification_path = (
        ROOT / "docs" / "verification" / "frontend-vnext-default-entry-cutover.md"
    )

    assert verification_path.is_file()
    verification = verification_path.read_text(encoding="utf-8")

    assert "运行时代码只改一行" in spec
    assert "真实提交重建" in plan
    assert "| `/` | React `preview/index.html` |" in readme
    assert "Frontend vNext 默认入口已切换。" in changelog
    assert "Frontend vNext 默认入口已切换。" in roadmap
    assert "Default Entry Cutover（已完成）" in project_direction
    assert "根 `/` 已指向 React Workbench" in frontend_direction
    assert "Frontend vNext 默认入口已切换。" in verification

    for document in (
        readme,
        changelog,
        roadmap,
        project_direction,
        frontend_direction,
        verification,
    ):
        assert "旧壳已退役。" not in document
        assert "Frontend vNext 长期路线完成。" not in document


def test_project_vnext_completion_definition_is_core_phases_zero_to_three() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")
    project_direction = (ROOT / "docs" / "project-vnext-direction.md").read_text(encoding="utf-8")
    frontend_direction = (ROOT / "docs" / "frontend-vnext-direction.md").read_text(encoding="utf-8")

    assert "阶段 0–3 是当前核心目标" in project_direction
    assert "阶段 4–5 是需求触发项" in project_direction
    assert "不阻塞 Project vNext 核心完成" in project_direction
    assert "对话、生成、前端、后端/API、CLI、打包和真实浏览器" in project_direction
    assert "只有六个生态闭环和长期完成标准均有当前证据" not in project_direction

    assert "阶段 3 是核心目标" in frontend_direction
    assert "阶段 4–5 是需求触发项" in frontend_direction
    assert "阶段 3–5 和旧壳退役仍未完成" not in frontend_direction

    assert "Project vNext core (Phase 0–3)" in roadmap
    assert "Phase 4–5 demand-triggered pool" in roadmap
    assert "阶段 0–3 是核心目标，阶段 4–5 改为需求触发项" in changelog


def test_async_chat_session_visibility_docs_record_contract_and_evidence() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    spec = (
        ROOT
        / "docs"
        / "superpowers"
        / "specs"
        / "2026-07-25-async-chat-session-visibility-design.md"
    ).read_text(encoding="utf-8")
    plan = (
        ROOT
        / "docs"
        / "superpowers"
        / "plans"
        / "2026-07-25-async-chat-session-visibility.md"
    ).read_text(encoding="utf-8")

    assert "状态：已实施并验收" in spec
    assert "成功返回时，其 `session_id` 必须已经能被现有 chat detail" in spec
    assert "状态：已执行" in plan
    assert "96 passed" in plan
    assert "5 个全新隔离服务" in plan
    assert "修复异步新会话首次详情读取竞态" in changelog


def test_extension_management_closeout_docs_record_commands_and_status() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    spec = (
        ROOT / "docs" / "superpowers" / "specs" / "2026-07-23-extension-management-closeout-design.md"
    ).read_text(encoding="utf-8")

    for command in ("agent hooks list", "agent mcp show", "agent config set", "agent config unset"):
        assert command in readme
    assert "config set" in changelog
    assert "状态：已实施" in spec


def test_phase3_recoverable_task_lifecycle_docs_lock_scope_and_completion_boundary() -> None:
    direction = (ROOT / "docs" / "project-vnext-phase3-direction-review.md").read_text(encoding="utf-8")
    spec = (
        ROOT
        / "docs"
        / "superpowers"
        / "specs"
        / "2026-07-25-phase3-recoverable-task-lifecycle-design.md"
    ).read_text(encoding="utf-8")
    plan = (
        ROOT
        / "docs"
        / "superpowers"
        / "plans"
        / "2026-07-25-phase3-recoverable-task-lifecycle.md"
    ).read_text(encoding="utf-8")
    verification_path = ROOT / "docs" / "verification" / "phase3-recoverable-task-lifecycle.md"

    assert verification_path.is_file()
    verification = verification_path.read_text(encoding="utf-8")

    assert "3A Lifecycle" in direction
    assert "resume **不会重放旧 message 或任何 Tool**" in spec
    assert "一个 workspace 同时只允许一个 Agent turn" in spec
    assert "1–3600 秒" in spec
    for terminal in ("cancelled", "timed_out", "interrupted"):
        assert terminal in spec
        assert terminal in plan
    assert "3A Lifecycle" in verification
    assert "Project vNext 核心仍未完成" in verification
    assert "Phase 4–5" in verification


def test_phase3_memory_lifecycle_docs_lock_scope_and_completion_boundary() -> None:
    direction = (ROOT / "docs" / "project-vnext-phase3-direction-review.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    spec = (
        ROOT / "docs" / "superpowers" / "specs" / "2026-07-25-phase3-memory-lifecycle-design.md"
    ).read_text(encoding="utf-8")
    plan = (
        ROOT / "docs" / "superpowers" / "plans" / "2026-07-25-phase3-memory-lifecycle.md"
    ).read_text(encoding="utf-8")
    verification_path = ROOT / "docs" / "verification" / "phase3-memory-lifecycle.md"

    assert verification_path.is_file()
    verification = verification_path.read_text(encoding="utf-8")

    assert "3B Memory" in direction
    assert "candidate 状态只有 pending、accepted、rejected" in spec
    assert "current active 叶节点" in spec
    assert "不建数据库" in spec
    assert "并发 accept/reject 只有一个成功" in plan
    for command in ("reject", "revise", "delete", "history"):
        assert f"agent memory {command}" in readme
    assert "状态：3B Memory 已完成" in verification
    assert "3C Automation" in verification
    assert "Project vNext 核心仍未完成" in verification
    assert "Phase 4–5" in verification
