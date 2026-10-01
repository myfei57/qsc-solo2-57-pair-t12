"""阀门状态快照。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValveSnapshot:
    """一次阀门读取的结果。"""

    name: str
    position_pct: float
    target_pct: float
    moves: int
    settled: bool
    rejected: int

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "position_pct": round(self.position_pct, 2),
            "target_pct": round(self.target_pct, 2),
            "moves": self.moves,
            "settled": self.settled,
            "rejected": self.rejected,
        }
