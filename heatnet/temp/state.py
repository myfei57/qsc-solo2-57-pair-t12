"""供热曲线状态快照。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CurveSnapshot:
    """一次曲线读取的结果。"""

    outdoor_c: float
    supply_c: float
    epoch: int
    updated_at: float
    stale: bool
    validated: int
    rejected: int

    def as_dict(self) -> dict:
        return {
            "outdoor_c": round(self.outdoor_c, 2),
            "supply_c": round(self.supply_c, 2),
            "epoch": self.epoch,
            "updated_at": round(self.updated_at, 3),
            "stale": self.stale,
            "validated": self.validated,
            "rejected": self.rejected,
        }
