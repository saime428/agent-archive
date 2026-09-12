from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import pytest

from agent.core.memory import MemoryError, MemoryStore


def test_memory_candidate_accept_and_undo(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    candidate = store.add_candidate(source_run_id="run_1", source_excerpt="Remember this fact.")

    assert store.list_candidates()[0].candidate_id == candidate.candidate_id
    assert store.list_entries() == []

    entry = store.accept_candidate(candidate.candidate_id)

    assert entry.entry_id.startswith("mem_")
    assert entry.source_run_id == "run_1"
    assert entry.status == "active"
    assert entry.candidate_id == candidate.candidate_id
    assert store.list_candidates()[0].status == "accepted"
    assert store.list_entries()[0].entry_id == entry.entry_id
    assert json.loads(store.candidates_path.read_text(encoding="utf-8"))["status"] == "pending"
    assert json.loads(store.entries_path.read_text(encoding="utf-8"))["candidate_id"] == candidate.candidate_id

    tombstone = store.undo_entry(entry.entry_id)

    assert tombstone.status == "deleted"
    assert store.list_entries(include_deleted=True)[-1].supersedes == entry.entry_id
    assert store.list_entries() == []


def test_memory_retrieval_is_deterministic_and_budgeted(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    first = store.add_candidate(source_run_id="run_1", source_excerpt="pytest validates parser behavior")
    second = store.add_candidate(source_run_id="run_2", source_excerpt="unrelated deployment note")
    store.accept_candidate(first.candidate_id)
    store.accept_candidate(second.candidate_id)

    matches = store.retrieve("fix parser tests", max_items=3, max_chars=12)

    assert len(matches) == 1
    assert matches[0].source_run_id == "run_1"
    assert matches[0].source_excerpt.endswith("\n[truncated]")


def test_memory_candidate_can_be_rejected_only_once(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    candidate = store.add_candidate(source_run_id="run_1", source_excerpt="Do not keep this note.")

    rejected = store.reject_candidate(candidate.candidate_id)

    assert rejected.status == "rejected"
    assert store.list_candidates() == [rejected]
    with pytest.raises(MemoryError, match="not pending"):
        store.reject_candidate(candidate.candidate_id)
    with pytest.raises(MemoryError, match="not pending"):
        store.accept_candidate(candidate.candidate_id)
    assert store.list_entries(include_deleted=True) == []


def test_memory_revise_delete_and_history_follow_one_current_leaf(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    candidate = store.add_candidate(source_run_id="run_origin", source_excerpt="pytest validates parsers")
    original = store.accept_candidate(candidate.candidate_id)

    revised = store.revise_entry(original.entry_id, "tomllib validates configuration parsers")

    assert revised.source_run_id == "run_origin"
    assert revised.supersedes == original.entry_id
    assert revised.candidate_id == candidate.candidate_id
    assert store.list_entries() == [revised]
    assert store.retrieve("tomllib parser", max_items=5, max_chars=1_000) == [revised]
    assert store.retrieve("pytest", max_items=5, max_chars=1_000) == []
    assert store.entry_history(original.entry_id) == [original, revised]

    with pytest.raises(MemoryError, match="current active"):
        store.revise_entry(original.entry_id, "branch from stale history")

    tombstone = store.delete_entry(revised.entry_id)

    assert tombstone.status == "deleted"
    assert tombstone.source_run_id == "run_origin"
    assert store.list_entries() == []
    assert store.retrieve("tomllib", max_items=5, max_chars=1_000) == []
    assert store.entry_history(revised.entry_id) == [original, revised, tombstone]
    with pytest.raises(MemoryError, match="current active"):
        store.delete_entry(revised.entry_id)


def test_memory_concurrent_accept_has_one_winner(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    candidate = store.add_candidate(source_run_id="run_1", source_excerpt="one accepted memory")
    barrier = threading.Barrier(2)

    def accept() -> str:
        barrier.wait()
        try:
            MemoryStore(tmp_path).accept_candidate(candidate.candidate_id)
        except MemoryError:
            return "error"
        return "accepted"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(lambda _index: accept(), range(2)))

    assert results == ["accepted", "error"]
    assert len(store.list_entries(include_deleted=True)) == 1
    assert store.list_candidates()[0].status == "accepted"


def test_memory_concurrent_accept_reject_has_one_terminal_state(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    candidate = store.add_candidate(source_run_id="run_1", source_excerpt="decide once")
    barrier = threading.Barrier(2)

    def decide(operation: str) -> str:
        barrier.wait()
        try:
            if operation == "accept":
                MemoryStore(tmp_path).accept_candidate(candidate.candidate_id)
            else:
                MemoryStore(tmp_path).reject_candidate(candidate.candidate_id)
        except MemoryError:
            return "error"
        return operation

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(decide, ("accept", "reject")))

    assert results.count("error") == 1
    candidate_state = store.list_candidates()[0].status
    assert candidate_state in {"accepted", "rejected"}
    assert len(store.list_entries(include_deleted=True)) == (1 if candidate_state == "accepted" else 0)


def test_memory_legacy_jsonl_records_remain_readable(tmp_path) -> None:
    root = tmp_path / ".agent" / "memory"
    root.mkdir(parents=True)
    (root / "candidates.jsonl").write_text(
        json.dumps(
            {
                "candidate_id": "cand_legacy",
                "source_run_id": "run_legacy",
                "source_excerpt": "legacy parser memory",
                "created_at": "2026-01-01T00:00:00+00:00",
                "status": "accepted",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "entries.jsonl").write_text(
        json.dumps(
            {
                "entry_id": "mem_legacy",
                "source_run_id": "run_legacy",
                "source_excerpt": "legacy parser memory",
                "created_at": "2026-01-01T00:00:01+00:00",
                "status": "active",
                "supersedes": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    store = MemoryStore(tmp_path)

    assert store.list_candidates()[0].status == "accepted"
    assert store.list_entries()[0].entry_id == "mem_legacy"
    revised = store.revise_entry("mem_legacy", "revised legacy parser memory")
    assert revised.supersedes == "mem_legacy"


@pytest.mark.parametrize(
    ("kind", "message"),
    [("branch", "branches"), ("cycle", "cycle"), ("missing", "unknown entry")],
)
def test_memory_rejects_invalid_supersedes_graph_from_every_entry_path(tmp_path, kind: str, message: str) -> None:
    store = MemoryStore(tmp_path)
    candidate = store.add_candidate(source_run_id="run_1", source_excerpt="parser memory")
    original = store.accept_candidate(candidate.candidate_id)
    first = {**asdict(original), "entry_id": "mem_first", "supersedes": original.entry_id}
    if kind == "branch":
        records = [asdict(original), first, {**first, "entry_id": "mem_second"}]
    elif kind == "cycle":
        records = [
            {**asdict(original), "supersedes": "mem_first"},
            {**first, "supersedes": original.entry_id},
        ]
    else:
        records = [{**asdict(original), "supersedes": "mem_missing"}]
    store.entries_path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    before = store.entries_path.read_bytes()

    operations = [
        lambda: store.list_entries(include_deleted=True),
        lambda: store.retrieve("parser", max_items=5, max_chars=100),
        lambda: store.revise_entry(original.entry_id, "revised parser memory"),
        lambda: store.delete_entry(original.entry_id),
        lambda: store.entry_history(original.entry_id),
    ]
    for operation in operations:
        with pytest.raises(MemoryError, match=message):
            operation()
        assert store.entries_path.read_bytes() == before


def test_memory_rejects_corrupt_and_linked_storage(tmp_path) -> None:
    corrupt_root = tmp_path / "corrupt" / ".agent" / "memory"
    corrupt_root.mkdir(parents=True)
    (corrupt_root / "candidates.jsonl").write_text("not-json\n", encoding="utf-8")

    with pytest.raises(MemoryError, match="parse"):
        MemoryStore(tmp_path / "corrupt").list_candidates()

    linked_workspace = tmp_path / "linked"
    linked_root = linked_workspace / ".agent" / "memory"
    linked_root.parent.mkdir(parents=True)
    external = tmp_path / "external-memory"
    external.mkdir()
    try:
        linked_root.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are not available on this host.")

    with pytest.raises(MemoryError, match="real directory"):
        MemoryStore(linked_workspace).list_candidates()


def test_memory_rejects_empty_and_oversized_revisions(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    candidate = store.add_candidate(source_run_id="run_1", source_excerpt="bounded memory")
    entry = store.accept_candidate(candidate.candidate_id)

    with pytest.raises(MemoryError, match="empty"):
        store.revise_entry(entry.entry_id, "   ")
    with pytest.raises(MemoryError, match="too large"):
        store.revise_entry(entry.entry_id, "x" * 20_001)
    assert store.list_entries() == [entry]


def test_memory_atomic_publish_failure_preserves_previous_log(tmp_path, monkeypatch) -> None:
    store = MemoryStore(tmp_path)
    store.add_candidate(source_run_id="run_1", source_excerpt="first")
    before = store.candidates_path.read_bytes()

    def fail_replace(_source, _target) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr("agent._user_store.os.replace", fail_replace)

    with pytest.raises(MemoryError, match="write"):
        store.add_candidate(source_run_id="run_2", source_excerpt="second")
    assert store.candidates_path.read_bytes() == before
