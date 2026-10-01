"""一次网状态快照。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkSnapshot:
    """一次一次网读取的结果。"""

    supply_c: float
    return_c: float
    flow_t_h: float
    baseline_t_h: float
    threshold_t_h: float
    low_flow: bool
    recalibrations: int
    dispatches: int

    def as_dict(self) -> dict:
        return {
            "supply_c": round(self.supply_c, 2),
            "return_c": round(self.return_c, 2),
            "flow_t_h": round(self.flow_t_h, 2),
            "baseline_t_h": round(self.baseline_t_h, 2),
            "threshold_t_h": round(self.threshold_t_h, 2),
            "low_flow": self.low_flow,
            "recalibrations": self.recalibrations,
            "dispatches": self.dispatches,
        }
