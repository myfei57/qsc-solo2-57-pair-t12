"""多源气象合成：选源定规、缺报部分失败、按时段兜底、时序与降温预警。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from heatnet.config import default_config, load_config
from heatnet.console.api import Api
from heatnet.source.fusion import (
    MODE_CONSERVATIVE,
    MODE_FUSED,
    MODE_HOLD,
    ProviderReport,
    WeatherFusion,
    push_fused_weather,
)
from heatnet.source.source import HeatSource
from heatnet.temp.curve import HeatCurve


def _parts():
    config = default_config()
    return (
        config,
        HeatSource(config.source),
        HeatCurve(config.curve),
        WeatherFusion(config.fusion, config.curve),
    )


def _reports(now: float, base: float = -8.0) -> list[ProviderReport]:
    return [
        ProviderReport("nmc", base - 0.4, now),
        ProviderReport("ecmwf", base + 0.3, now),
        ProviderReport("local", base, now),
    ]


def _advance_to_hour(clock, hour: int) -> float:
    """把可推进时钟拨到指定的 UTC 小时（兜底时段按 UTC 小时判定）。"""

    current = int((clock.now() // 3600) % 24)
    clock.advance(((hour - current) % 24) * 3600)
    return clock.now()


def test_fused_round_weights_trusted_providers():
    config, source, curve, fusion = _parts()
    now = 1_758_000_000.0
    report = push_fused_weather(source, curve, fusion, _reports(now), now)
    assert report["ok"] is True
    assert report["mode"] == MODE_FUSED
    # 三家都在偏差带内：按偏差平方反比加权，结果靠近中位数 -8.0。
    assert report["outdoor_c"] == pytest.approx(-8.03, abs=0.05)
    # 合成序列、曲线与审计用的是同一份值（报告与序列保留两位小数）。
    assert curve.outdoor_c() == pytest.approx(report["outdoor_c"], abs=0.01)
    assert fusion.series()[-1]["outdoor_c"] == report["outdoor_c"]
    assert report["fusion_epoch"] == 1
    assert curve.epoch() == 1
    assert report["partial"] is False


def test_divergent_reading_is_excluded_not_averaged():
    config, source, curve, fusion = _parts()
    now = 1_758_000_000.0
    reports = [
        ProviderReport("nmc", -8.0, now),
        ProviderReport("ecmwf", -8.5, now),
        ProviderReport("local", 17.0, now),  # 飘了但在曲线适用区间内
    ]
    report = push_fused_weather(source, curve, fusion, reports, now)
    assert report["ok"] is True
    assert report["mode"] == MODE_FUSED
    # 野值被剔除，合成只取 -8.0 与 -8.5 两家。
    assert report["outdoor_c"] == pytest.approx(-8.22, abs=0.05)
    decision = report["decision"]
    assert set(decision["trusted"]) == {"nmc", "ecmwf"}
    assert {item["provider"]: item["reason"] for item in decision["excluded"]} == {
        "local": "divergent"
    }
    assert decision["partial"] is True


def test_missing_provider_is_partial_failure_and_not_fused():
    config, source, curve, fusion = _parts()
    now = 1_758_000_000.0
    reports = [ProviderReport("nmc", -8.0, now), ProviderReport("ecmwf", -8.3, now)]
    report = push_fused_weather(source, curve, fusion, reports, now)
    assert report["ok"] is True
    assert report["mode"] == MODE_FUSED
    decision = report["decision"]
    assert decision["missing"] == ["local"]
    assert decision["partial"] is True
    # 缺报只记健康度，不估值补位：合成只来自到报的两家。
    assert report["outdoor_c"] == pytest.approx(-8.15, abs=0.05)
    health = {item["provider"]: item for item in fusion.health()}
    assert health["local"]["missing"] == 1
    assert health["local"]["received"] == 0


def test_stale_report_fails_freshness_gate_even_if_close():
    config, source, curve, fusion = _parts()
    now = 1_758_000_000.0
    reports = [
        ProviderReport("nmc", -8.0, now - config.fusion.fresh_after_s - 1.0),
        ProviderReport("ecmwf", -8.2, now),
        ProviderReport("local", -8.1, now),
    ]
    report = push_fused_weather(source, curve, fusion, reports, now)
    decision = report["decision"]
    assert {item["provider"]: item["reason"] for item in decision["excluded"]} == {
        "nmc": "stale"
    }
    assert set(decision["trusted"]) == {"ecmwf", "local"}


def test_all_untrusted_uses_conservative_curve_during_conservative_hours(platform):
    # 可推进时钟起点落在保守时段（UTC 5 点，默认保守时段 22..5）。
    now = platform.clock.now()
    stale = now - platform.config.fusion.fresh_after_s - 10.0
    report = platform.fuse_weather(
        [
            ProviderReport("nmc", -8.0, stale),
            ProviderReport("ecmwf", -9.0, stale),
            ProviderReport("local", -7.0, stale),
        ]
    )
    assert report["ok"] is True
    assert report["mode"] == MODE_CONSERVATIVE
    expected = platform.config.curve.outdoor_min_c + platform.config.fusion.conservative_margin_c
    assert report["outdoor_c"] == pytest.approx(expected)
    assert platform.curve.outdoor_c() == pytest.approx(expected)


def test_all_untrusted_holds_last_value_outside_conservative_hours(platform):
    good = platform.fuse_weather(_reports(platform.clock.now()))
    assert good["mode"] == MODE_FUSED
    _advance_to_hour(platform.clock, 12)
    stale = platform.clock.now() - platform.config.fusion.fresh_after_s - 10.0
    report = platform.fuse_weather(
        [
            ProviderReport("nmc", -20.0, stale),
            ProviderReport("ecmwf", -21.0, stale),
            ProviderReport("local", -19.0, stale),
        ]
    )
    assert report["ok"] is True
    assert report["mode"] == MODE_HOLD
    assert report["outdoor_c"] == pytest.approx(good["outdoor_c"])
    assert platform.curve.outdoor_c() == pytest.approx(good["outdoor_c"], abs=0.01)


def test_all_untrusted_without_previous_value_falls_back_to_conservative(platform):
    _advance_to_hour(platform.clock, 12)
    stale = platform.clock.now() - platform.config.fusion.fresh_after_s - 10.0
    report = platform.fuse_weather([ProviderReport("nmc", -8.0, stale)])
    assert report["mode"] == MODE_CONSERVATIVE
    assert report["decision"]["fallback_reason"] == "no_previous_value"


def test_late_report_cannot_regress_the_series(platform):
    now = platform.clock.now()
    first = platform.fuse_weather(_reports(now))
    assert first["mode"] == MODE_FUSED
    platform.clock.advance(60.0)
    # nmc 重发上一帧（签发时刻不比已应用版本新），按迟到剔除。
    reports = [
        ProviderReport("nmc", -20.0, now),
        ProviderReport("ecmwf", -8.6, platform.clock.now()),
        ProviderReport("local", -8.4, platform.clock.now()),
    ]
    report = platform.fuse_weather(reports)
    decision = report["decision"]
    assert {item["provider"]: item["reason"] for item in decision["excluded"]} == {
        "nmc": "late"
    }
    series = platform.fusion.series()
    assert [point["epoch"] for point in series] == sorted(point["epoch"] for point in series)
    assert all(point["outdoor_c"] > -20.0 for point in series)


def test_cooling_trend_raises_alert_with_supply_tier(platform):
    horizon = platform.config.fusion.alert_horizon_s
    first = platform.fuse_weather(_reports(platform.clock.now(), base=-4.0))
    assert first["alert"] is None
    platform.clock.advance(horizon / 2.0)
    second = platform.fuse_weather(_reports(platform.clock.now(), base=-9.0))
    alert = second["alert"]
    assert alert is not None
    assert alert["kind"] == "cooling_trend"
    assert alert["drop_c"] >= platform.config.fusion.alert_drop_c
    # 越冷供温档越高：预警给出的目标供温必须高于当前供温。
    assert alert["supply_target_c"] > alert["supply_now_c"]
    entries = platform.audit.entries(limit=50)
    alerts = [entry for entry in entries if entry["action"] == "cooling_alert"]
    assert alerts and alerts[0]["severity"] == "warning"


def test_fusion_curve_and_audit_stay_consistent(platform):
    now = platform.clock.now()
    report = platform.fuse_weather(
        [ProviderReport("nmc", -8.0, now), ProviderReport("ecmwf", -8.2, now)]
    )
    assert report["ok"] is True
    assert report["partial"] is True
    series = platform.fusion.series()
    assert series[-1]["outdoor_c"] == pytest.approx(platform.curve.outdoor_c())
    entries = platform.audit.entries(limit=50)
    applied = [entry for entry in entries if entry["action"] == "apply_forecast"]
    assert applied and applied[0]["payload"]["outdoor_c"] == pytest.approx(
        platform.curve.outdoor_c()
    )
    missing = [entry for entry in entries if entry["action"] == "provider_missing"]
    assert [entry["payload"]["provider"] for entry in missing] == ["local"]
    assert missing[0]["severity"] == "warning"


def test_fusion_status_exposes_rules_health_and_series(platform):
    platform.fuse_weather(_reports(platform.clock.now()))
    api = Api(platform)
    status, payload = api.handle("GET", "/api/weather/fusion", {}, {})
    assert status == 200
    assert payload["rules"]["selection"] == "freshness_gate_then_deviation_weight"
    assert payload["rules"]["min_providers"] == platform.config.fusion.min_providers
    assert len(payload["providers"]) == len(platform.config.fusion.providers)
    assert len(payload["series"]) == 1
    assert payload["last"]["mode"] == MODE_FUSED


def test_console_posts_fusion_round_and_validates_body(platform):
    api = Api(platform)
    now = platform.clock.now()
    status, payload = api.handle(
        "POST",
        "/api/weather/fusion",
        {},
        {
            "reports": [
                {"provider": "nmc", "outdoor_c": -8.0, "issued_at": now},
                {"provider": "ecmwf", "outdoor_c": -8.2, "issued_at": now},
            ]
        },
    )
    assert status == 200
    assert payload["ok"] is True
    assert payload["mode"] == MODE_FUSED
    assert payload["decision"]["missing"] == ["local"]

    status, bad = api.handle("POST", "/api/weather/fusion", {}, {"reports": []})
    assert status == 400
    status, bad = api.handle(
        "POST", "/api/weather/fusion", {}, {"reports": [{"provider": "nmc"}]}
    )
    assert status == 400


def test_repo_config_carries_fusion_section():
    path = Path(__file__).resolve().parents[1] / "config" / "heatnet.json"
    config = load_config(str(path))
    assert config.fusion.providers == default_config().fusion.providers
    assert config.fusion.min_providers == default_config().fusion.min_providers
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "fusion" in raw["limits"]
