"""时钟抽象。

生产环境使用 :class:`SystemClock`；标定、复现与单元验证使用
:class:`ManualClock`，让采样过期、流量确认累积和批量下发间隔在不真实等待的
前提下推进——这些跨模块顺序必须能被显式推进，否则无法在验证环境里观察。
"""

from __future__ import annotations

import time


class Clock:
    """时钟基类，只实现各实现共享的格式化逻辑。"""

    def now(self) -> float:
        """返回 Unix 时间戳（秒）。"""

        raise NotImplementedError

    def monotonic(self) -> float:
        """返回单调递增秒数，用于测量间隔。"""

        raise NotImplementedError

    def sleep(self, seconds: float) -> None:
        """等待给定秒数。"""

        raise NotImplementedError

    def utc_iso(self) -> str:
        """把当前时间格式化成审计流水使用的时间戳。"""

        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.now()))


class SystemClock(Clock):
    """真实时钟。"""

    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class ManualClock(Clock):
    """可手动推进的时钟，``sleep`` 直接推进自身时间。"""

    def __init__(self, start: float = 1_758_000_000.0) -> None:
        self._now = float(start)
        self._mono = 0.0

    def now(self) -> float:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def advance(self, seconds: float) -> float:
        """把两个时间轴同时推进 ``seconds`` 秒，返回推进后的挂钟时间。"""

        if seconds < 0:
            raise ValueError("时钟不能回退")
        self._now += seconds
        self._mono += seconds
        return self._now
