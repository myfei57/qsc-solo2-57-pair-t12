"""一次网管网状态。

网里只有一个"当前总流量"字段，它是全网的结果而不是中间量：任何按站计算的过程
都必须用本地变量累加，算完再一次性写回。中间步骤里反复改写这个共享字段，后一个
站就会把前一个站的累加值当成自己的起点。
"""

from __future__ import annotations

from ..config import PrimaryLimits
from .state import NetworkSnapshot


class PrimaryNetwork:
    """一次网：供回水温度、总流量与流量基线。"""

    def __init__(self, limits: PrimaryLimits) -> None:
        self._limits = limits
        self._supply_c = 0.0
        self._return_c = 0.0
        self._flow_t_h = 0.0
        self._baseline_t_h = limits.flow_baseline_t_h
        self._recalibrations = 0
        self._dispatches = 0

    @property
    def limits(self) -> PrimaryLimits:
        return self._limits

    def supply_c(self) -> float:
        """返回一次网供水温度。"""

        return self._supply_c

    def return_c(self) -> float:
        """返回一次网回水温度。"""

        return self._return_c

    def flow_t_h(self) -> float:
        """返回当前总流量。"""

        return self._flow_t_h

    def baseline_t_h(self) -> float:
        """返回当前流量基线。"""

        return self._baseline_t_h

    def threshold_t_h(self) -> float:
        """返回低流量联锁门限。"""

        return self._limits.low_flow_threshold(self._baseline_t_h)

    def low_flow(self) -> bool:
        """总流量是否跌破联锁门限。"""

        return self._flow_t_h < self.threshold_t_h()

    def recalibrations(self) -> int:
        """返回累计重新标定次数。"""

        return self._recalibrations

    def dispatches(self) -> int:
        """返回累计下发次数。"""

        return self._dispatches

    def set_supply(self, temperature_c: float) -> float:
        """更新一次网供水温度。"""

        self._supply_c = float(temperature_c)
        return self._supply_c

    def set_return(self, temperature_c: float) -> float:
        """更新一次网回水温度。"""

        self._return_c = float(temperature_c)
        return self._return_c

    def set_flow(self, flow_t_h: float) -> float:
        """把总流量写为给定值，返回写后的流量。"""

        self._flow_t_h = max(0.0, float(flow_t_h))
        return self._flow_t_h

    def recalibrate(self, measured_t_h: float) -> float:
        """按实测流量重新标定基线，联锁门限随之变化。"""

        self._baseline_t_h = max(1.0, float(measured_t_h))
        self._recalibrations += 1
        return self._baseline_t_h

    def count_dispatch(self) -> int:
        """记一次下发。"""

        self._dispatches += 1
        return self._dispatches

    def deviation_t_h(self) -> float:
        """返回当前总流量相对基线的偏差。"""

        return self._flow_t_h - self._baseline_t_h

    def snapshot(self) -> NetworkSnapshot:
        """返回一次网状态快照。"""

        return NetworkSnapshot(
            supply_c=self._supply_c,
            return_c=self._return_c,
            flow_t_h=self._flow_t_h,
            baseline_t_h=self._baseline_t_h,
            threshold_t_h=self.threshold_t_h(),
            low_flow=self.low_flow(),
            recalibrations=self._recalibrations,
            dispatches=self._dispatches,
        )
