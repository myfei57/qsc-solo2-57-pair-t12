"""命名空间、时钟、事件总线、标识与趋势缓冲。"""

from __future__ import annotations

import pytest

from heatnet.clock import ManualClock, SystemClock
from heatnet.errors import NamespaceError, PlantError
from heatnet.eventbus import Event, EventBus
from heatnet.ids import IdFactory
from heatnet.ns.registry import Device, NamespaceRegistry
from heatnet.ns.topology import build_default_topology
from heatnet.telemetry import Sample, TrendBuffer


def test_manual_clock_advances_both_axes():
    clock = ManualClock(start=1000.0)
    assert clock.now() == pytest.approx(1000.0)
    clock.sleep(5.0)
    assert clock.now() == pytest.approx(1005.0)
    assert clock.monotonic() == pytest.approx(5.0)
    with pytest.raises(ValueError):
        clock.advance(-1.0)
    assert clock.advance(1.0) == pytest.approx(1006.0)
    assert clock.utc_iso().endswith("Z")


def test_system_clock_reports_real_time():
    clock = SystemClock()
    assert clock.now() > 0
    assert clock.monotonic() >= 0
    clock.sleep(0.0)


def test_namespace_registry_and_topology():
    registry = NamespaceRegistry("heatnet")
    registry.register("plant", "heat_source", "heat-source")
    with pytest.raises(NamespaceError):
        registry.register("plant", "heat_source", "heat-source")
    assert registry.resolve("plant.heat_source").kind == "heat-source"
    assert registry.by_kind("heat-source")[0].address == "plant.heat_source"
    assert registry.describe()["count"] == 1
    assert registry.unit == "heatnet"
    with pytest.raises(NamespaceError):
        registry.resolve("plant.nope")
    assert Device("a", "b", "c").address == "a.b"

    topology = build_default_topology()
    verify = topology.verify({"weather"})
    assert "source" not in verify["missing"]
    assert verify["missing"]["station"] == ["source"]
    assert topology.downstream("weather") == ["source", "station", "actuator", "quota", "audit"]
    assert topology.stage("audit").label == "审计"
    assert topology.predecessors("quota") == ("actuator",)


def test_event_bus_publish_and_history():
    bus = EventBus(history_limit=3)
    seen: list[str] = []
    unsubscribe = bus.subscribe("source", lambda event: seen.append(event.action))
    bus.subscribe("*", lambda event: seen.append(f"*{event.action}"))
    assert bus.publish(Event.of("source", "source", "adjust", flow_t_h=1200.0)) == 2
    assert seen == ["adjust", "*adjust"]
    unsubscribe()
    bus.publish(Event.of("source", "source", "trip"))
    assert seen[-1] == "*trip"
    assert len(bus.history()) == 2
    assert [event.action for event in bus.history("source")] == ["adjust", "trip"]


def test_id_factory_produces_unique_prefixed_ids():
    factory = IdFactory("op")
    first = factory.next()
    second = factory.next()
    assert first.startswith("op-") and second.startswith("op-")
    assert first != second
    assert factory.issued() == 2
    with pytest.raises(ValueError):
        IdFactory("")


def test_trend_buffer_limits_and_gap_filling():
    buffer = TrendBuffer(limit=3, period_s=5.0)
    for index in range(5):
        buffer.append("supply_c", float(index * 5), float(index))
    assert len(buffer.series("supply_c", limit=10)) == 3
    assert buffer.latest("supply_c").value == pytest.approx(4.0)
    filled = buffer.fill_gaps("supply_c", [Sample(0.0, 0.0), Sample(15.0, 3.0)])
    assert [sample.ts for sample in filled] == [0.0, 5.0, 10.0, 15.0]
    assert buffer.snapshot(limit=1)["supply_c"]["latest"]["value"] == pytest.approx(4.0)
    assert buffer.signals() == ["supply_c"]
    assert buffer.period_s == pytest.approx(5.0)


def test_plant_error_carries_component():
    error = PlantError("失败", component="source")
    assert error.as_record()["component"] == "source"
    assert str(error) == "失败"
