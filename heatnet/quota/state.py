"""热量表与配额状态快照。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MeterSnapshot:
    """一次热量表读取的结果。"""

    name: str
    reading_mwh: float
    total_mwh: float
    wraps: int
    increments: int

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "reading_mwh": round(self.reading_mwh, 4),
            "total_mwh": round(self.total_mwh, 4),
            "wraps": self.wraps,
            "increments": self.increments,
        }


@dataclass(frozen=True)
class QuotaSnapshot:
    """一次配额总账读取的结果。"""

    total_mwh: float
    meters: int
    wraps: int
    stations: int
    period_hours: float

    def as_dict(self) -> dict:
        return {
            "total_mwh": round(self.total_mwh, 4),
            "meters": self.meters,
            "wraps": self.wraps,
            "stations": self.stations,
            "period_hours": self.period_hours,
        }
