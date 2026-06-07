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
