from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_quickstart_documents_core_cli_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "agent run" in readme
    assert "agent runs list" in readme
    assert "agent runs show" in readme
    assert "agent config show" in readme
    assert "agent config doctor" in readme
    assert "--dry-run" in readme
    assert "snapshot" in readme.lower()


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
    assert "python -m pytest tests/test_actions.py tests/test_documents.py tests/test_loop.py tests/test_cli.py tests/test_docs.py -q" in readme
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
    assert "python -m pytest tests/test_chat.py tests/test_cli.py tests/test_deepseek.py tests/test_docs.py -q" in readme
    assert "live chat success criteria" in readme
    assert "raw model response preview" in readme
    assert "chat_id" in readme
    assert "terminal_reason: done" in readme
    assert "APPROVAL_DENIED" in readme


def test_readme_documents_v06_workbench_smoke() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "v0.6 Visual Workbench" in readme
    assert "python -m agent.cli ui --cwd F:\\agent" in readme
    assert "http://127.0.0.1:8765" in readme
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
    assert "DeepSeek key presence" in readme
    assert "Task Review panel" in readme
    assert "Runs Dashboard" in readme
    assert "workbench success criteria" in readme
    assert "Status Bar shows workspace, provider, model, session, DeepSeek key presence, and last refresh" in readme
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
    assert "Next slice: v1.0 release prep" in roadmap
    assert "Core agent engine" in roadmap
    assert "Visual Workbench product" in roadmap


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
    assert "Next slice: v1.0 release prep" in roadmap


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
    assert "Next slice: v1.0 release prep" in roadmap


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
    assert "python -m pytest tests/test_ui.py tests/test_docs.py tests/test_cli.py -q" in readme
    assert "visual agent progress" in readme
    assert "Completed slice: v0.9 run risk filters" in roadmap
    assert "Completed slice: v0.9 run replay" in roadmap
    assert "Completed slice: v0.9 log filters" in roadmap
    assert "Completed slice: v0.9 workspace risk hints" in roadmap
    assert "Completed slice: v0.9 memory review UI" in roadmap
    assert "Completed slice: v0.9 stronger failure recovery" in roadmap
    assert "Completed slice: v0.9 closeout" in roadmap
    assert "Next slice: v1.0 release prep" in roadmap
