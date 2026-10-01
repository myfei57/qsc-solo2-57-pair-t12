"""分区拆分与站归属反向索引。"""

from __future__ import annotations

import pytest

from heatnet.errors import NamespaceError
from heatnet.ns.zone import Zone, ZoneRegistry
from heatnet.station.mapping import StationMapping


def _registry() -> ZoneRegistry:
    zones = ZoneRegistry()
    zones.add(Zone(name="north", setpoint_c=62.0))
    for station in ("st01", "st02", "st03"):
        zones.assign(station, "north")
    zones.add(Zone(name="south", setpoint_c=58.0))
    zones.assign("st04", "south")
    return zones


def test_zone_registry_assign_and_describe():
    zones = _registry()
    assert zones.names() == ["north", "south"]
    assert zones.stations("north") == ["st01", "st02", "st03"]
    assert zones.zone_of("st04") == "south"
    assert zones.describe()["count"] == 2
    assert zones.describe()["index"]["st04"] == "south"
    with pytest.raises(NamespaceError):
        zones.add(Zone(name="north"))
    with pytest.raises(NamespaceError):
        zones.get("east")
    with pytest.raises(NamespaceError):
        zones.zone_of("st99")
    zones.assign("st04", "north")
    assert zones.stations("south") == []
    assert zones.zone_of("st04") == "north"


def test_split_rebuilds_reverse_index():
    zones = _registry()
    mapping = StationMapping(zones)
    assert mapping.generation() == 1
    assert mapping.zone_of("st02") == "north"

    zones.split("north", ["st02", "st03"], "north-west")
    # 拆分只改了分区表，索引还是旧的：这正是必须重建的那一步。
    assert mapping.zone_of("st02") == "north"

    assert mapping.rebuild() == 4
    assert mapping.generation() == 2
    assert mapping.zone_of("st02") == "north-west"
    assert mapping.stations_in("north") == ["st01"]
    assert mapping.stations_in("north-west") == ["st02", "st03"]
    assert mapping.describe()["count"] == 4
    assert zones.splits() == 1


def test_split_rejects_unknown_or_empty_inputs():
    zones = _registry()
    with pytest.raises(NamespaceError):
        zones.split("north", ["st04"], "north-west")
    with pytest.raises(NamespaceError):
        zones.split("north", ["st01"], "north")
    with pytest.raises(NamespaceError):
        zones.split("north", ["st01"], "south")
    assert zones.describe()["splits"] == 0
