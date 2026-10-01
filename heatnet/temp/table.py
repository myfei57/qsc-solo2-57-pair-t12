"""供热曲线分段表。

曲线用三个断点描述：室外最冷点对应最高供温、室外最暖点对应最低供温、区间中点
落在两者之间。断点之间线性插值，区间之外按端点取值——室外温度超出断点时曲线
只负责夹取，是否越界由 :class:`~heatnet.temp.curve.HeatCurve` 的校验判定。
"""

from __future__ import annotations

from ..config import CurveLimits


class CurveTable:
    """按室外温度插值的一次网供温表。"""

    def __init__(self, limits: CurveLimits) -> None:
        self._limits = limits
        mid = (limits.outdoor_min_c + limits.outdoor_max_c) / 2.0
        self._points: tuple[tuple[float, float], ...] = (
            (limits.outdoor_min_c, limits.supply_high_c),
            (mid, (limits.supply_high_c + limits.supply_low_c) / 2.0),
            (limits.outdoor_max_c, limits.supply_low_c),
        )

    @property
    def limits(self) -> CurveLimits:
        return self._limits

    def points(self) -> list[dict]:
        """返回断点列表。"""

        return [{"outdoor_c": round(o, 2), "supply_c": round(s, 2)} for o, s in self._points]

    def interpolate(self, outdoor_c: float) -> float:
        """按室外温度插值出供温。"""

        value = float(outdoor_c)
        if value <= self._points[0][0]:
            return self._points[0][1]
        if value >= self._points[-1][0]:
            return self._points[-1][1]
        for (left_x, left_y), (right_x, right_y) in zip(self._points, self._points[1:]):
            if left_x <= value <= right_x:
                ratio = (value - left_x) / (right_x - left_x)
                return left_y + (right_y - left_y) * ratio
        return self._points[-1][1]
