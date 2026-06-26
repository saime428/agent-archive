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
    assert "native browser confirmation" in readme
    assert "Files panel" in readme
    assert "Snapshots panel" in readme
    assert "Diff Viewer" in readme
    assert "/api/diff" in readme
    assert "Restore button" in readme
    assert "Activity panel" in readme
    assert "Runs Dashboard" in readme


def test_v06_acceptance_checklist_records_workbench_slice() -> None:
    checklist = (ROOT / "docs" / "v0.6-acceptance.md").read_text(encoding="utf-8")

    assert "v0.6 Acceptance Checklist" in checklist
    assert "Visual Workbench" in checklist
    assert "agent ui" in checklist
    assert "browser chat turn" in checklist
    assert "native browser confirmation" in checklist
    assert "Files panel" in checklist
    assert "Snapshots panel" in checklist
    assert "Diff Viewer" in checklist
    assert "/api/diff" in checklist
    assert "Restore button" in checklist
    assert "Activity panel" in checklist
    assert "health/config/tools/runs" in checklist
    assert "Implemented / Tested" in checklist
    assert "Deferred" in checklist


def test_roadmap_progress_records_overall_plan() -> None:
    roadmap = (ROOT / "docs" / "roadmap-progress.md").read_text(encoding="utf-8")

    assert "Product Goal" in roadmap
    assert "Current Progress Estimate" in roadmap
    assert "v0.6 Browser Live Events" in roadmap
    assert "Activity panel" in roadmap
    assert "Core agent engine" in roadmap
    assert "Visual Workbench product" in roadmap
