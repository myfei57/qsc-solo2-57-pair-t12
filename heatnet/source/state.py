"""热源状态快照。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSnapshot:
    """一次热源状态读取的结果。"""

    state: str
    temperature_c: float
    flow_t_h: float
    target_c: float
    quality_hold_s: float
    adjustments: int
    trip_reason: str

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "temperature_c": round(self.temperature_c, 2),
            "flow_t_h": round(self.flow_t_h, 2),
            "target_c": round(self.target_c, 2),
            "quality_hold_s": round(self.quality_hold_s, 3),
            "adjustments": self.adjustments,
            "trip_reason": self.trip_reason,
        }
