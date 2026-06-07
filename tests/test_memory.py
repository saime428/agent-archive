from __future__ import annotations

from agent.core.memory import MemoryStore


def test_memory_candidate_accept_and_undo(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    candidate = store.add_candidate(source_run_id="run_1", source_excerpt="Remember this fact.")

    assert store.list_candidates()[0].candidate_id == candidate.candidate_id
    assert store.list_entries() == []

    entry = store.accept_candidate(candidate.candidate_id)

    assert entry.entry_id.startswith("mem_")
    assert entry.source_run_id == "run_1"
    assert entry.status == "active"
    assert store.list_candidates()[0].status == "accepted"
    assert store.list_entries()[0].entry_id == entry.entry_id

    tombstone = store.undo_entry(entry.entry_id)

    assert tombstone.status == "deleted"
    assert store.list_entries(include_deleted=True)[-1].supersedes == entry.entry_id


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
