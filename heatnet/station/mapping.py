"""站与分区的对应关系。

调度按站查参数，因此需要一份"站 → 分区"的反向索引。索引是从分区表派生出来的：
分区拆分改了站列表之后，索引必须重建，否则新分区里的站在调度眼里还挂在旧分区
名下，供的是旧分区的参数。
"""

from __future__ import annotations

from ..ns.zone import ZoneRegistry


class StationMapping:
    """基于分区表派生的站归属索引。"""

    def __init__(self, zones: ZoneRegistry) -> None:
        self._zones = zones
        self._index: dict[str, str] = {}
        self._generation = 0
        self.rebuild()

    @property
    def zones(self) -> ZoneRegistry:
        return self._zones

    def rebuild(self) -> int:
        """按分区表重建反向索引，返回索引条目数。"""

        self._index = self._zones.index()
        self._generation += 1
        return len(self._index)

    def generation(self) -> int:
        """返回索引代际，每次重建加一。"""

        return self._generation

    def zone_of(self, station: str) -> str:
        """按站反查分区名，索引过期时能立刻暴露。"""

        try:
            return self._index[station]
        except KeyError as error:
            raise KeyError(f"站未进入归属索引: {station}") from error

    def stations_in(self, zone_name: str) -> list[str]:
        """返回某分区下的站（按分区表顺序）。"""

        return [station for station in self._zones.stations(zone_name) if self._index.get(station) == zone_name]

    def describe(self) -> dict:
        """汇总索引，供状态快照读取。"""

        return {
            "generation": self._generation,
            "count": len(self._index),
            "index": dict(sorted(self._index.items())),
        }
