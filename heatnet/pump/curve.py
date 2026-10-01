"""循环泵特性曲线。

转速与流量之间按线性特性换算：下限转速对应下限流量，上限转速对应上限流量。
曲线只做换算，不判断泵是否在转——运行状态由 :class:`~heatnet.pump.pump.Pump`
自己维护。
"""

from __future__ import annotations


class PumpCurve:
    """转速到流量的线性特性。"""

    def __init__(
        self,
        min_speed_pct: float,
        max_speed_pct: float,
        min_flow_t_h: float,
        max_flow_t_h: float,
    ) -> None:
        if min_speed_pct >= max_speed_pct:
            raise ValueError("转速下限必须小于上限")
        if min_flow_t_h >= max_flow_t_h:
            raise ValueError("流量下限必须小于上限")
        self._min_speed = float(min_speed_pct)
        self._max_speed = float(max_speed_pct)
        self._min_flow = float(min_flow_t_h)
        self._max_flow = float(max_flow_t_h)

    def flow_for(self, speed_pct: float) -> float:
        """按转速换算流量（越界按端点夹取）。"""

        speed = max(self._min_speed, min(self._max_speed, float(speed_pct)))
        ratio = (speed - self._min_speed) / (self._max_speed - self._min_speed)
        return self._min_flow + (self._max_flow - self._min_flow) * ratio

    def speed_for(self, flow_t_h: float) -> float:
        """按流量反算转速（越界按端点夹取）。"""

        flow = max(self._min_flow, min(self._max_flow, float(flow_t_h)))
        ratio = (flow - self._min_flow) / (self._max_flow - self._min_flow)
        return self._min_speed + (self._max_speed - self._min_speed) * ratio

    def describe(self) -> dict:
        """返回特性曲线的端点，供状态页展示。"""

        return {
            "min_speed_pct": round(self._min_speed, 2),
            "max_speed_pct": round(self._max_speed, 2),
            "min_flow_t_h": round(self._min_flow, 2),
            "max_flow_t_h": round(self._max_flow, 2),
        }
