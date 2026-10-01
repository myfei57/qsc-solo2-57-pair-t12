"""二次网状态快照。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SecondarySnapshot:
    """一次二次网读取的结果。"""

    supply_c: float
    return_c: float
    delta_c: float
    pressure_kpa: float
    margin_to_min_kpa: float
    overpressure: bool
    steps: int
    disturbances: int

    def as_dict(self) -> dict:
        return {
            "supply_c": round(self.supply_c, 2),
            "return_c": round(self.return_c, 2),
            "delta_c": round(self.delta_c, 2),
            "pressure_kpa": round(self.pressure_kpa, 2),
            "margin_to_min_kpa": round(self.margin_to_min_kpa, 2),
            "overpressure": self.overpressure,
            "steps": self.steps,
            "disturbances": self.disturbances,
        }
