"""二次网循环的收尾保证与水力平衡。"""

from __future__ import annotations

import pytest

from heatnet.config import default_config
from heatnet.pump.curve import PumpCurve
from heatnet.pump.pump import Pump
from heatnet.pump.start import start_pump_after_valve, stop_pump_before_valve
from heatnet.secondary.balance import hydraulic_balance
from heatnet.secondary.cycle import run_cycle
from heatnet.secondary.loop import SecondaryLoop
from heatnet.secondary.makeup import makeup_then_pressurise
from heatnet.store.jsonfile import JsonStore
from heatnet.store.state import DurableState
from heatnet.valve.valve import Valve


def _pump() -> Pump:
    config = default_config()
    baseline = config.primary.flow_baseline_t_h
    curve = PumpCurve(config.pump.min_speed_pct, config.pump.max_speed_pct, baseline * 0.25, baseline)
    return Pump("secondary.circulating", config.pump, curve)


def _loop() -> SecondaryLoop:
    return SecondaryLoop(default_config().secondary)


def test_hydraulic_balance_scales_with_flow_and_delta():
    report = hydraulic_balance(2000.0, 60.0, 45.0)
    assert report.delta_c == pytest.approx(15.0)
    assert report.load_kw == pytest.approx(2000.0 * 15.0 / 1.163)
    assert report.flow_ratio == pytest.approx(2000.0 / 2400.0)
    assert report.as_dict()["load_kw"] == pytest.approx(round(report.load_kw, 2))
    assert hydraulic_balance(0.0, 60.0, 45.0).load_kw == pytest.approx(0.0)


def test_cycle_stops_pump_even_on_success(tmp_path):
    loop = _loop()
    pump = _pump()
    valve = Valve("st01.mix", default_config().valve)
    durable = DurableState(JsonStore(str(tmp_path)))
    report = run_cycle(loop, pump, valve, durable, 1.0)
    assert report["ok"] is True
    assert report["pump_idle"] is True
    assert pump.idle() is True
    assert pump.running() is False
    assert durable.load("secondary/320")["running"] is False


def test_cycle_error_path_still_stops_pump(tmp_path):
    loop = _loop()
    pump = _pump()
    valve = Valve("st01.mix", default_config().valve)
    durable = DurableState(JsonStore(str(tmp_path)))
    loop.disturb(3.0)
    assert loop.overheat() is True
    report = run_cycle(loop, pump, valve, durable, 1.0)
    assert report["ok"] is False
    assert report["violations"] == ["return_overtemperature"]
    assert report["pump_idle"] is True
    assert pump.idle() is True
    assert pump.starts() == 1
    assert pump.stops() == 1


def test_makeup_runs_before_pressurising():
    loop = _loop()
    loop.bleed_pressure(loop.limits.makeup_min_kpa)
    assert loop.needs_makeup() is True
    report = makeup_then_pressurise(loop, 1.0)
    assert report["ok"] is True
    assert loop.needs_makeup() is False
    assert [step["action"] for step in report["steps"]] == ["makeup"]


def test_makeup_bleeds_when_overpressurised():
    loop = _loop()
    loop.add_pressure(200.0)
    assert loop.overpressure() is True
    report = makeup_then_pressurise(loop, 1.0)
    assert report["ok"] is True
    assert [step["action"] for step in report["steps"]] == ["makeup", "bleed"]
    assert loop.overpressure() is False


def test_pump_start_requires_settled_valve(tmp_path):
    config = default_config()
    valve = Valve("st01.mix", config.valve)
    durable = DurableState(JsonStore(str(tmp_path)))
    pump = _pump()
    report = start_pump_after_valve(valve, durable, pump, 60.0, 1.0)
    assert report["ok"] is True
    assert valve.at_target() is True
    assert pump.running() is True
    assert pump.target_flow_t_h() > 0.0

    stopped = stop_pump_before_valve(pump, valve, 1.0)
    assert stopped["ok"] is True
    assert pump.idle() is True
    assert valve.target_pct() == pytest.approx(0.0)
