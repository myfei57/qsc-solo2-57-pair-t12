"""换热站状态快照。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StationSnapshot:
    """一次换热站读取的结果。"""

    name: str
    zone: str
    supply_c: float
    target_c: float
    demand_pct: float
    steps: int
    at_setpoint: bool

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "zone": self.zone,
            "supply_c": round(self.supply_c, 2),
            "target_c": round(self.target_c, 2),
            "demand_pct": round(self.demand_pct, 2),
            "steps": self.steps,
            "at_setpoint": self.at_setpoint,
        }
