"""换热站本体。

站只维护自己的二次侧供水温度与目标温度；混水阀、流量与落盘都由上层编排负责，
这样"每一步是否被取消"可以在服务层统一判定，站本身不参与取消逻辑。
"""

from __future__ import annotations

from ..config import StationLimits
from .state import StationSnapshot


class HeatStation:
    """一个换热站。"""

    def __init__(self, name: str, zone: str, limits: StationLimits, supply_c: float | None = None) -> None:
        self._name = name
        self._zone = zone
        self._limits = limits
        self._supply_c = float(limits.setpoint_c if supply_c is None else supply_c)
        self._target_c = float(limits.setpoint_c)
        self._steps = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def limits(self) -> StationLimits:
        return self._limits

    def zone(self) -> str:
        """返回所属分区。"""

        return self._zone

    def rezone(self, zone: str) -> str:
        """更新所属分区（拆分之后由编排调用）。"""

        self._zone = str(zone)
        return self._zone

    def supply_c(self) -> float:
        """返回二次侧供水温度。"""

        return self._supply_c

    def target_c(self) -> float:
        """返回二次侧目标温度。"""

        return self._target_c

    def steps(self) -> int:
        """返回累计调节步数。"""

        return self._steps

    def at_setpoint(self) -> bool:
        """供水温度是否落在设定点带内。"""

        return self._limits.at_setpoint(self._supply_c)

    def set_target(self, temperature_c: float) -> float:
        """设定二次侧目标温度。"""

        self._target_c = float(temperature_c)
        return self._target_c

    def demand_pct(self) -> float:
        """按目标温差给出混水阀需求开度。"""

        gap = self._target_c - self._supply_c
        return max(0.0, min(100.0, 50.0 + gap * 12.0))

    def settle(self, dt: float) -> float:
        """向目标温度逼近一个步长。"""

        if dt <= 0:
            raise ValueError("步长必须为正")
        self._steps += 1
        rate = self._limits.mix_travel_pct_s * 0.05 * dt
        delta = self._target_c - self._supply_c
        if abs(delta) <= rate:
            self._supply_c = self._target_c
        else:
            self._supply_c += rate if delta > 0 else -rate
        return self._supply_c

    def snapshot(self) -> StationSnapshot:
        """返回换热站状态快照。"""

        return StationSnapshot(
            name=self._name,
            zone=self._zone,
            supply_c=self._supply_c,
            target_c=self._target_c,
            demand_pct=self.demand_pct(),
            steps=self._steps,
            at_setpoint=self.at_setpoint(),
        )
