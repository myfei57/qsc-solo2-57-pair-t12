"""循环泵状态快照。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PumpSnapshot:
    """一次循环泵读取的结果。"""

    name: str
    running: bool
    speed_pct: float
    flow_t_h: float
    target_flow_t_h: float
    starts: int
    stops: int

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "running": self.running,
            "speed_pct": round(self.speed_pct, 2),
            "flow_t_h": round(self.flow_t_h, 2),
            "target_flow_t_h": round(self.target_flow_t_h, 2),
            "starts": self.starts,
            "stops": self.stops,
        }
