from __future__ import annotations

from pathlib import Path

import pytest

from agent.core.skills import SkillError, SkillStore, discover_skills, load_selected_skills

_FIXTURE_SKILL = (Path(__file__).parent / "fixtures" / "skills" / "reviewer-v1").resolve()


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


def _store(tmp_path) -> tuple[SkillStore, Path, Path]:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    return SkillStore(workspace, home=home), workspace, home


def _write_candidate(
    root: Path,
    name: str,
    *,
    body: str = "Candidate body.\n",
    frontmatter_name: str | None = None,
) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        "---\n"
        f"name: {frontmatter_name if frontmatter_name is not None else name}\n"
        "description: Candidate skill\n"
        "allowed_tools:\n  - read_file\n"
        "---\n"
        f"{body}",
        encoding="utf-8",
    )
    return directory


def _project_skill(workspace: Path, name: str) -> None:
    path = workspace / ".agent" / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"---\nname: {name}\ndescription: Project skill\nallowed_tools:\n  - read_file\n---\nProject body.\n",
        encoding="utf-8",
    )


def test_install_publishes_enabled_user_skill_visible_to_discovery(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)

    item = store.install(_FIXTURE_SKILL)

    assert (item.name, item.source, item.enabled, item.status) == ("reviewer", "user", True, "valid")
    catalog = discover_skills(workspace, home=home)
    assert catalog["reviewer"].source == "user"
    assert catalog["reviewer"].body is None
    assert "code-dev" in catalog
    loaded = load_selected_skills(workspace, ["reviewer"], max_chars=2_000, home=home)
    assert "REVIEWER-V1-BODY-MARKER" in loaded[0].body


def test_inventory_lists_builtin_project_and_user_sources(tmp_path) -> None:
    store, workspace, _ = _store(tmp_path)
    _project_skill(workspace, "planner")
    store.install(_FIXTURE_SKILL)

    items = {item.name: item for item in store.inventory()}

    assert items["code-dev"].source == "builtin"
    assert items["planner"].source == "project"
    assert items["reviewer"].source == "user"
    assert all(item.enabled for item in items.values())


def test_project_skill_still_overrides_builtin(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    _project_skill(workspace, "code-dev")

    catalog = discover_skills(workspace, home=home)

    assert catalog["code-dev"].source == "project"
    assert [item.source for item in store.inventory() if item.name == "code-dev"] == ["project"]


def test_user_skill_colliding_with_builtin_is_rejected_at_install(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    candidate = _write_candidate(tmp_path / "candidates", "code-dev")

    with pytest.raises(SkillError, match="conflict|exists"):
        store.install(candidate)


def test_user_skill_colliding_with_later_project_skill_fails_discovery_closed(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    store.install(_FIXTURE_SKILL)
    _project_skill(workspace, "reviewer")

    with pytest.raises(SkillError, match="conflict"):
        discover_skills(workspace, home=home)

    conflict = {item.name: item for item in store.inventory()}["reviewer"]
    assert conflict.status == "conflict"


def test_disabled_user_skill_is_inventory_only_and_body_never_loads(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    store.install(_FIXTURE_SKILL)

    item = store.set_enabled("reviewer", False)

    assert (item.enabled, item.status) == (False, "disabled")
    assert "reviewer" not in discover_skills(workspace, home=home)
    with pytest.raises(SkillError, match="disabled"):
        load_selected_skills(workspace, ["reviewer"], max_chars=2_000, home=home)
    assert load_selected_skills(workspace, ["code-dev"], max_chars=200, home=home)[0].name == "code-dev"

    assert store.set_enabled("reviewer", True).enabled is True
    assert "reviewer" in discover_skills(workspace, home=home)


def test_state_only_orphan_is_visible_but_never_blocks_discovery(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    store.install(_FIXTURE_SKILL)
    store.set_enabled("reviewer", False)
    installed = home / ".agent" / "skills" / "reviewer"
    for path in sorted(installed.rglob("*"), reverse=True):
        path.unlink()
    installed.rmdir()

    orphan = {item.name: item for item in store.inventory()}["reviewer"]

    assert (orphan.source, orphan.enabled, orphan.status) == ("orphan", False, "orphan")
    assert "reviewer" not in discover_skills(workspace, home=home)
    with pytest.raises(SkillError, match="does not exist|not found"):
        store.set_enabled("reviewer", True)

    store.remove("reviewer")
    assert "reviewer" not in {item.name for item in store.inventory()}

    store.install(_FIXTURE_SKILL)
    assert {item.name: item for item in store.inventory()}["reviewer"].enabled is True


def test_remove_only_targets_user_skills(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    _project_skill(workspace, "planner")
    store.install(_FIXTURE_SKILL)

    with pytest.raises(SkillError, match="builtin|cannot"):
        store.remove("code-dev")
    with pytest.raises(SkillError, match="project|cannot"):
        store.remove("planner")

    store.remove("reviewer")
    assert not (home / ".agent" / "skills" / "reviewer").exists()
    assert "reviewer" not in discover_skills(workspace, home=home)
    store.remove("reviewer")


def test_validate_directory_reports_without_writing(tmp_path) -> None:
    store, _, home = _store(tmp_path)

    item = store.validate_directory(_FIXTURE_SKILL)

    assert (item.name, item.status) == ("reviewer", "valid")
    assert not (home / ".agent" / "skills").exists()


def test_frontmatter_name_is_authoritative_over_the_source_directory(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    candidate = _write_candidate(tmp_path / "candidates", "alpha-v3", frontmatter_name="alpha")

    item = store.install(candidate)

    assert item.name == "alpha"
    assert (home / ".agent" / "skills" / "alpha" / "SKILL.md").is_file()
    assert not (home / ".agent" / "skills" / "alpha-v3").exists()
    assert discover_skills(workspace, home=home)["alpha"].source == "user"


def test_installed_directory_name_must_match_its_frontmatter(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    store.install(_FIXTURE_SKILL)
    installed = home / ".agent" / "skills" / "reviewer" / "SKILL.md"
    installed.write_text(
        installed.read_text(encoding="utf-8").replace("name: reviewer", "name: impostor"),
        encoding="utf-8",
    )

    with pytest.raises(SkillError, match="does not match"):
        discover_skills(workspace, home=home)


@pytest.mark.parametrize("name", ["CON", "nul", "alpha.", ".hidden", "a" * 65, "bad/name"])
def test_unsafe_candidate_names_are_rejected(tmp_path, name) -> None:
    store, _, _ = _store(tmp_path)
    root = tmp_path / "candidates"
    root.mkdir(parents=True, exist_ok=True)
    directory = root / "candidate"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Candidate\n---\nBody.\n", encoding="utf-8"
    )

    with pytest.raises(SkillError):
        store.validate_directory(directory)


def test_candidate_rejects_case_folded_collision_with_existing_user_skill(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    store.install(_FIXTURE_SKILL)
    candidate = _write_candidate(tmp_path / "candidates", "REVIEWER")

    with pytest.raises(SkillError, match="case|exists|conflict"):
        store.install(candidate)


def test_candidate_enforces_file_count_limit(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    candidate = _write_candidate(tmp_path / "many", "many")
    for index in range(128):
        (candidate / f"file{index}.txt").write_text("x", encoding="utf-8")

    with pytest.raises(SkillError, match="files|limit"):
        store.validate_directory(candidate)


def test_candidate_enforces_single_file_and_skill_size_limits(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    big_file = _write_candidate(tmp_path / "big", "big")
    (big_file / "asset.bin").write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(SkillError, match="size|limit|large"):
        store.validate_directory(big_file)

    big_skill = _write_candidate(tmp_path / "bigskill", "bigskill", body="y" * (256 * 1024 + 1))
    with pytest.raises(SkillError, match="size|limit|large"):
        store.validate_directory(big_skill)


def test_candidate_rejects_links_and_non_regular_entries(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    candidate = _write_candidate(tmp_path / "candidates", "linked")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    try:
        (candidate / "link.txt").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(SkillError, match="link|reparse|regular"):
        store.validate_directory(candidate)


def test_user_store_inside_workspace_is_rejected(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = SkillStore(workspace, home=workspace / "home")

    with pytest.raises(SkillError, match="workspace"):
        store.install(_FIXTURE_SKILL)


def test_install_and_validate_never_execute_candidate_files(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    candidate = _write_candidate(tmp_path / "candidates", "scripted")
    marker = tmp_path / "executed.txt"
    (candidate / "setup.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )

    store.validate_directory(candidate)
    store.install(candidate)

    assert not marker.exists()
    assert (home / ".agent" / "skills" / "scripted" / "setup.py").is_file()
    assert discover_skills(workspace, home=home)["scripted"].source == "user"


def test_install_rejects_candidate_without_skill_document(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    candidate = tmp_path / "candidates" / "empty"
    candidate.mkdir(parents=True)

    with pytest.raises(SkillError, match="SKILL.md"):
        store.install(candidate)


def test_install_is_atomic_and_leaves_no_partial_target(tmp_path, monkeypatch) -> None:
    import agent._user_store as user_store_module

    store, workspace, home = _store(tmp_path)
    store.install(_FIXTURE_SKILL)
    real_write_record = user_store_module.write_record

    def fail_commit(root: Path, tx: Path, record: dict) -> None:
        if record.get("phase") == "committed":
            raise user_store_module.UserStoreError("injected commit failure")
        real_write_record(root, tx, record)

    monkeypatch.setattr(user_store_module, "write_record", fail_commit)
    candidate = _write_candidate(tmp_path / "candidates", "second")

    with pytest.raises(SkillError, match="injected commit failure|write"):
        store.install(candidate)

    monkeypatch.undo()
    names = {item.name for item in store.inventory()}
    assert "second" not in names
    assert discover_skills(workspace, home=home)["reviewer"].source == "user"
