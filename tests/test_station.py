"""换热站批量调节、取消语义与流量分批计算。"""

from __future__ import annotations

import pytest

from heatnet.config import default_config
from heatnet.ns.zone import Zone, ZoneRegistry
from heatnet.primary.flow import batch_flows
from heatnet.primary.network import PrimaryNetwork
from heatnet.station.batch import build_plan, run_batch
from heatnet.station.mapping import StationMapping
from heatnet.station.mix import apply_mix
from heatnet.station.service import CancelToken, StationService
from heatnet.station.station import HeatStation
from heatnet.store.jsonfile import JsonStore
from heatnet.store.state import DurableState
from heatnet.valve.valve import Valve


def _stack(tmp_path) -> tuple[ZoneRegistry, StationMapping, StationService, PrimaryNetwork]:
    zones = ZoneRegistry()
    zones.add(Zone(name="north", setpoint_c=62.0))
    zones.add(Zone(name="south", setpoint_c=54.0))
    for station in ("st01", "st02", "st03"):
        zones.assign(station, "north")
    for station in ("st04", "st05"):
        zones.assign(station, "south")

    config = default_config()
    stations = {name: HeatStation(name, zones.zone_of(name), config.station) for name in zones.index()}
    valves = {name: Valve(f"{name}.mix", config.valve) for name in stations}
    service = StationService(stations, valves, DurableState(JsonStore(str(tmp_path))))
    return zones, StationMapping(zones), service, PrimaryNetwork(config.primary)


class _CancelAfter(CancelToken):
    """处理若干个站之后再置位取消，用来验证逐步检查。"""

    def __init__(self, allowed: int) -> None:
        super().__init__("mid-batch")
        self._allowed = allowed
        self._seen = 0

    def cancelled(self) -> bool:
        self._seen += 1
        return self._seen > self._allowed


def test_batch_flows_are_independent_per_station():
    network = PrimaryNetwork(default_config().primary)
    plan = [("st01", 60.0), ("st02", 60.0), ("st03", 60.0)]
    flows = batch_flows(network, plan)
    values = [flow.flow_t_h for flow in flows]
    assert values[0] == pytest.approx(values[1])
    assert values[0] == pytest.approx(values[2])
    assert network.flow_t_h() == pytest.approx(sum(values))
    assert network.flow_t_h() < network.baseline_t_h()
    assert [flow.as_dict()["station"] for flow in flows] == ["st01", "st02", "st03"]
    assert network.dispatches() == 0


def test_adjust_zone_applies_to_every_station(tmp_path):
    zones, mapping, service, _ = _stack(tmp_path)
    report = service.adjust_zone(mapping, "north", 61.0)
    assert report["ok"] is True
    assert report["adjusted"] == ["st01", "st02", "st03"]
    assert report["skipped"] == []
    for name in ("st01", "st02", "st03"):
        assert service.get(name).target_c() == pytest.approx(61.0)
        assert service.valve(name).position_pct() > 0.0
    assert service.batches() == 1
    assert service.aborted() == 0


def test_cancelled_before_start_changes_nothing(tmp_path):
    zones, mapping, service, _ = _stack(tmp_path)
    token = CancelToken("client-timeout")
    token.cancel()
    report = service.adjust_zone(mapping, "north", 61.0, token)
    assert report["ok"] is False
    assert report["adjusted"] == []
    assert report["skipped"] == ["st01", "st02", "st03"]
    assert report["violations"] == ["cancelled:client-timeout"]
    assert service.valve("st01").moves() == 0
    assert service.aborted() == 1


def test_cancellation_is_checked_at_every_station(tmp_path):
    zones, mapping, service, _ = _stack(tmp_path)
    report = service.adjust_zone(mapping, "north", 61.0, _CancelAfter(1))
    assert report["ok"] is False
    assert report["adjusted"] == ["st01"]
    assert report["skipped"] == ["st02", "st03"]
    assert service.get("st02").target_c() == pytest.approx(service.get("st02").limits.setpoint_c)
    assert service.valve("st02").moves() == 0
    with pytest.raises(ValueError):
        service.adjust_zone(mapping, "north", 61.0, None, 0.0)


def test_run_batch_reports_flows_and_adjustments(tmp_path):
    zones, mapping, service, network = _stack(tmp_path)
    report = run_batch(service, mapping, zones, network, ["north", "south"], 60.0, 60.0)
    assert report["ok"] is True
    assert report["planned"] == 5
    assert set(report["adjusted"]) == {"st01", "st02", "st03", "st04", "st05"}
    assert len(report["flows"]) == 5
    assert network.dispatches() == 1
    assert network.flow_t_h() > 0.0


def test_build_plan_orders_by_setpoint(tmp_path):
    zones, mapping, _, _ = _stack(tmp_path)
    plan = build_plan(mapping, zones, ["south", "north"], 60.0)
    assert [station for station, _ in plan][:3] == ["st01", "st02", "st03"]
    south_demand = dict(plan)["st04"]
    assert south_demand < 60.0


def test_apply_mix_writes_station_state_to_store(tmp_path):
    config = default_config()
    station = HeatStation("st01", "north", config.station)
    valve = Valve("st01.mix", config.valve)
    durable = DurableState(JsonStore(str(tmp_path)))
    detail = apply_mix(station, valve, durable, 58.0, 1.0)
    assert detail["station"] == "st01"
    assert detail["valve_pct"] > 0.0
    assert durable.load("valve/st01.mix")["position_pct"] == pytest.approx(detail["valve_pct"])
    assert station.snapshot().as_dict()["target_c"] == pytest.approx(58.0)
