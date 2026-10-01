"""循环泵状态与升速。

启动后按配置的升速斜率把流量抬到目标；负荷撤销后同样按斜率回落。泵本身不写盘，
需要落盘的是"这次循环有没有正常收尾"——由二次网循环负责，见
:mod:`~heatnet.secondary.cycle`。
"""

from __future__ import annotations

from ..config import PumpLimits
from .curve import PumpCurve
from .state import PumpSnapshot

FLOW_EPSILON = 1e-6


class Pump:
    """一台循环泵。"""

    def __init__(self, name: str, limits: PumpLimits, curve: PumpCurve) -> None:
        self._name = name
        self._limits = limits
        self._curve = curve
        self._running = False
        self._speed_pct = 0.0
        self._flow_t_h = 0.0
        self._target_flow_t_h = 0.0
        self._starts = 0
        self._stops = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def limits(self) -> PumpLimits:
        return self._limits

    @property
    def curve(self) -> PumpCurve:
        return self._curve

    def running(self) -> bool:
        """泵是否处于运行状态。"""

        return self._running

    def idle(self) -> bool:
        """泵是否已经停稳（不在运行且流量归零）。"""

        return not self._running and self._flow_t_h <= FLOW_EPSILON

    def flow_t_h(self) -> float:
        """返回当前流量。"""

        return self._flow_t_h

    def target_flow_t_h(self) -> float:
        """返回目标流量。"""

        return self._target_flow_t_h

    def speed_pct(self) -> float:
        """返回当前转速。"""

        return self._speed_pct

    def starts(self) -> int:
        """返回累计启动次数。"""

        return self._starts

    def stops(self) -> int:
        """返回累计停止次数。"""

        return self._stops

    def start(self, speed_pct: float = 100.0) -> float:
        """启动泵并把目标流量设为该转速对应的流量。"""

        self._running = True
        self._starts += 1
        self._target_flow_t_h = self._curve.flow_for(speed_pct)
        return self._target_flow_t_h

    def stop(self) -> float:
        """停泵并撤销目标流量（流量按斜率回落）。"""

        if self._running:
            self._stops += 1
        self._running = False
        self._target_flow_t_h = 0.0
        return self._target_flow_t_h

    def set_speed(self, speed_pct: float) -> float:
        """调整目标转速。"""

        self._speed_pct = max(
            self._limits.min_speed_pct, min(self._limits.max_speed_pct, float(speed_pct))
        )
        self._target_flow_t_h = self._curve.flow_for(self._speed_pct)
        return self._speed_pct

    def step(self, dt: float) -> float:
        """按升速斜率推进一个步长，返回推进后的流量。"""

        if dt <= 0:
            raise ValueError("步长必须为正")
        step = self._limits.ramp_t_h_s * dt
        delta = self._target_flow_t_h - self._flow_t_h
        if abs(delta) <= step:
            self._flow_t_h = self._target_flow_t_h
        else:
            self._flow_t_h += step if delta > 0 else -step
        if self._flow_t_h <= FLOW_EPSILON:
            self._flow_t_h = 0.0
        self._speed_pct = 0.0 if self._flow_t_h <= FLOW_EPSILON else self._curve.speed_for(self._flow_t_h)
        return self._flow_t_h

    def snapshot(self) -> PumpSnapshot:
        """返回循环泵状态快照。"""

        return PumpSnapshot(
            name=self._name,
            running=self._running,
            speed_pct=self._speed_pct,
            flow_t_h=self._flow_t_h,
            target_flow_t_h=self._target_flow_t_h,
            starts=self._starts,
            stops=self._stops,
        )
