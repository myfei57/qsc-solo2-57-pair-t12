"""供热曲线与气象校验。

一次气象推送只有在室外温度落在适用区间内时才允许覆盖曲线。校验不通过时抛出
:class:`~heatnet.errors.ForecastError`，调用方必须把这条推送整条作废——把错误
吞掉继续点火，热源就会按上一版曲线运行，越界的室外温度根本进不到曲线里，现场
看到的现象是"曲线还是老的，供热没跟着天气走"。
"""

from __future__ import annotations

from ..config import CurveLimits
from ..errors import ForecastError
from .state import CurveSnapshot
from .table import CurveTable


class HeatCurve:
    """按气象更新的供热曲线。"""

    def __init__(self, limits: CurveLimits) -> None:
        self._limits = limits
        self._table = CurveTable(limits)
        self._outdoor_c = (limits.outdoor_min_c + limits.outdoor_max_c) / 2.0
        self._supply_c = self._table.interpolate(self._outdoor_c)
        self._updated_at = 0.0
        self._epoch = 0
        self._validated = 0
        self._rejected = 0

    @property
    def limits(self) -> CurveLimits:
        return self._limits

    @property
    def table(self) -> CurveTable:
        return self._table

    def outdoor_c(self) -> float:
        """返回当前曲线对应的室外温度。"""

        return self._outdoor_c

    def supply_c(self) -> float:
        """返回当前曲线的目标供水温度。"""

        return self._supply_c

    def epoch(self) -> int:
        """返回曲线代际，每次成功更新加一。"""

        return self._epoch

    def updated_at(self) -> float:
        """返回最近一次成功更新的时刻。"""

        return self._updated_at

    def validated(self) -> int:
        """返回累计通过的校验次数。"""

        return self._validated

    def rejected(self) -> int:
        """返回累计被拒绝的校验次数。"""

        return self._rejected

    def validate(self, outdoor_c: float) -> float:
        """校验室外温度是否落在适用区间内，越界即抛出。"""

        value = float(outdoor_c)
        if not self._limits.outdoor_in_range(value):
            self._rejected += 1
            raise ForecastError(
                f"室外温度 {value:.1f}℃ 超出曲线适用区间 "
                f"[{self._limits.outdoor_min_c:.1f}, {self._limits.outdoor_max_c:.1f}]",
                component="temp",
            )
        self._validated += 1
        return value

    def apply_forecast(self, outdoor_c: float, now: float) -> dict:
        """校验后覆盖曲线，返回更新后的摘要。"""

        value = self.validate(outdoor_c)
        self._outdoor_c = value
        self._supply_c = self._table.interpolate(value)
        self._updated_at = float(now)
        self._epoch += 1
        return {
            "outdoor_c": round(self._outdoor_c, 2),
            "supply_c": round(self._supply_c, 2),
            "epoch": self._epoch,
            "updated_at": round(self._updated_at, 3),
        }

    def is_stale(self, now: float) -> bool:
        """曲线是否已经超过新鲜度窗口。"""

        return (float(now) - self._updated_at) > self._limits.stale_after_s

    def snapshot(self, now: float) -> CurveSnapshot:
        """返回曲线状态快照。"""

        return CurveSnapshot(
            outdoor_c=self._outdoor_c,
            supply_c=self._supply_c,
            epoch=self._epoch,
            updated_at=self._updated_at,
            stale=self.is_stale(now),
            validated=self._validated,
            rejected=self._rejected,
        )
