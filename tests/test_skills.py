from __future__ import annotations

from agent.core.skills import SkillError, discover_skills, load_selected_skills


def test_discover_skills_lists_builtin_skill_metadata(tmp_path) -> None:
    catalog = discover_skills(tmp_path)

    assert "code-dev" in catalog
    assert catalog["code-dev"].name == "code-dev"
    assert "apply_patch" in catalog["code-dev"].allowed_tools
    assert "mcp:*" in catalog["code-dev"].allowed_tools
    assert catalog["code-dev"].body is None


def test_discover_skills_lists_project_skill_metadata(tmp_path) -> None:
    skill_path = tmp_path / ".agent" / "skills" / "reviewer" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text(
        "---\nname: reviewer\ndescription: Reviews changes\nallowed_tools:\n  - read_file\n---\nReview carefully.\n",
        encoding="utf-8",
    )

    catalog = discover_skills(tmp_path)

    assert "reviewer" in catalog
    assert catalog["reviewer"].source == "project"
    assert catalog["reviewer"].body is None


def test_load_selected_skills_loads_body_with_budget(tmp_path) -> None:
    loaded = load_selected_skills(tmp_path, ["code-dev"], max_chars=20)

    assert len(loaded) == 1
    assert loaded[0].name == "code-dev"
    assert loaded[0].body.endswith("\n[truncated]")


def test_builtin_code_dev_prefers_the_simplest_standard_library_fix(tmp_path) -> None:
    loaded = load_selected_skills(tmp_path, ["code-dev"], max_chars=2_000)

    assert "simplest correct change" in loaded[0].body
    assert "standard library" in loaded[0].body
    assert "built-in language features" in loaded[0].body
    assert "Do not add an import" in loaded[0].body
    assert "split()/join()" in loaded[0].body
    assert "re.sub" in loaded[0].body


def test_load_selected_skills_rejects_unknown_skill(tmp_path) -> None:
    try:
        load_selected_skills(tmp_path, ["missing"], max_chars=100)
    except SkillError as exc:
        assert "Unknown skill: missing" in str(exc)
    else:
        raise AssertionError("Expected SkillError")
