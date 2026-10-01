"""文件型持久化：原子文档、分段流水、用量统计与两个语义封装。"""

from __future__ import annotations

import json

import pytest

from heatnet.errors import StorageError
from heatnet.store.command import CommandCheckpoint
from heatnet.store.jsonfile import JsonStore
from heatnet.store.journal import JsonlJournal
from heatnet.store.metrics import StoreMetrics
from heatnet.store.state import DurableState


def test_json_store_round_trip_and_nested_id(tmp_path):
    store = JsonStore(str(tmp_path))
    path = store.write("valve/st01", {"position_pct": 42.5})
    assert path.endswith("st01.json")
    assert store.exists("valve/st01") is True
    assert store.read("valve/st01")["position_pct"] == pytest.approx(42.5)
    assert store.read("missing/doc") is None
    assert store.list_ids() == ["valve/st01"]
    assert store.remove("valve/st01") is True
    assert store.remove("valve/st01") is False


def test_json_store_rejects_corrupt_document(tmp_path):
    store = JsonStore(str(tmp_path))
    store.write("broken", {"ok": True})
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(StorageError):
        store.read("broken")


def test_journal_rolls_segments_and_replays(tmp_path):
    journal = JsonlJournal(str(tmp_path), "audit", segment_limit=2)
    for index in range(5):
        journal.append({"index": index})
    assert journal.count() == 5
    assert journal.active_segment() == 2
    assert len(journal.segments()) == 3
    assert journal.topic == "audit"
    assert [item["index"] for item in journal.read_segment(1)] == [2, 3]
    assert len(journal.read_all()) == 5
    assert journal.read_segment(99) == []


def test_journal_resumes_count_after_reopen(tmp_path):
    first = JsonlJournal(str(tmp_path), "audit", segment_limit=2)
    first.append({"index": 0})
    first.append({"index": 1})
    second = JsonlJournal(str(tmp_path), "audit", segment_limit=2)
    assert second.count() == 2
    second.append({"index": 2})
    assert second.active_segment() == 1
    assert len(second.read_all()) == 3


def test_store_metrics_counts_files(tmp_path):
    store = JsonStore(str(tmp_path))
    store.write("a", {"x": 1})
    store.write("nested/b", {"y": 2})
    journal = JsonlJournal(str(tmp_path), "audit", segment_limit=8)
    journal.append({"x": 1})
    metrics = StoreMetrics(str(tmp_path))
    summary = metrics.summary()
    assert summary["files"] == 3
    assert summary["bytes"] > 0
    assert summary["audit_segments"] == 1
    assert metrics.usage().files == 3
    assert metrics.usage().as_dict()["path"] == "."


def test_durable_state_round_trip(tmp_path):
    store = JsonStore(str(tmp_path))
    state = DurableState(store)
    assert state.load("valve/st01") == {}
    state.save("valve/st01", {"position_pct": 30.0})
    assert state.load("valve/st01")["position_pct"] == pytest.approx(30.0)
    with pytest.raises(ValueError):
        state.save("valve/st01", ["not-a-mapping"])
    assert state.doc_id("valve/st01") == "state/valve/st01"
    assert state.store is store


def test_command_checkpoint_round_trip(tmp_path):
    store = JsonStore(str(tmp_path))
    checkpoint = CommandCheckpoint(store)
    assert checkpoint.load("st01") == 0
    checkpoint.save("st01", 4)
    assert checkpoint.load("st01") == 4
    assert checkpoint.doc_id("st01") == "command/st01"
    assert checkpoint.store is store
    with pytest.raises(ValueError):
        checkpoint.save("st01", -1)


def test_journal_records_are_json_lines(tmp_path):
    journal = JsonlJournal(str(tmp_path), "audit", segment_limit=8)
    journal.append({"asset": "st01", "action": "dispatch"})
    line = (tmp_path / "audit-00000.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(line)["asset"] == "st01"
