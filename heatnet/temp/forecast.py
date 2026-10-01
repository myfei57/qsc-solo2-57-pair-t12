"""曲线外推预估。

值班员关心的是"再冷几度，供温要到多少"，因此这里按等步长外推一串室外温度，
逐个过一遍曲线表，给出未来若干档的目标供温。外推只读曲线表，不改曲线本身，
也不会写审计。
"""

from __future__ import annotations

from dataclasses import dataclass

from .table import CurveTable


@dataclass(frozen=True)
class ForecastPoint:
    """一档预估结果。"""

    step: int
    outdoor_c: float
    supply_c: float

    def as_dict(self) -> dict:
        return {"step": self.step, "outdoor_c": round(self.outdoor_c, 2), "supply_c": round(self.supply_c, 2)}


def build_forecast(
    table: CurveTable,
    start_outdoor_c: float,
    drop_c: float = 2.0,
    steps: int = 5,
) -> list[ForecastPoint]:
    """按等步长降温外推一批供温档位。"""

    if steps < 1:
        raise ValueError("外推档数必须为正")
    points: list[ForecastPoint] = []
    for index in range(steps):
        outdoor = float(start_outdoor_c) - drop_c * index
        points.append(ForecastPoint(index, outdoor, table.interpolate(outdoor)))
    return points


def describe_forecast(points: list[ForecastPoint]) -> dict:
    """把预估结果折成控制台直接可读的一份摘要。"""

    if not points:
        return {"count": 0, "points": [], "max_supply_c": None}
    supplies = [point.supply_c for point in points]
    return {
        "count": len(points),
        "points": [point.as_dict() for point in points],
        "max_supply_c": round(max(supplies), 2),
        "min_supply_c": round(min(supplies), 2),
    }
