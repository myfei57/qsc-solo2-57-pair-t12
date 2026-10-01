"""阀门落盘顺序、存储失败与指令队列检查点。"""

from __future__ import annotations

import pytest

from heatnet.config import default_config
from heatnet.errors import StorageError
from heatnet.store.command import CommandCheckpoint
from heatnet.store.jsonfile import JsonStore
from heatnet.store.state import DurableState
from heatnet.valve.move import load_valve, move_valve
from heatnet.valve.queue import ValveCommandQueue, replay_queue
from heatnet.valve.valve import Valve


class _FailingDurable:
    """写盘总是失败的当前态封装，用来验证落盘失败时内存不推进。"""

    def load(self, component: str) -> dict:
        return {}

    def save(self, component: str, payload: object) -> str:
        raise StorageError("模拟写盘失败", component="store")


def _valve(position_pct: float = 0.0) -> Valve:
    return Valve("st01.mix", default_config().valve, position_pct)


def test_move_persists_before_applying(tmp_path):
    valve = _valve()
    durable = DurableState(JsonStore(str(tmp_path)))
    move = move_valve(valve, durable, 45.0)
    assert move.ok is True
    assert move.persisted is True
    assert valve.position_pct() == pytest.approx(45.0)
    assert durable.load("valve/st01.mix")["position_pct"] == pytest.approx(45.0)
    assert valve.moves() == 1


def test_storage_failure_keeps_memory_position_and_allows_retry(tmp_path):
    valve = _valve(position_pct=20.0)
    durable = DurableState(JsonStore(str(tmp_path)))
    move_valve(valve, durable, 20.0)
    before = valve.position_pct()

    with pytest.raises(StorageError):
        move_valve(valve, _FailingDurable(), 80.0)
    assert valve.position_pct() == pytest.approx(before)
    assert valve.rejected() == 1

    retry = move_valve(valve, durable, 80.0)
    assert retry.ok is True
    assert valve.position_pct() == pytest.approx(80.0)
    assert durable.load("valve/st01.mix")["position_pct"] == pytest.approx(80.0)


def test_load_valve_restores_durable_position(tmp_path):
    durable = DurableState(JsonStore(str(tmp_path)))
    original = _valve()
    move_valve(original, durable, 62.5)

    restored = _valve()
    assert load_valve(restored, durable) == pytest.approx(62.5)
    assert load_valve(_valve(), DurableState(JsonStore(str(tmp_path / "empty")))) == pytest.approx(0.0)


def test_queue_replay_skips_applied_commands(tmp_path):
    store = JsonStore(str(tmp_path))
    durable = DurableState(store)
    checkpoint = CommandCheckpoint(store)
    valve = _valve()
    queue = ValveCommandQueue("st01")
    queue.enqueue(30.0, "dispatch")
    queue.enqueue(55.0, "dispatch")
    queue.enqueue(70.0, "local")

    first = replay_queue(valve, durable, queue, checkpoint)
    assert first["replayed"] == 3
    assert first["applied"] == 3
    assert first["skipped"] == 0
    assert valve.position_pct() == pytest.approx(70.0)

    second = replay_queue(valve, durable, queue, checkpoint)
    assert second["replayed"] == 0
    assert second["skipped"] == 3
    assert valve.position_pct() == pytest.approx(70.0)
    assert checkpoint.load("st01") == 3


def test_queue_checkpoint_survives_restart(tmp_path):
    store = JsonStore(str(tmp_path))
    durable = DurableState(store)
    valve = _valve()
    queue = ValveCommandQueue("st01")
    queue.enqueue(40.0, "dispatch")
    queue.enqueue(60.0, "dispatch")
    replay_queue(valve, durable, queue, CommandCheckpoint(store))

    reopened = CommandCheckpoint(JsonStore(str(tmp_path)))
    restarted_valve = _valve(position_pct=60.0)
    restarted = ValveCommandQueue("st01")
    restarted.enqueue(40.0, "dispatch")
    restarted.enqueue(60.0, "dispatch")
    report = replay_queue(restarted_valve, durable, restarted, reopened)
    assert report["replayed"] == 0
    assert restarted_valve.position_pct() == pytest.approx(60.0)
    assert restarted.last_seq() == 2
    assert [command.seq for command in restarted.commands()] == [1, 2]


def test_valve_step_moves_towards_target():
    valve = _valve()
    valve.set_target(48.0)
    for _ in range(600):
        valve.step(1.0)
        if valve.at_target():
            break
    assert valve.at_target() is True
    assert valve.target_pct() == pytest.approx(48.0)
    assert valve.snapshot().settled is True
    with pytest.raises(ValueError):
        valve.step(0.0)
