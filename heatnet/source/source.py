"""热源状态机与调质调量。

温度与流量是同一台机组的一次调质结果，任何一次调整都必须把两个字段当成一个
整体写入：并发的气象自动推送和人工调节同时改这两个字段时，只要中间态能被读到，
下游一次网就会拿到"上一次的温度配这一次的流量"。:meth:`HeatSource.adjust` 在
同一把可重入锁里写完两个字段，读方法也在同一把锁里取快照。
"""

from __future__ import annotations

import threading

from ..config import SourceLimits
from ..errors import InterlockError
from .state import SourceSnapshot

IDLE = "idle"
QUALITY = "quality"
QUANTITY = "quantity"
ONLINE = "online"
TRIPPED = "tripped"


class HeatSource:
    """热源：调质、调量与在线状态。"""

    def __init__(self, limits: SourceLimits) -> None:
        self._limits = limits
        self._guard = threading.RLock()
        self._state = IDLE
        self._temperature_c = limits.return_min_c
        self._flow_t_h = 0.0
        self._target_c = limits.supply_target_c
        self._quality_hold_s = 0.0
        self._adjustments = 0
        self._trip_reason = ""
        self._trips = 0

    @property
    def limits(self) -> SourceLimits:
        return self._limits

    def state(self) -> str:
        """返回当前状态。"""

        with self._guard:
            return self._state

    def temperature_c(self) -> float:
        """返回一次网供水温度。"""

        with self._guard:
            return self._temperature_c

    def flow_t_h(self) -> float:
        """返回一次网循环流量。"""

        with self._guard:
            return self._flow_t_h

    def target_c(self) -> float:
        """返回当前调质目标温度。"""

        with self._guard:
            return self._target_c

    def quality_hold_s(self) -> float:
        """返回调质累计确认时间。"""

        with self._guard:
            return self._quality_hold_s

    def adjustments(self) -> int:
        """返回累计调整次数。"""

        with self._guard:
            return self._adjustments

    def trip_reason(self) -> str:
        """返回最近一次停机原因。"""

        with self._guard:
            return self._trip_reason

    def trips(self) -> int:
        """返回累计停机次数。"""

        with self._guard:
            return self._trips

    def set_target(self, temperature_c: float) -> float:
        """设定调质目标温度（越界即拒绝）。"""

        with self._guard:
            value = float(temperature_c)
            if value >= self._limits.supply_max_c:
                raise InterlockError("调质目标越上限", component="source")
            if value < self._limits.return_min_c:
                raise InterlockError("调质目标低于回水下限", component="source")
            self._target_c = value
            return self._target_c

    def adjust(self, temperature_c: float, flow_t_h: float) -> tuple[float, float]:
        """把温度与流量作为一个整体一次写入，返回写后的二元组。"""

        with self._guard:
            if self._state == TRIPPED:
                raise InterlockError(f"热源已停机（{self._trip_reason}），禁止调整", component="source")
            temperature = float(temperature_c)
            flow = float(flow_t_h)
            if self._limits.overtemperature(temperature):
                raise InterlockError("调整后的供温越上限", component="source")
            if not self._limits.flow_in_range(flow):
                raise InterlockError("调整后的流量越界", component="source")
            self._temperature_c = temperature
            self._flow_t_h = flow
            self._adjustments += 1
            return self._temperature_c, self._flow_t_h

    def settle_quality(self, target_c: float, dt: float) -> float:
        """向目标温度逼近一个步长，返回逼近后的温度。"""

        if dt <= 0:
            raise ValueError("步长必须为正")
        with self._guard:
            if self._state == TRIPPED:
                raise InterlockError(f"热源已停机（{self._trip_reason}），禁止调质", component="source")
            self._target_c = float(target_c)
            step = self._limits.adjust_rate_c_s * dt
            delta = self._target_c - self._temperature_c
            if abs(delta) <= step:
                self._temperature_c = self._target_c
                self._quality_hold_s += dt
            else:
                self._temperature_c += step if delta > 0 else -step
                self._quality_hold_s = 0.0
            if self._quality_hold_s < self._limits.quality_confirm_s:
                self._state = QUALITY
            elif self._state != ONLINE:
                self._state = QUANTITY
            return self._temperature_c

    def quality_confirmed(self) -> bool:
        """调质是否已确认（供调量放行）。"""

        with self._guard:
            return self._quality_hold_s >= self._limits.quality_confirm_s

    def set_flow(self, flow_t_h: float) -> float:
        """在调质确认之后调量。"""

        with self._guard:
            if self._state == TRIPPED:
                raise InterlockError(f"热源已停机（{self._trip_reason}），禁止调量", component="source")
            if not self.quality_confirmed():
                raise InterlockError("调质未确认，禁止调量", component="source")
            value = float(flow_t_h)
            if not self._limits.flow_in_range(value):
                raise InterlockError("调量目标越界", component="source")
            self._flow_t_h = value
            self._state = ONLINE
            return self._flow_t_h

    def fire(self, supply_c: float) -> float:
        """按供热曲线点火：把曲线给出的供水温度写入调质目标。"""

        with self._guard:
            if self._state == TRIPPED:
                raise InterlockError(f"热源已停机（{self._trip_reason}），禁止点火", component="source")
            value = float(supply_c)
            if self._limits.overtemperature(value):
                raise InterlockError("曲线供温越上限，拒绝点火", component="source")
            self._target_c = value
            self._temperature_c = value
            self._state = QUANTITY if self.quality_confirmed() else QUALITY
            return self._temperature_c

    def trip(self, reason: str) -> str:
        """停机并记录原因。"""

        with self._guard:
            self._state = TRIPPED
            self._trip_reason = str(reason)
            self._trips += 1
            self._flow_t_h = 0.0
            return self._state

    def reset(self) -> str:
        """复位停机状态。"""

        with self._guard:
            if self._state != TRIPPED:
                raise InterlockError("热源未停机，无需复位", component="source")
            self._trip_reason = ""
            self._quality_hold_s = 0.0
            self._state = IDLE
            return self._state

    def snapshot(self) -> SourceSnapshot:
        """返回热源状态快照，温度与流量在同一把锁里一起取。"""

        with self._guard:
            return SourceSnapshot(
                state=self._state,
                temperature_c=self._temperature_c,
                flow_t_h=self._flow_t_h,
                target_c=self._target_c,
                quality_hold_s=self._quality_hold_s,
                adjustments=self._adjustments,
                trip_reason=self._trip_reason,
            )
