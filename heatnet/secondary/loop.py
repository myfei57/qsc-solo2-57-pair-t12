"""二次网回路状态。

回路按"补水定压 → 建立流量 → 回水收敛"的顺序推进：压力跌破补水门限时先补水，
补水到位才允许继续建立流量；回水温度越上限时回路把这一步标成越限，由循环编排
决定是停下还是继续。
"""

from __future__ import annotations

from ..config import SecondaryLimits
from .balance import BalanceReport, hydraulic_balance
from .state import SecondarySnapshot

RETURN_CEILING_MARGIN_C = 15.0
SUPPLY_DELTA_C = 20.0
MAKEUP_STEP_KPA = 12.0


class SecondaryLoop:
    """二次网回路：回水、供水与定压。"""

    def __init__(self, limits: SecondaryLimits) -> None:
        self._limits = limits
        self._return_c = limits.return_target_c - 4.0
        self._supply_c = self._return_c + SUPPLY_DELTA_C
        self._pressure_kpa = limits.makeup_target_kpa
        self._steps = 0
        self._disturbances = 0

    @property
    def limits(self) -> SecondaryLimits:
        return self._limits

    def supply_c(self) -> float:
        """返回二次网供水温度。"""

        return self._supply_c

    def return_c(self) -> float:
        """返回二次网回水温度。"""

        return self._return_c

    def delta_c(self) -> float:
        """返回供回水温差。"""

        return self._supply_c - self._return_c

    def pressure_kpa(self) -> float:
        """返回系统定压。"""

        return self._pressure_kpa

    def steps(self) -> int:
        """返回累计推进步数。"""

        return self._steps

    def disturbances(self) -> int:
        """返回累计扰动次数。"""

        return self._disturbances

    def needs_makeup(self) -> bool:
        """定压是否跌破补水门限。"""

        return self._limits.needs_makeup(self._pressure_kpa)

    def overpressure(self) -> bool:
        """定压是否越上限。"""

        return self._limits.overpressure(self._pressure_kpa)

    def return_ceiling_c(self) -> float:
        """返回回水温度判定上限。"""

        return self._limits.return_target_c + RETURN_CEILING_MARGIN_C

    def overheat(self) -> bool:
        """回水是否越上限。"""

        return self._return_c > self.return_ceiling_c()

    def add_pressure(self, delta_kpa: float) -> float:
        """补一次压，返回补后的定压。"""

        self._pressure_kpa += float(delta_kpa)
        return self._pressure_kpa

    def bleed_pressure(self, delta_kpa: float) -> float:
        """泄一次压，返回泄后的定压。"""

        self._pressure_kpa = max(0.0, self._pressure_kpa - float(delta_kpa))
        return self._pressure_kpa

    def disturb(self, heat_fraction: float) -> float:
        """注入一次热负荷扰动，抬高回水温度。"""

        self._disturbances += 1
        self._return_c += max(0.0, float(heat_fraction)) * 12.0
        return self._return_c

    def makeup_step(self, dt: float) -> float:
        """推进一次补水：低于门限才补，补到目标就停。"""

        if dt <= 0:
            raise ValueError("步长必须为正")
        if self._pressure_kpa < self._limits.makeup_target_kpa:
            self._pressure_kpa = min(
                self._limits.makeup_target_kpa, self._pressure_kpa + MAKEUP_STEP_KPA * dt
            )
        return self._pressure_kpa

    def step(self, dt: float, flow_t_h: float) -> dict:
        """推进一个控制步长，返回本步的水力平衡报告。"""

        if dt <= 0:
            raise ValueError("步长必须为正")
        self._steps += 1
        flow = max(0.0, float(flow_t_h))
        baseline = self._pressure_kpa / max(1.0, self._limits.makeup_target_kpa)
        approach = 0.08 * dt * min(1.0, flow / 200.0) * baseline
        target_return = self._limits.return_target_c
        if self._return_c < target_return:
            self._return_c = min(target_return, self._return_c + approach * 4.0)
        elif self._return_c > target_return:
            self._return_c = max(target_return, self._return_c - approach)
        self._supply_c = self._return_c + SUPPLY_DELTA_C * min(1.0, flow / 200.0)
        report: BalanceReport = hydraulic_balance(flow, self._supply_c, self._return_c)
        payload = report.as_dict()
        payload["overheat"] = self.overheat()
        payload["needs_makeup"] = self.needs_makeup()
        return payload

    def snapshot(self) -> SecondarySnapshot:
        """返回二次网状态快照。"""

        return SecondarySnapshot(
            supply_c=self._supply_c,
            return_c=self._return_c,
            delta_c=self.delta_c(),
            pressure_kpa=self._pressure_kpa,
            margin_to_min_kpa=self._pressure_kpa - self._limits.makeup_min_kpa,
            overpressure=self.overpressure(),
            steps=self._steps,
            disturbances=self._disturbances,
        )
