"""热量表。

表读数到顶后回绕，因此同时维护"当前读数"和"累计热量"：前者是现场表头，后者是
结算用的总量。累加必须原子——``self._reading += delta`` 在多线程下会读改写交错，
丢掉的增量既不在表头也不在总量里。
"""

from __future__ import annotations

import threading

from .state import MeterSnapshot


class HeatMeter:
    """一块带回绕的热量表。"""

    def __init__(self, name: str, wrap_mwh: float) -> None:
        if wrap_mwh <= 0:
            raise ValueError("回绕阈值必须为正")
        self._name = name
        self._wrap_mwh = float(wrap_mwh)
        self._reading_mwh = 0.0
        self._total_mwh = 0.0
        self._wraps = 0
        self._increments = 0
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._name

    @property
    def wrap_mwh(self) -> float:
        return self._wrap_mwh

    def add(self, delta_mwh: float) -> float:
        """原子累加一次热量增量，返回累加后的表头读数。"""

        delta = float(delta_mwh)
        with self._lock:
            if delta < 0:
                raise ValueError("热量增量不能为负")
            self._reading_mwh += delta
            self._total_mwh += delta
            self._increments += 1
            while self._reading_mwh >= self._wrap_mwh:
                self._reading_mwh -= self._wrap_mwh
                self._wraps += 1
            return self._reading_mwh

    def reading_mwh(self) -> float:
        """返回表头读数（已回绕）。"""

        with self._lock:
            return self._reading_mwh

    def total_mwh(self) -> float:
        """返回累计热量（未回绕）。"""

        with self._lock:
            return self._total_mwh

    def wraps(self) -> int:
        """返回累计回绕次数。"""

        with self._lock:
            return self._wraps

    def increments(self) -> int:
        """返回累计累加次数。"""

        with self._lock:
            return self._increments

    def reset(self) -> None:
        """把表头与总量清零（结算周期切换时使用）。"""

        with self._lock:
            self._reading_mwh = 0.0
            self._total_mwh = 0.0
            self._wraps = 0
            self._increments = 0

    def snapshot(self) -> MeterSnapshot:
        """返回热量表状态快照，读数与总量在同一把锁里一起取。"""

        with self._lock:
            return MeterSnapshot(
                name=self._name,
                reading_mwh=self._reading_mwh,
                total_mwh=self._total_mwh,
                wraps=self._wraps,
                increments=self._increments,
            )
