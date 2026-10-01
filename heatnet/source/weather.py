"""气象推送与按曲线点火。

气象推送先更新供热曲线，再让热源按新曲线点火。曲线校验失败时必须整条推送作废：
吞掉校验错误继续点火，热源会按上一版（甚至过期）的曲线运行，室外温度越冷反而
供温越低。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import PlantError
from ..temp.curve import HeatCurve
from .source import HeatSource


@dataclass(frozen=True)
class WeatherPush:
    """一次气象推送。"""

    outdoor_c: float
    issued_at: float
    station: str = "weather-center"

    def as_dict(self) -> dict:
        return {
            "outdoor_c": round(self.outdoor_c, 2),
            "issued_at": round(self.issued_at, 3),
            "station": self.station,
        }


def push_weather(source: HeatSource, curve: HeatCurve, push: WeatherPush, now: float) -> dict:
    """按气象推送更新曲线并让热源点火。"""

    steps: list[dict] = []
    violations: list[str] = []

    try:
        forecast = curve.apply_forecast(push.outdoor_c, now)
    except PlantError as error:
        return {
            "ok": False,
            "steps": steps,
            "violations": [error.message],
            "outdoor_c": round(float(push.outdoor_c), 2),
        }
    steps.append({"component": "temp", "action": "apply_forecast", "detail": forecast})

    if curve.is_stale(now):
        violations.append("curve_stale")
        return {"ok": False, "steps": steps, "violations": violations, "outdoor_c": forecast["outdoor_c"]}

    try:
        fired = source.fire(curve.supply_c())
    except PlantError as error:
        violations.append(error.message)
        return {"ok": False, "steps": steps, "violations": violations, "outdoor_c": forecast["outdoor_c"]}
    steps.append({"component": "source", "action": "fire_forecast", "detail": {"temperature_c": round(fired, 2)}})

    return {
        "ok": not violations,
        "steps": steps,
        "violations": violations,
        "outdoor_c": forecast["outdoor_c"],
        "supply_c": round(curve.supply_c(), 2),
        "epoch": curve.epoch(),
    }
