"""平台装配、控制循环、并发探测与跨重启一致性。"""

from __future__ import annotations

import pytest

from heatnet.app import build_platform
from heatnet.config import default_config
from heatnet.station.service import CancelToken


def test_startup_dispatch_and_cycle(online):
    for _ in range(120):
        online.cycle(dt=1.0)
    status = online.status()
    assert status["source"]["state"] == "online"
    assert status["source"]["quality_confirmed"] is True
    assert status["curve"]["stale"] is False
    assert status["primary"]["flow_t_h"] > 0.0
    assert status["pump"]["running"] is False
    assert status["stations"]["count"] == 6
    assert online.audit.summary()["total"] > 0


def test_dispatch_uses_priority_order_and_independent_flows(platform):
    platform.start()
    platform.push_weather(-8.0)
    platform.startup(-8.0, 60.0)
    report = platform.dispatch(60.0, 60.0)
    assert report["ok"] is True
    assert report["adjusted"][0] == "st01"
    assert len(report["flows"]) == 6
    assert platform.network.dispatches() == 1
    assert platform.network.flow_t_h() < platform.network.baseline_t_h()


def test_dispatch_honours_cancellation(platform):
    platform.start()
    platform.push_weather(-8.0)
    platform.startup(-8.0, 60.0)
    token = CancelToken("client-timeout")
    token.cancel()
    report = platform.dispatch(60.0, 60.0, ["north"], token)
    assert report["ok"] is False
    assert report["violations"] == ["cancelled:client-timeout"]
    assert platform.service.valve("st01").moves() == 0


def test_split_zone_rebuilds_mapping(platform):
    report = platform.split_zone("north", ["st02", "st03"], "north-west")
    assert report["ok"] is True
    assert platform.mapping.zone_of("st02") == "north-west"
    assert platform.mapping.generation() == 2
    assert platform.service.get("st02").zone() == "north-west"
    assert platform.zones.names() == ["east", "north", "north-west", "south"]


def test_replay_valves_skips_applied_commands(platform):
    platform.queue_commands("st01", [40.0, 65.0])
    first = platform.replay_valves(["st01"])
    assert first["replayed"] == 2
    second = platform.replay_valves(["st01"])
    assert second["replayed"] == 0
    assert platform.valves["st01"].position_pct() == pytest.approx(65.0)


def test_collect_heat_and_settle_quota(platform):
    for name in platform.meter_names():
        platform.collect_heat(name, 5.0)
    report = platform.quota_report()
    assert report["ledger"]["total_mwh"] == pytest.approx(30.0)
    assert report["accumulator"]["count"] == 6
    settled = platform.settle_quota()
    assert settled["period"] == 1
    assert len(settled["lines"]) == 6
    assert platform.ledger.periods() == 1


def test_concurrency_probe_reports_no_lost_state(platform):
    report = platform.concurrency_probe(rounds=24)
    assert report["ok"] is True
    assert report["source"]["mixed_pairs"] == 0
    assert report["meter"]["lost_increments"] == pytest.approx(0.0)


def test_trip_state_survives_restart(platform, clock):
    platform.start()
    platform.push_weather(-8.0)
    platform.trip("overtemperature")
    assert platform.source.state() == "tripped"

    restarted = build_platform(default_config(), clock=clock, storage_root=platform.store.root)
    assert restarted.source.state() == "tripped"
    assert restarted.source.trip_reason() == "overtemperature"
    assert restarted.status()["operations"] >= 1


def test_valve_position_survives_restart(platform, clock):
    platform.start()
    platform.queue_commands("st02", [55.0])
    platform.replay_valves(["st02"])

    restarted = build_platform(default_config(), clock=clock, storage_root=platform.store.root)
    assert restarted.valves["st02"].position_pct() == pytest.approx(55.0)
    assert restarted.checkpoint.load("st02") == 1


def test_snapshot_exposes_all_sections(online):
    snapshot = online.snapshot()
    for key in ("status", "topology", "namespaces", "zones", "mapping", "trend", "billing"):
        assert key in snapshot
    assert snapshot["topology"]["order"][0] == "weather"
    assert snapshot["namespaces"]["count"] == 25
    assert snapshot["status"]["stations"]["count"] == 6


def test_trend_collects_signals_after_cycles(online):
    for _ in range(5):
        online.cycle(dt=5.0)
    samples = online.trend.series("supply_c", limit=10)
    assert len(samples) == 5
    assert online.trend.latest("network_flow_t_h") is not None
    filled = online.trend.fill_gaps("supply_c", samples)
    assert len(filled) >= len(samples)


def test_forecast_and_billing_reports(platform):
    forecast = platform.outdoor_forecast(-10.0, steps=4)
    assert forecast["count"] == 4
    assert forecast["max_supply_c"] >= forecast["min_supply_c"]
    platform.collect_heat(platform.meter_names()[0], 40.0)
    lines = platform.billing(10.0)
    assert lines and lines[0]["overage_mwh"] > 0.0


def test_reset_state_clears_counters(platform):
    platform.start()
    platform.cycle(dt=1.0)
    assert platform.reset_state() is True
    assert platform.reset_state() is False


def test_note_error_writes_audit_entry(platform):
    from heatnet.errors import InterlockError

    platform.start()
    record = platform.note_error(InterlockError("联锁拒绝", component="source"))
    assert record["component"] == "source"
    assert platform.audit.summary()["by_severity"]["warning"] == 1
    assert platform.audit.count("error") == 1
