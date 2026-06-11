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
    assert "pytest does not require a real DeepSeek API key" in readme


def test_v04_acceptance_checklist_records_provider_smoke() -> None:
    checklist = (ROOT / "docs" / "v0.4-acceptance.md").read_text(encoding="utf-8")

    assert "v0.4 Acceptance Checklist" in checklist
    assert "provider smoke" in checklist
    assert "DeepSeek" in checklist
    assert "Implemented / Tested" in checklist
    assert "default provider remains `fake`" in checklist
    assert "automated tests do not require a real API key" in checklist
