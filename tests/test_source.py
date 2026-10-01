"""热源调质调量、气象推送与停机复位。"""

from __future__ import annotations

import threading

import pytest

from heatnet.config import default_config
from heatnet.errors import ForecastError, InterlockError
from heatnet.source.adjust import apply_adjustment
from heatnet.source.source import HeatSource
from heatnet.source.weather import WeatherPush, push_weather
from heatnet.temp.curve import HeatCurve


def _source() -> HeatSource:
    return HeatSource(default_config().source)


def _curve() -> HeatCurve:
    return HeatCurve(default_config().curve)


def test_adjust_writes_temperature_and_flow_together():
    source = _source()
    result = apply_adjustment(source, 90.0, 2000.0, "manual")
    assert result.ok is True
    assert result.temperature_c == pytest.approx(90.0)
    assert result.flow_t_h == pytest.approx(2000.0)
    snapshot = source.snapshot()
    assert snapshot.adjustments == 1
    assert snapshot.temperature_c == pytest.approx(90.0)


def test_invalid_adjustment_keeps_previous_state():
    source = _source()
    apply_adjustment(source, 90.0, 2000.0, "manual")
    rejected = apply_adjustment(source, 120.0, 2000.0, "manual")
    assert rejected.ok is False
    assert rejected.violations
    assert source.snapshot().temperature_c == pytest.approx(90.0)
    assert source.snapshot().flow_t_h == pytest.approx(2000.0)


def test_concurrent_adjust_never_tears_the_pair():
    source = _source()
    pairs = ((95.0, 2000.0), (85.0, 3000.0))
    seed = source.snapshot()
    allowed = set(pairs) | {(seed.temperature_c, seed.flow_t_h)}
    observed: list[tuple[float, float]] = []
    stop = threading.Event()

    def writer(temperature_c: float, flow_t_h: float) -> None:
        for _ in range(300):
            source.adjust(temperature_c, flow_t_h)

    def sampler() -> None:
        while not stop.is_set():
            snapshot = source.snapshot()
            observed.append((snapshot.temperature_c, snapshot.flow_t_h))

    watcher = threading.Thread(target=sampler)
    watcher.start()
    workers = [threading.Thread(target=writer, args=pair) for pair in pairs]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    stop.set()
    watcher.join()

    mixed = [pair for pair in observed if pair not in allowed]
    assert mixed == []


def test_quality_must_be_confirmed_before_quantity():
    source = _source()
    with pytest.raises(InterlockError):
        source.set_flow(1500.0)
    for _ in range(400):
        source.settle_quality(90.0, 1.0)
        if source.quality_confirmed():
            break
    assert source.quality_confirmed() is True
    assert source.set_flow(1500.0) == pytest.approx(1500.0)
    assert source.state() == "online"


def test_weather_push_updates_curve_and_fires_source():
    source = _source()
    curve = _curve()
    report = push_weather(source, curve, WeatherPush(-12.0, 1000.0), 1000.0)
    assert report["ok"] is True
    assert report["epoch"] == 1
    assert curve.outdoor_c() == pytest.approx(-12.0)
    assert source.target_c() == pytest.approx(curve.supply_c())
    assert [step["action"] for step in report["steps"]] == ["apply_forecast", "fire_forecast"]


def test_out_of_range_forecast_is_rejected_without_touching_curve():
    source = _source()
    curve = _curve()
    push_weather(source, curve, WeatherPush(-8.0, 1000.0), 1000.0)
    before_epoch = curve.epoch()
    before_supply = curve.supply_c()

    with pytest.raises(ForecastError):
        curve.validate(60.0)
    assert curve.rejected() == 1

    report = push_weather(source, curve, WeatherPush(60.0, 1100.0), 1100.0)
    assert report["ok"] is False
    assert curve.epoch() == before_epoch
    assert curve.supply_c() == pytest.approx(before_supply)
    assert "超出曲线适用区间" in report["violations"][0]


def test_trip_and_reset():
    source = _source()
    source.trip("overtemperature")
    assert source.state() == "tripped"
    assert source.trips() == 1
    with pytest.raises(InterlockError):
        source.adjust(90.0, 1200.0)
    with pytest.raises(InterlockError):
        source.fire(90.0)
    assert source.reset() == "idle"
    assert source.trip_reason() == ""
    with pytest.raises(InterlockError):
        source.reset()
