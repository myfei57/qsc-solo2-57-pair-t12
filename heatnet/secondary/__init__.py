"""二次网。

二次网负责把一次网送来的热量分到末端：循环泵建立流量，补水定压把系统压力顶在
许可带内，回水温度按水力平衡收敛。一个循环无论走成功还是半途失败，泵都必须在
离开循环之前停稳。
"""

from __future__ import annotations

from .balance import BalanceReport, hydraulic_balance
from .cycle import run_cycle
from .loop import SecondaryLoop
from .makeup import makeup_then_pressurise
from .state import SecondarySnapshot

__all__ = [
    "BalanceReport",
    "SecondaryLoop",
    "SecondarySnapshot",
    "hydraulic_balance",
    "makeup_then_pressurise",
    "run_cycle",
]
