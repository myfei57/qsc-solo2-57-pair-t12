"""供热曲线与多源气象融合。

曲线按室外温度给出一次网目标供水温度：室外越冷，供温越高。曲线是"按气象更新"
的对象，每次更新都要先校验室外温度是否落在适用区间内，校验通过才允许覆盖旧值；
超过新鲜度窗口的曲线一律视为过期，热源不得据其点火。

多家预报并存时，由 :class:`~heatnet.temp.blend.ForecastBlender` 先筛可信源再合成
一条室外温度序列，曲线只从合成序列取值；全部不可信时按时段在"撑着"与"保守经验
曲线"之间切换，切换与合成共用同一条单调时序。
"""

from __future__ import annotations

from .blend import (
    MODE_FALLBACK,
    MODE_HOLD,
    MODE_LIVE,
    BlendDecision,
    BlendPoint,
    ForecastBlender,
    ProviderReading,
)
from .curve import HeatCurve
from .forecast import ForecastPoint, build_forecast, describe_forecast
from .state import CurveSnapshot
from .table import CurveTable

__all__ = [
    "BlendDecision",
    "BlendPoint",
    "CurveSnapshot",
    "CurveTable",
    "ForecastBlender",
    "ForecastPoint",
    "HeatCurve",
    "MODE_FALLBACK",
    "MODE_HOLD",
    "MODE_LIVE",
    "ProviderReading",
    "build_forecast",
    "describe_forecast",
]
