"""定压基线的校验与回滚。

改造下发要先算目标、再校验、最后才写基线。校验不过时必须保持原值：先写后校验
的话，越界目标已经进了基线，函数再返回错误也回不到旧值，二次网会卡在超压。
"""

from __future__ import annotations

from ..config import PressureLimits
from ..errors import InterlockError
from .state import PressureSnapshot


class PressureBaseline:
    """二次网定压基线。"""

    def __init__(self, limits: PressureLimits) -> None:
        self._limits = limits
        self._baseline_kpa = (limits.baseline_min_kpa + limits.baseline_max_kpa) / 2.0
        self._revisions = 0
        self._rejected = 0
        self._last_target_kpa = self._baseline_kpa

    @property
    def limits(self) -> PressureLimits:
        return self._limits

    def value_kpa(self) -> float:
        """返回当前基线。"""

        return self._baseline_kpa

    def revisions(self) -> int:
        """返回累计成功改造次数。"""

        return self._revisions

    def rejected(self) -> int:
        """返回累计被拒的改造次数。"""

        return self._rejected

    def last_target_kpa(self) -> float:
        """返回最近一次下发的目标值。"""

        return self._last_target_kpa

    def in_range(self, target_kpa: float) -> bool:
        """目标值是否落在许可范围内。"""

        return self._limits.in_range(target_kpa)

    def apply_retrofit(self, target_kpa: float) -> float:
        """按改造下发更新基线：先校验，通过才写值。"""

        target = float(target_kpa)
        self._last_target_kpa = target
        if not self.in_range(target):
            self._rejected += 1
            raise InterlockError(
                f"定压基线 {target:.1f} kPa 越界 "
                f"[{self._limits.baseline_min_kpa:.1f}, {self._limits.baseline_max_kpa:.1f}]",
                component="pressure",
            )
        self._baseline_kpa = target
        self._revisions += 1
        return self._baseline_kpa

    def snapshot(self) -> PressureSnapshot:
        """返回定压基线状态快照。"""

        return PressureSnapshot(
            baseline_kpa=self._baseline_kpa,
            revisions=self._revisions,
            rejected=self._rejected,
            last_target_kpa=self._last_target_kpa,
            in_range=self.in_range(self._baseline_kpa),
        )
