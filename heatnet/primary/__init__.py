"""一次网。

一次网承接热源，把流量分给各换热站。流量基线可以被重新标定，调度下发前先按
优先级排好站的调节顺序；每个站的目标流量必须独立算出来，不允许用上一站的结果
往下滚。
"""

from __future__ import annotations

from .flow import StationFlow, batch_flows
from .network import PrimaryNetwork
from .order import priority_order
from .state import NetworkSnapshot

__all__ = ["NetworkSnapshot", "PrimaryNetwork", "StationFlow", "batch_flows", "priority_order"]
