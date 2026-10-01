"""混水阀本体。

阀门只保存"当前开度"与"目标开度"两个物理量，不知道持久化与队列的存在。落盘与
检查点由 :mod:`~heatnet.valve.move` 和 :mod:`~heatnet.valve.queue` 负责，这样
一次动作的先后顺序（先落盘、再改内存）可以被单独验证。
"""

from __future__ import annotations

from ..config import ValveLimits
from .state import ValveSnapshot


class Valve:
    """一只混水阀。"""

    def __init__(self, name: str, limits: ValveLimits, position_pct: float = 0.0) -> None:
        self._name = name
        self._limits = limits
        self._position_pct = float(position_pct)
        self._target_pct = float(position_pct)
        self._moves = 0
        self._rejected = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def limits(self) -> ValveLimits:
        return self._limits

    def position_pct(self) -> float:
        """返回当前开度。"""

        return self._position_pct

    def target_pct(self) -> float:
        """返回目标开度。"""

        return self._target_pct

    def moves(self) -> int:
        """返回累计成功动作次数。"""

        return self._moves

    def rejected(self) -> int:
        """返回累计被拒动作次数。"""

        return self._rejected

    def reject(self) -> int:
        """记一次被拒动作（落盘失败等）。"""

        self._rejected += 1
        return self._rejected

    def at_target(self) -> bool:
        """开度是否已经落在到位公差内。"""

        return self._limits.settled(self._position_pct, self._target_pct)

    def set_target(self, target_pct: float) -> float:
        """只改目标开度（不发动作，不落盘）。"""

        self._target_pct = max(0.0, min(100.0, float(target_pct)))
        return self._target_pct

    def apply(self, position_pct: float) -> float:
        """把开度直接置为给定值，并累计一次成功动作。"""

        self._position_pct = max(0.0, min(100.0, float(position_pct)))
        self._target_pct = self._position_pct
        self._moves += 1
        return self._position_pct

    def step(self, dt: float) -> float:
        """按行程速率向目标开度推进一个步长。"""

        if dt <= 0:
            raise ValueError("步长必须为正")
        step = self._limits.travel_pct_s * dt
        delta = self._target_pct - self._position_pct
        if abs(delta) <= step:
            self._position_pct = self._target_pct
        else:
            self._position_pct += step if delta > 0 else -step
        return self._position_pct

    def snapshot(self) -> ValveSnapshot:
        """返回阀门状态快照。"""

        return ValveSnapshot(
            name=self._name,
            position_pct=self._position_pct,
            target_pct=self._target_pct,
            moves=self._moves,
            settled=self.at_target(),
            rejected=self._rejected,
        )
