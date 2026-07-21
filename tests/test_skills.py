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

    item = store.validate_source(_FIXTURE_SKILL)

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
        store.validate_source(directory)


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
        store.validate_source(candidate)


def test_candidate_enforces_single_file_and_skill_size_limits(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    big_file = _write_candidate(tmp_path / "big", "big")
    (big_file / "asset.bin").write_bytes(b"x" * (1024 * 1024 + 1))
    with pytest.raises(SkillError, match="size|limit|large"):
        store.validate_source(big_file)

    big_skill = _write_candidate(tmp_path / "bigskill", "bigskill", body="y" * (256 * 1024 + 1))
    with pytest.raises(SkillError, match="size|limit|large"):
        store.validate_source(big_skill)


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
        store.validate_source(candidate)


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

    store.validate_source(candidate)
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


_FIXTURE_V2 = (Path(__file__).parent / "fixtures" / "skills" / "reviewer-v2").resolve()
_FIXTURE_INVALID = (Path(__file__).parent / "fixtures" / "skills" / "reviewer-invalid").resolve()
_VALID_DOCUMENT = (
    b"---\nname: packaged\ndescription: Packaged skill\nallowed_tools:\n  - read_file\n---\nBody.\n"
)


def _write_archive(path: Path, members: list[tuple[str, bytes]]) -> Path:
    import zipfile

    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members:
            archive.writestr(name, data)
    return path


def test_install_copies_ordinary_resources_alongside_the_document(tmp_path) -> None:
    store, _, home = _store(tmp_path)

    store.install(_FIXTURE_SKILL)

    reference = home / ".agent" / "skills" / "reviewer" / "reference.md"
    assert "RESOURCE-V1-MARKER" in reference.read_text(encoding="utf-8")


def test_update_replaces_body_and_resources_and_keeps_disabled_state(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    store.install(_FIXTURE_SKILL)
    store.set_enabled("reviewer", False)

    item = store.update("reviewer", _FIXTURE_V2)

    assert (item.name, item.enabled, item.status) == ("reviewer", False, "disabled")
    installed = home / ".agent" / "skills" / "reviewer"
    document = (installed / "SKILL.md").read_text(encoding="utf-8")
    assert "REVIEWER-V2-BODY-MARKER" in document
    assert "REVIEWER-V1-BODY-MARKER" not in document
    assert "RESOURCE-V2-MARKER" in (installed / "reference.md").read_text(encoding="utf-8")

    store.set_enabled("reviewer", True)
    loaded = load_selected_skills(workspace, ["reviewer"], max_chars=4_000, home=home)
    assert "revision:v2" in loaded[0].body


def test_update_rejects_mismatched_name_invalid_candidate_and_non_user_targets(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    _project_skill(workspace, "planner")
    store.install(_FIXTURE_SKILL)
    installed = home / ".agent" / "skills" / "reviewer" / "SKILL.md"
    before = installed.read_bytes()
    other = _write_candidate(tmp_path / "candidates", "other")

    with pytest.raises(SkillError, match="name"):
        store.update("reviewer", other)
    with pytest.raises(SkillError, match="frontmatter"):
        store.update("reviewer", _FIXTURE_INVALID)
    with pytest.raises(SkillError, match="builtin|cannot"):
        store.update("code-dev", _FIXTURE_V2)
    with pytest.raises(SkillError, match="project|cannot"):
        store.update("planner", _FIXTURE_V2)
    with pytest.raises(SkillError, match="does not exist|not found"):
        store.update("missing", _FIXTURE_V2)

    assert installed.read_bytes() == before


def test_package_round_trip_preserves_document_and_resources(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    store.install(_FIXTURE_V2)
    output = tmp_path / "reviewer.skill.zip"

    store.package("reviewer", output)

    assert output.is_file()
    store.remove("reviewer")
    assert store.validate_source(output).name == "reviewer"
    store.install(output)

    installed = home / ".agent" / "skills" / "reviewer"
    assert (installed / "SKILL.md").read_bytes() == (_FIXTURE_V2 / "SKILL.md").read_bytes()
    assert (installed / "reference.md").read_bytes() == (_FIXTURE_V2 / "reference.md").read_bytes()
    assert discover_skills(workspace, home=home)["reviewer"].source == "user"


def test_repeated_package_produces_identical_archive_bytes(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    store.install(_FIXTURE_V2)
    first = tmp_path / "first.skill.zip"
    second = tmp_path / "second.skill.zip"

    store.package("reviewer", first)
    store.package("reviewer", second)

    assert first.read_bytes() == second.read_bytes()


def test_package_never_includes_internal_state_files(tmp_path) -> None:
    import zipfile

    store, _, _ = _store(tmp_path)
    store.install(_FIXTURE_V2)
    store.set_enabled("reviewer", False)
    output = tmp_path / "reviewer.skill.zip"

    store.package("reviewer", output)

    with zipfile.ZipFile(output) as archive:
        names = sorted(archive.namelist())
    assert names == ["SKILL.md", "reference.md"]


def test_package_refuses_unsafe_or_existing_outputs(tmp_path) -> None:
    store, _, home = _store(tmp_path)
    store.install(_FIXTURE_V2)
    existing = tmp_path / "taken.skill.zip"
    existing.write_bytes(b"keep\n")

    with pytest.raises(SkillError, match="exists"):
        store.package("reviewer", existing)
    with pytest.raises(SkillError, match="skill.zip"):
        store.package("reviewer", tmp_path / "wrong-suffix.zip")
    with pytest.raises(SkillError, match="parent|directory"):
        store.package("reviewer", tmp_path / "missing-dir" / "out.skill.zip")
    with pytest.raises(SkillError, match="store|user"):
        store.package("reviewer", home / ".agent" / "out.skill.zip")
    with pytest.raises(SkillError, match="builtin|cannot|user"):
        store.package("code-dev", tmp_path / "builtin.skill.zip")

    assert existing.read_bytes() == b"keep\n"


def test_package_leaves_no_target_or_temp_file_when_publishing_fails(tmp_path, monkeypatch) -> None:
    import agent.core.skills as skills_module

    store, _, _ = _store(tmp_path)
    store.install(_FIXTURE_V2)
    output = tmp_path / "reviewer.skill.zip"

    def failing_link(source, target):
        raise OSError("simulated hard link failure")

    monkeypatch.setattr(skills_module.os, "link", failing_link)

    with pytest.raises(SkillError, match="link|publish"):
        store.package("reviewer", output)

    assert not output.exists()
    assert [path.name for path in tmp_path.iterdir() if path.name.endswith(".tmp")] == []


@pytest.mark.parametrize(
    "member",
    [
        "../escape.txt",
        "/absolute.txt",
        "C:/drive.txt",
        "nested/../../escape.txt",
    ],
)
def test_archive_rejects_path_traversal_members(tmp_path, member) -> None:
    store, _, _ = _store(tmp_path)
    archive = _write_archive(
        tmp_path / "bad.skill.zip",
        [("SKILL.md", _VALID_DOCUMENT), (member, b"payload")],
    )

    with pytest.raises(SkillError):
        store.validate_source(archive)


@pytest.mark.filterwarnings("ignore:Duplicate name:UserWarning")
def test_archive_rejects_duplicate_and_case_folded_members(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    duplicate = _write_archive(
        tmp_path / "dup.skill.zip",
        [("SKILL.md", _VALID_DOCUMENT), ("note.txt", b"a"), ("note.txt", b"b")],
    )
    folded = _write_archive(
        tmp_path / "folded.skill.zip",
        [("SKILL.md", _VALID_DOCUMENT), ("Note.txt", b"a"), ("note.txt", b"b")],
    )

    with pytest.raises(SkillError, match="duplicate|case"):
        store.validate_source(duplicate)
    with pytest.raises(SkillError, match="duplicate|case"):
        store.validate_source(folded)


def test_archive_rejects_symlink_members(tmp_path) -> None:
    import stat
    import zipfile

    store, _, _ = _store(tmp_path)
    path = tmp_path / "link.skill.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("SKILL.md", _VALID_DOCUMENT)
        info = zipfile.ZipInfo("link.txt")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "/etc/passwd")

    with pytest.raises(SkillError, match="link|regular"):
        store.validate_source(path)


def test_archive_rejects_oversized_and_over_counted_members(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    oversized = _write_archive(
        tmp_path / "big.skill.zip",
        [("SKILL.md", _VALID_DOCUMENT), ("asset.bin", b"x" * (1024 * 1024 + 1))],
    )
    too_many = _write_archive(
        tmp_path / "many.skill.zip",
        [("SKILL.md", _VALID_DOCUMENT)] + [(f"file{index}.txt", b"x") for index in range(128)],
    )

    with pytest.raises(SkillError, match="size|limit|large"):
        store.validate_source(oversized)
    with pytest.raises(SkillError, match="files|limit|members"):
        store.validate_source(too_many)


def test_archive_without_root_document_is_rejected(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    nested = _write_archive(tmp_path / "nested.skill.zip", [("reviewer/SKILL.md", _VALID_DOCUMENT)])

    with pytest.raises(SkillError, match="SKILL.md"):
        store.validate_source(nested)


def test_rejected_archive_never_writes_the_store_or_escapes(tmp_path) -> None:
    store, _, home = _store(tmp_path)
    archive = _write_archive(
        tmp_path / "bad.skill.zip",
        [("SKILL.md", _VALID_DOCUMENT), ("../escape.txt", b"payload")],
    )

    with pytest.raises(SkillError):
        store.install(archive)

    assert not (home / ".agent" / "skills" / "packaged").exists()
    assert not (tmp_path / "escape.txt").exists()


def test_doctor_reports_a_healthy_store(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    store.install(_FIXTURE_SKILL)

    report = store.doctor(default_skills=["code-dev", "reviewer"])

    assert report.healthy is True
    assert report.problems == ()
    assert all("REVIEWER-V1-BODY-MARKER" not in item for item in report.problems)


def test_doctor_reports_disabled_defaults_orphans_and_collisions(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    store.install(_FIXTURE_SKILL)
    store.set_enabled("reviewer", False)

    report = store.doctor(default_skills=["reviewer", "missing"])

    assert report.healthy is False
    assert any("missing" in problem for problem in report.problems)
    assert any("reviewer" in problem for problem in report.problems)

    store.set_enabled("reviewer", True)
    _project_skill(workspace, "reviewer")
    collision = store.doctor(default_skills=[])
    assert collision.healthy is False
    assert any("same name" in problem or "conflict" in problem for problem in collision.problems)


_BOM_DOCUMENT = (
    b"\xef\xbb\xbf---\nname: bom\ndescription: Saved by a Windows editor\n"
    b"allowed_tools:\n  - read_file\n---\nBOM-BODY-MARKER\n"
)


def test_skill_document_with_a_utf8_bom_is_accepted(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    candidate = tmp_path / "candidates" / "bom"
    candidate.mkdir(parents=True)
    (candidate / "SKILL.md").write_bytes(_BOM_DOCUMENT)

    assert store.validate_source(candidate).name == "bom"
    store.install(candidate)

    assert discover_skills(workspace, home=home)["bom"].source == "user"
    loaded = load_selected_skills(workspace, ["bom"], max_chars=2_000, home=home)
    assert "BOM-BODY-MARKER" in loaded[0].body
    assert not loaded[0].name.startswith("﻿")


def _break_installed_skill(home: Path, name: str) -> Path:
    """Simulate a delete that died after unlinking the document."""
    installed = home / ".agent" / "skills" / name
    (installed / "SKILL.md").unlink()
    return installed


def test_directory_without_a_document_is_visible_removable_and_never_silently_deleted(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    store.install(_FIXTURE_SKILL)
    installed = _break_installed_skill(home, "reviewer")
    (installed / "user-data.txt").write_text("keep me\n", encoding="utf-8")

    reported = {item.name: item for item in store.inventory()}["reviewer"]
    assert (reported.source, reported.status, reported.enabled) == ("user", "invalid", False)
    assert "SKILL.md" in (reported.message or "")

    # A reinstall must refuse rather than replace or delete the occupied name.
    with pytest.raises(SkillError, match="already exists"):
        store.install(_FIXTURE_SKILL)
    assert (installed / "user-data.txt").read_text(encoding="utf-8") == "keep me\n"

    # Discovery keeps ignoring it, so a broken directory never breaks a run.
    assert "reviewer" not in discover_skills(workspace, home=home)

    store.remove("reviewer")
    assert not installed.exists()
    store.install(_FIXTURE_SKILL)
    assert discover_skills(workspace, home=home)["reviewer"].source == "user"


def test_doctor_reports_a_directory_without_a_document(tmp_path) -> None:
    store, _, home = _store(tmp_path)
    store.install(_FIXTURE_SKILL)
    _break_installed_skill(home, "reviewer")

    report = store.doctor(default_skills=[])

    assert report.healthy is False
    assert any("reviewer" in problem for problem in report.problems)


def test_archive_rejects_stream_and_trailing_punctuation_member_names(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    stream = _write_archive(
        tmp_path / "stream.skill.zip",
        [("SKILL.md", _VALID_DOCUMENT), ("note.txt:hidden", b"payload")],
    )
    trailing = _write_archive(
        tmp_path / "trailing.skill.zip",
        [("SKILL.md", _VALID_DOCUMENT), ("note.txt. ", b"payload")],
    )

    with pytest.raises(SkillError, match="unsafe path component"):
        store.validate_source(stream)
    with pytest.raises(SkillError, match="unsafe path component"):
        store.validate_source(trailing)


def test_oversized_archive_is_rejected_before_it_is_parsed(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    archive = tmp_path / "huge.skill.zip"
    archive.write_bytes(b"x" * (8 * 1024 * 1024 + 1))

    with pytest.raises(SkillError, match="8 MiB"):
        store.validate_source(archive)


def test_publish_failure_reports_the_failing_step(tmp_path, monkeypatch) -> None:
    import agent.core.skills as skills_module

    store, _, _ = _store(tmp_path)
    real_replace = skills_module.os.replace

    def failing_replace(source, target):
        if Path(target).name == "reviewer":
            raise OSError("simulated rename failure")
        return real_replace(source, target)

    monkeypatch.setattr(skills_module.os, "replace", failing_replace)

    with pytest.raises(SkillError, match="simulated rename failure"):
        store.install(_FIXTURE_SKILL)


def test_unrecognized_store_entries_are_reported_but_never_break_discovery(tmp_path) -> None:
    store, workspace, home = _store(tmp_path)
    store.install(_FIXTURE_SKILL)
    stray = home / ".agent" / "skills" / "not a skill"
    stray.mkdir()
    (stray / "notes.txt").write_text("user data\n", encoding="utf-8")

    # A folder the user happened to create must not brick every run.
    catalog = discover_skills(workspace, home=home)
    assert catalog["reviewer"].source == "user"
    assert load_selected_skills(workspace, ["reviewer"], max_chars=2_000, home=home)[0].name == "reviewer"

    reported = {item.name: item for item in store.inventory()}["not a skill"]
    assert (reported.source, reported.status, reported.enabled) == ("user", "invalid", False)
    assert "delete it manually" in (reported.message or "")
    assert store.doctor(default_skills=[]).healthy is False
    assert (stray / "notes.txt").is_file()


def test_install_never_changes_default_skills(tmp_path) -> None:
    store, workspace, _ = _store(tmp_path)
    config = workspace / ".agent" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('default_skills = ["code-dev"]\n', encoding="utf-8")
    before = config.read_bytes()

    store.install(_FIXTURE_SKILL)

    assert config.read_bytes() == before


def test_package_refuses_a_symlinked_output(tmp_path) -> None:
    store, _, _ = _store(tmp_path)
    store.install(_FIXTURE_SKILL)
    real = tmp_path / "real.zip"
    real.write_bytes(b"keep\n")
    link = tmp_path / "linked.skill.zip"
    try:
        link.symlink_to(real)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(SkillError, match="exists"):
        store.package("reviewer", link)

    assert real.read_bytes() == b"keep\n"


def test_an_empty_user_store_keeps_builtin_and_project_behaviour_identical(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()
    _project_skill(workspace, "planner")

    catalog = discover_skills(workspace, home=empty_home)

    assert catalog["planner"].source == "project"
    assert catalog["code-dev"].source == "builtin"
    assert not (empty_home / ".agent").exists()
    loaded = load_selected_skills(workspace, ["code-dev"], max_chars=200, home=empty_home)
    assert loaded[0].name == "code-dev"
    assert not (empty_home / ".agent").exists()
