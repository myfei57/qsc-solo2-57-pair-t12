"""供热配额与热量表。

热量表按周期累计热量，读数到顶后回绕，总账要同时给出"表读数"和"实际累计"两个
口径。多个采集任务会并发累加同一块表，累加必须是原子的：非原子的 ``+=`` 在并发
下会丢增量，总账比实际小。
"""

from __future__ import annotations

from .accumulator import QuotaAccumulator
from .billing import billing_lines
from .meter import HeatMeter
from .quota import QuotaLedger
from .state import MeterSnapshot, QuotaSnapshot

__all__ = [
    "HeatMeter",
    "MeterSnapshot",
    "QuotaAccumulator",
    "QuotaLedger",
    "QuotaSnapshot",
    "billing_lines",
]
