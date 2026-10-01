"""换热站批量调节服务。

批量调节按分区逐站下发，每处理一个站之前都要重新看一次取消信号：只在循环开始
前看一次、或者在循环之后补一次，客户端超时取消之后剩下的站照样会被改掉，现场
看到的是"取消之后还有几个站的阀位变了"。
"""

from __future__ import annotations

from ..store.state import DurableState
from ..valve.valve import Valve
from .mapping import StationMapping
from .mix import apply_mix
from .station import HeatStation


class CancelToken:
    """批量下发的取消信号。"""

    def __init__(self, reason: str = "client-timeout") -> None:
        self._cancelled = False
        self._reason = str(reason)

    def cancel(self) -> None:
        """置位取消。"""

        self._cancelled = True

    def cancelled(self) -> bool:
        """取消是否已经置位。"""

        return self._cancelled

    def reason(self) -> str:
        """返回取消原因。"""

        return self._reason


class StationService:
    """按分区批量调节换热站。"""

    def __init__(
        self,
        stations: dict[str, HeatStation],
        valves: dict[str, Valve],
        durable: DurableState,
    ) -> None:
        self._stations = stations
        self._valves = valves
        self._durable = durable
        self._batches = 0
        self._aborted = 0

    @property
    def durable(self) -> DurableState:
        return self._durable

    def names(self) -> list[str]:
        """返回全部站名（排序后）。"""

        return sorted(self._stations)

    def get(self, name: str) -> HeatStation:
        """按名取站。"""

        try:
            return self._stations[name]
        except KeyError as error:
            raise KeyError(f"未登记换热站: {name}") from error

    def valve(self, name: str) -> Valve:
        """按名取站的混水阀。"""

        try:
            return self._valves[name]
        except KeyError as error:
            raise KeyError(f"换热站没有混水阀: {name}") from error

    def batches(self) -> int:
        """返回累计批量调节次数。"""

        return self._batches

    def aborted(self) -> int:
        """返回累计因取消而中断的次数。"""

        return self._aborted

    def adjust_zone(
        self,
        mapping: StationMapping,
        zone_name: str,
        target_c: float,
        cancel: CancelToken | None = None,
        dt: float = 1.0,
    ) -> dict:
        """调节一个分区里的全部换热站，每一步都检查取消信号。"""

        if dt <= 0:
            raise ValueError("步长必须为正")
        members = mapping.stations_in(zone_name)
        steps: list[dict] = []
        adjusted: list[str] = []
        self._batches += 1
        for station_name in members:
            if cancel is not None and cancel.cancelled():
                self._aborted += 1
                return {
                    "ok": False,
                    "zone": zone_name,
                    "steps": steps,
                    "adjusted": adjusted,
                    "skipped": members[len(adjusted):],
                    "violations": [f"cancelled:{cancel.reason()}"],
                }
            station = self.get(station_name)
            valve = self.valve(station_name)
            detail = apply_mix(station, valve, self._durable, target_c, dt)
            self._durable.save(f"station/{station_name}", {"zone": zone_name, "target_c": target_c})
            adjusted.append(station_name)
            steps.append({"component": "station", "action": "adjust", "detail": detail})
        return {
            "ok": True,
            "zone": zone_name,
            "steps": steps,
            "adjusted": adjusted,
            "skipped": [],
            "violations": [],
        }
