"""混水阀动作。

混水阀按需求开度调整，然后站向目标温度逼近：先算需求、再动阀、最后收敛温度。
顺序反过来会让阀门按上一拍的温差动作，温度收敛慢一拍。
"""

from __future__ import annotations

from ..valve.move import move_valve
from ..valve.valve import Valve
from ..store.state import DurableState
from .station import HeatStation


def apply_mix(
    station: HeatStation,
    valve: Valve,
    durable: DurableState,
    target_c: float,
    dt: float = 1.0,
) -> dict:
    """按目标温度调整混水阀并推进站内温度。"""

    station.set_target(target_c)
    demand = station.demand_pct()
    move = move_valve(valve, durable, demand)
    for _ in range(600):
        valve.step(dt)
        if valve.at_target():
            break
    supply = station.settle(dt)
    return {
        "station": station.name,
        "target_c": round(target_c, 2),
        "demand_pct": round(demand, 2),
        "valve_pct": round(valve.position_pct(), 2),
        "supply_c": round(supply, 2),
        "move": move.as_dict(),
    }
