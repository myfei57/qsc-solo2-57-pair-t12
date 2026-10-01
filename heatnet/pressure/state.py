"""定压基线状态快照。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PressureSnapshot:
    """一次定压基线读取的结果。"""

    baseline_kpa: float
    revisions: int
    rejected: int
    last_target_kpa: float
    in_range: bool

    def as_dict(self) -> dict:
        return {
            "baseline_kpa": round(self.baseline_kpa, 2),
            "revisions": self.revisions,
            "rejected": self.rejected,
            "last_target_kpa": round(self.last_target_kpa, 2),
            "in_range": self.in_range,
        }
