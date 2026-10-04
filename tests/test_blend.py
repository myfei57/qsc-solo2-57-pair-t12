"""多源气象融合：选源、缺报、兜底切换、时序、预警与三方一致性。"""

from __future__ import annotations

import pytest

from heatnet.app import build_platform
from heatnet.clock import ManualClock
from heatnet.config import ConfigError, PlatformConfig, config_to_mapping, default_config
from heatnet.console.api import Api
from heatnet.errors import ForecastError
from heatnet.temp.blend import ForecastBlender


@pytest.fixture()
def blend_platform(tmp_path):
    clock = ManualClock()
    platform = build_platform(default_config(), clock=clock, storage_root=str(tmp_path / "state"))
    return platform, clock


def _ingest_all(platform, outdoor_c: float) -> list[dict]:
    return [platform.ingest_weather(name, outdoor_c) for name in platform.config.forecast.providers]


def test_trusted_providers_blend_to_median_and_stay_consistent(blend_platform):
    platform, _clock = blend_platform
    reports = [
        platform.ingest_weather("nmc", -8.0),
        platform.ingest_weather("cma-net", -7.6),
        platform.ingest_weather("local-tower", -8.4),
    ]
    assert all(item["ok"] for item in reports)
    last = reports[-1]
    assert last["mode"] == "live"
    assert last["outdoor_c"] == pytest.approx(-8.0)
    # 选源按"偏差小者优先、平手按源名"排名：cma-net 与 nmc 偏差并列，按名字字典序在前。
    assert last["point"]["trusted"] == ["cma-net", "nmc", "local-tower"]
    # 合成序列、曲线与审计三者一致：每个序列点对应一次曲线代际与一条审计事件。
    series = platform.blender.series()
    assert len(series) == 3
    assert platform.curve.outdoor_c() == pytest.approx(-8.0)
    assert platform.curve.epoch() == len(series)
    events = [entry for entry in platform.audit.entries(limit=100) if entry["action"] == "blend_point"]
    assert len(events) == len(series)
    assert events[0]["payload"]["seq"] == series[-1]["seq"]
    assert events[0]["payload"]["outdoor_c"] == pytest.approx(-8.0)


def test_deviating_provider_is_excluded_from_the_blend(blend_platform):
    platform, clock = blend_platform
    _ingest_all(platform, -8.0)
    clock.advance(60.0)
    report = platform.ingest_weather("nmc", 2.0)  # 飘了：与上一版偏差 10℃
    assert report["ok"] is True
    point = report["point"]
    assert point["mode"] == "live"
    assert point["excluded"] == {"nmc": "deviating"}
    assert point["outdoor_c"] == pytest.approx(-8.0)
    providers = {entry["provider"]: entry["state"] for entry in platform.blender.providers(clock.now())}
    assert providers["nmc"] == "deviating"
    assert providers["cma-net"] == "ok"


def test_missing_provider_is_partial_failure_not_blend_input(blend_platform):
    platform, clock = blend_platform
    _ingest_all(platform, -8.0)
    clock.advance(1000.0)  # 超过缺报周期 900s，两家没再报
    report = platform.ingest_weather("nmc", -9.0)
    point = report["point"]
    assert point["mode"] == "live"
    assert point["trusted"] == ["nmc"]
    assert point["excluded"] == {"cma-net": "missing", "local-tower": "missing"}
    assert point["outdoor_c"] == pytest.approx(-9.0)
    assert platform.curve.outdoor_c() == pytest.approx(-9.0)


def test_stale_issued_reading_is_excluded(blend_platform):
    platform, clock = blend_platform
    platform.ingest_weather("nmc", -8.0)
    clock.advance(1900.0)
    # 签发时刻落在新鲜度窗口之外，但晚于上一决策点，时序上允许登记。
    report = platform.ingest_weather("cma-net", -8.2, issued_at=clock.now() - 1850.0)
    point = report["point"]
    assert point["mode"] == "hold"
    assert point["excluded"]["cma-net"] == "stale"
    assert point["excluded"]["nmc"] == "missing"
    assert point["outdoor_c"] == pytest.approx(-8.0)


def test_all_untrusted_holds_then_switches_to_fallback_by_elapsed_time(blend_platform):
    platform, clock = blend_platform
    _ingest_all(platform, -8.0)
    good_at = clock.now()
    # 全断 1000s：过了缺报周期，但还在撑着窗口内 → 按上一版撑着。
    first = platform.cycle(dt=1000.0)
    assert first["blend"]["mode"] == "hold"
    assert first["blend"]["outdoor_c"] == pytest.approx(-8.0)
    assert platform.curve.outdoor_c() == pytest.approx(-8.0)
    # 全断超过 hold_after_s → 切保守经验曲线，取值与日变化模型一致。
    second = platform.cycle(dt=2700.0)
    assert second["blend"]["mode"] == "fallback"
    expected = round(platform.blender.empirical_outdoor_c(clock.now()), 2)
    assert second["blend"]["outdoor_c"] == pytest.approx(expected)
    assert clock.now() - good_at > platform.config.forecast.hold_after_s
    # 切换与合成共用一条时序：序号连续、时刻单调。
    series = platform.blender.series()
    assert [point["seq"] for point in series] == list(range(1, len(series) + 1))
    times = [point["decided_at"] for point in series]
    assert times == sorted(times)
    modes = [point["mode"] for point in series]
    assert modes == ["live", "live", "live", "hold", "fallback"]


def test_provider_recovery_returns_to_live(blend_platform):
    platform, clock = blend_platform
    _ingest_all(platform, -8.0)
    platform.cycle(dt=1000.0)
    platform.cycle(dt=2700.0)
    assert platform.blend_report()["mode"] == "fallback"
    report = platform.ingest_weather("cma-net", -7.0)
    assert report["mode"] == "live"
    assert report["point"]["trusted"] == ["cma-net"]
    assert platform.curve.outdoor_c() == pytest.approx(-7.0)


def test_out_of_order_push_is_rejected_without_touching_series(blend_platform):
    platform, clock = blend_platform
    platform.ingest_weather("nmc", -8.0)
    before = len(platform.blender.series())
    stale = platform.ingest_weather("nmc", -9.0, issued_at=clock.now() - 10.0)
    assert stale["ok"] is False
    assert stale["ingest"]["accepted"] is False
    assert stale["ingest"]["reason"] == "out_of_order"
    assert len(platform.blender.series()) == before
    duplicate = platform.ingest_weather("cma-net", -8.1, issued_at=clock.now())
    assert duplicate["ok"] is True  # cma-net 首报，与 nmc 的时序互不干扰
    clock.advance(1.0)
    again = platform.ingest_weather("nmc", -9.0)
    assert again["ok"] is True


def test_curve_rejection_rolls_back_series_point(blend_platform):
    platform, clock = blend_platform
    report = platform.ingest_weather("nmc", 60.0)  # 超出曲线适用区间
    assert report["ok"] is False
    assert "超出曲线适用区间" in report["violations"][0]
    assert platform.blender.series() == []
    assert platform.curve.epoch() == 0
    assert [entry for entry in platform.audit.entries(limit=50) if entry["action"] == "blend_point"] == []
    clock.advance(1.0)
    good = platform.ingest_weather("nmc", -8.0)
    assert good["ok"] is True
    assert platform.curve.outdoor_c() == pytest.approx(-8.0)
    assert platform.curve.epoch() == 1


def test_cooling_trend_raises_cold_warning_with_supply_tiers(blend_platform):
    platform, clock = blend_platform
    _ingest_all(platform, -4.0)
    clock.advance(600.0)
    reports = _ingest_all(platform, -8.0)
    assert any(item["warning"] for item in reports)
    warnings = [entry for entry in platform.audit.entries(limit=100) if entry["action"] == "cold_warning"]
    assert warnings
    assert warnings[0]["severity"] == "warning"
    payload = warnings[0]["payload"]
    assert payload["projected_outdoor_c"] < -8.0
    tiers = payload["tiers"]
    assert len(tiers) == 5
    supplies = [tier["supply_c"] for tier in tiers]
    assert supplies == sorted(supplies)  # 越冷供温越高
    assert tiers[-1]["outdoor_c"] < tiers[0]["outdoor_c"]


def test_console_blend_endpoints_and_audit_trail(blend_platform):
    platform, _clock = blend_platform
    api = Api(platform)
    for index, name in enumerate(platform.config.forecast.providers):
        status, payload = api.handle(
            "POST", "/api/blend/ingest", {}, {"provider": name, "outdoor_c": -8.0 - 0.1 * index}
        )
        assert status == 200
        assert payload["ok"] is True
    status, report = api.handle("GET", "/api/blend", {}, {})
    assert status == 200
    assert report["mode"] == "live"
    assert len(report["providers"]) == 3
    assert report["series"]
    assert report["curve"]["epoch"] == len(report["series"])
    status, _payload = api.handle("POST", "/api/blend/ingest", {}, {"provider": "nobody", "outdoor_c": -5.0})
    assert status == 409


def test_status_exposes_blend_section(blend_platform):
    platform, _clock = blend_platform
    platform.ingest_weather("nmc", -8.0)
    status = platform.status()
    assert status["blend"]["mode"] == "live"
    assert status["blend"]["last_point"]["outdoor_c"] == pytest.approx(-8.0)


def test_unknown_provider_is_rejected():
    blender = ForecastBlender(default_config().forecast)
    with pytest.raises(ForecastError):
        blender.ingest("nobody", -8.0, 1000.0, 1000.0)


def test_fallback_envelope_must_stay_inside_curve_range():
    mapping = config_to_mapping(default_config())
    mapping["limits"]["forecast"]["fallback_mean_c"] = 40.0
    with pytest.raises(ConfigError):
        PlatformConfig.from_mapping(mapping)
