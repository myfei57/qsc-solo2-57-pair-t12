"""定压控制。

基线只是目标值，泵房还要把实际定压拉到基线附近。改造下发先过
:class:`~heatnet.pressure.baseline.PressureBaseline`，成功之后才驱动二次网
压力；下发失败时二次网压力一个字节都不许动。
"""

from __future__ import annotations

from ..config import PressureLimits
from ..errors import PlantError
from ..secondary.loop import SecondaryLoop
from .baseline import PressureBaseline

MAX_STEPS = 600


class PressurisingController:
    """把二次网定压拉到基线附近的控制器。"""

    def __init__(self, baseline: PressureBaseline, limits: PressureLimits) -> None:
        self._baseline = baseline
        self._limits = limits
        self._settles = 0

    @property
    def baseline(self) -> PressureBaseline:
        return self._baseline

    @property
    def limits(self) -> PressureLimits:
        return self._limits

    def settles(self) -> int:
        """返回累计收敛次数。"""

        return self._settles

    def settle(self, loop: SecondaryLoop, dt: float = 1.0) -> float:
        """把二次网定压推进到当前基线附近，返回收敛后的压力。"""

        if dt <= 0:
            raise ValueError("步长必须为正")
        target = self._baseline.value_kpa()
        for _ in range(MAX_STEPS):
            current = loop.pressure_kpa()
            gap = target - current
            if abs(gap) <= 2.0:
                break
            if gap > 0:
                loop.add_pressure(min(gap, 12.0 * dt))
            else:
                loop.bleed_pressure(min(-gap, 12.0 * dt))
        self._settles += 1
        return loop.pressure_kpa()

    def retrofit(self, loop: SecondaryLoop, target_kpa: float, dt: float = 1.0) -> dict:
        """下发一次定压改造并驱动二次网收敛。"""

        before = self._baseline.value_kpa()
        try:
            baseline = self._baseline.apply_retrofit(target_kpa)
        except PlantError as error:
            return {
                "ok": False,
                "violations": [error.message],
                "baseline_kpa": round(before, 2),
                "rolled_back": True,
            }
        settled = self.settle(loop, dt)
        return {
            "ok": True,
            "violations": [],
            "baseline_kpa": round(baseline, 2),
            "pressure_kpa": round(settled, 2),
            "rolled_back": False,
        }
