"""供热配额总账。

配额按结算周期把累计热量分到各换热站，周期结束时结清。总账只保存"站 → 热量"，
不参与采集，避免采集与结算共用同一份可变状态。
"""

from __future__ import annotations

from ..config import QuotaLimits
from .accumulator import QuotaAccumulator
from .state import QuotaSnapshot


class QuotaLedger:
    """供热配额总账。"""

    def __init__(self, limits: QuotaLimits, accumulator: QuotaAccumulator) -> None:
        self._limits = limits
        self._accumulator = accumulator
        self._allocations: dict[str, float] = {}
        self._periods = 0

    @property
    def limits(self) -> QuotaLimits:
        return self._limits

    @property
    def accumulator(self) -> QuotaAccumulator:
        return self._accumulator

    def allocate(self, station: str, mwh: float) -> float:
        """把一个站的热量记进本期总账。"""

        value = max(0.0, float(mwh))
        self._allocations[station] = self._allocations.get(station, 0.0) + value
        return self._allocations[station]

    def allocated_mwh(self, station: str) -> float:
        """返回某站本期累计热量。"""

        return self._allocations.get(station, 0.0)

    def stations(self) -> list[str]:
        """返回本期出现过的站名（排序后）。"""

        return sorted(self._allocations)

    def periods(self) -> int:
        """返回累计结算周期数。"""

        return self._periods

    def total_mwh(self) -> float:
        """返回本期总热量（分站分配有记录时取两者中更保守的一个）。"""

        collected = self._accumulator.total_mwh()
        allocated = sum(self._allocations.values())
        return min(collected, allocated) if allocated else collected

    def settle(self) -> dict:
        """结束本期：累计周期数并返回结算摘要。"""

        self._periods += 1
        payload = {
            "period": self._periods,
            "hours": self._limits.period_hours,
            "total_mwh": round(self.total_mwh(), 4),
            "stations": {name: round(value, 4) for name, value in sorted(self._allocations.items())},
        }
        self._allocations = {}
        return payload

    def snapshot(self) -> QuotaSnapshot:
        """返回配额总账状态快照。"""

        return QuotaSnapshot(
            total_mwh=self.total_mwh(),
            meters=len(self._accumulator.meters()),
            wraps=self._accumulator.wraps(),
            stations=len(self._allocations),
            period_hours=self._limits.period_hours,
        )
