"""热量采集与总账汇总。

多个采集任务并发投递增量，全部落到 :class:`~heatnet.quota.meter.HeatMeter` 的
累加里；汇总只读表快照。采集端不做任何本地累加，避免"采集端丢一次、总账看不出来"。
"""

from __future__ import annotations

import threading

from .meter import HeatMeter


class QuotaAccumulator:
    """多表汇总。"""

    def __init__(self) -> None:
        self._meters: dict[str, HeatMeter] = {}
        self._lock = threading.RLock()
        self._collections = 0

    def register(self, meter: HeatMeter) -> HeatMeter:
        """登记一块热量表，重名即报错。"""

        with self._lock:
            if meter.name in self._meters:
                raise ValueError(f"热量表重名: {meter.name}")
            self._meters[meter.name] = meter
            return meter

    def meters(self) -> list[str]:
        """返回全部表名（排序后）。"""

        with self._lock:
            return sorted(self._meters)

    def get(self, name: str) -> HeatMeter:
        """按名取表。"""

        with self._lock:
            try:
                return self._meters[name]
            except KeyError as error:
                raise KeyError(f"未登记热量表: {name}") from error

    def collect(self, name: str, delta_mwh: float) -> float:
        """把一次采集增量投递给对应表。"""

        meter = self.get(name)
        reading = meter.add(delta_mwh)
        with self._lock:
            self._collections += 1
        return reading

    def collections(self) -> int:
        """返回累计采集次数。"""

        with self._lock:
            return self._collections

    def total_mwh(self) -> float:
        """返回全部表的累计热量之和。"""

        with self._lock:
            meters = list(self._meters.values())
        return sum(meter.total_mwh() for meter in meters)

    def wraps(self) -> int:
        """返回全部表的回绕次数之和。"""

        with self._lock:
            meters = list(self._meters.values())
        return sum(meter.wraps() for meter in meters)

    def describe(self) -> dict:
        """汇总各表读数，供状态快照读取。"""

        with self._lock:
            names = sorted(self._meters)
        return {
            "count": len(names),
            "collections": self._collections,
            "meters": {name: self._meters[name].snapshot().as_dict() for name in names},
        }
