"""供热分区与站归属索引。

分区表同时维护两份索引：``分区 → 站列表`` 供批量调节按区分组，``站 → 分区``
供调度按站查参数。两份索引指向同一份事实，因此任何一次拆分都必须一起更新——
只改站列表而不重建反向索引，拆分后的新分区在调度眼里仍然挂着旧分区的参数。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import NamespaceError

SUPPLY = "supply"
RETURN = "return"


@dataclass
class Zone:
    """一个供热分区。"""

    name: str
    kind: str = SUPPLY
    setpoint_c: float = 0.0
    stations: list[str] = field(default_factory=list)

    def add_station(self, station: str) -> None:
        """把一个换热站加入本区（重复加入幂等）。"""

        if station not in self.stations:
            self.stations.append(station)

    def drop_station(self, station: str) -> bool:
        """把一个换热站移出本区，返回是否真的移出了。"""

        if station in self.stations:
            self.stations.remove(station)
            return True
        return False

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "setpoint_c": round(self.setpoint_c, 2),
            "stations": list(self.stations),
        }


class ZoneRegistry:
    """分区注册表与站归属反向索引。"""

    def __init__(self) -> None:
        self._zones: dict[str, Zone] = {}
        self._station_zone: dict[str, str] = {}
        self._splits = 0

    def add(self, zone: Zone) -> Zone:
        """登记一个分区，重名即报错。"""

        if not zone.name:
            raise NamespaceError("分区必须有名字", component="ns")
        if zone.name in self._zones:
            raise NamespaceError(f"分区已存在: {zone.name}", component="ns")
        self._zones[zone.name] = zone
        for station in zone.stations:
            self._station_zone[station] = zone.name
        return zone

    def assign(self, station: str, zone_name: str) -> str:
        """把一个站划入分区，同时维护两份索引。"""

        zone = self.get(zone_name)
        previous = self._station_zone.get(station)
        if previous is not None and previous != zone_name:
            self._zones[previous].drop_station(station)
        zone.add_station(station)
        self._station_zone[station] = zone_name
        return zone_name

    def zone_of(self, station: str) -> str:
        """按站反查分区名。"""

        try:
            return self._station_zone[station]
        except KeyError as error:
            raise NamespaceError(f"换热站未归属任何分区: {station}", component="ns") from error

    def split(self, source_name: str, station_names: list[str], new_name: str) -> Zone:
        """从既有分区里拆出一个新分区。"""

        source = self.get(source_name)
        if new_name == source_name:
            raise NamespaceError("拆分后的分区名不能与原分区相同", component="ns")
        if new_name in self._zones:
            raise NamespaceError(f"分区已存在: {new_name}", component="ns")
        moving = [station for station in station_names if station in source.stations]
        if not moving:
            raise NamespaceError("拆分必须至少包含一个属于原分区的站", component="ns")

        child = Zone(name=new_name, kind=source.kind, setpoint_c=source.setpoint_c)
        for station in moving:
            source.drop_station(station)
            child.add_station(station)
        self._zones[new_name] = child
        self._splits += 1
        self.rebuild_index()
        return child

    def rebuild_index(self) -> int:
        """按分区表重建"站 → 分区"反向索引，返回索引条目数。"""

        rebuilt: dict[str, str] = {}
        for zone in self._zones.values():
            for station in zone.stations:
                rebuilt[station] = zone.name
        self._station_zone = rebuilt
        return len(rebuilt)

    def get(self, name: str) -> Zone:
        """按名字取分区。"""

        try:
            return self._zones[name]
        except KeyError as error:
            raise NamespaceError(f"未登记分区: {name}", component="ns") from error

    def names(self) -> list[str]:
        """返回全部分区名（排序后）。"""

        return sorted(self._zones)

    def stations(self, name: str) -> list[str]:
        """返回某分区的站列表（按加入顺序）。"""

        return list(self.get(name).stations)

    def index(self) -> dict[str, str]:
        """返回反查索引的只读副本。"""

        return dict(self._station_zone)

    def splits(self) -> int:
        """返回累计拆分次数。"""

        return self._splits

    def describe(self) -> dict:
        """汇总分区与索引，供状态快照读取。"""

        return {
            "count": len(self._zones),
            "splits": self._splits,
            "zones": [self._zones[name].as_dict() for name in self.names()],
            "index": dict(sorted(self._station_zone.items())),
        }
