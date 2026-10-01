"""先阀后泵的启停看守。

启泵之前混水阀必须已经到位：阀门还关着就启泵，二次网会被抽成负压；停运时反过
来，先停泵再关阀，阀先关会把泵憋住。两个方向都在这里做硬判定，条件不满足直接
拒绝，由调用方写审计。
"""

from __future__ import annotations

from ..errors import AlignmentError, InterlockError
from ..store.state import DurableState
from ..valve.move import move_valve
from ..valve.valve import Valve
from .pump import Pump

MAX_STEPS = 600


def start_pump_after_valve(
    valve: Valve,
    durable: DurableState,
    pump: Pump,
    target_pct: float,
    dt: float = 1.0,
    speed_pct: float = 100.0,
) -> dict:
    """先把阀门开到目标位，再启泵。"""

    move = move_valve(valve, durable, target_pct)
    for _ in range(MAX_STEPS):
        valve.step(dt)
        if valve.at_target():
            break
    if not valve.at_target():
        raise AlignmentError("混水阀未到位，禁止启动循环泵", component="valve")
    target_flow = pump.start(speed_pct)
    return {
        "ok": True,
        "valve": move.as_dict(),
        "position_pct": round(valve.position_pct(), 2),
        "target_flow_t_h": round(target_flow, 2),
    }


def stop_pump_before_valve(pump: Pump, valve: Valve, dt: float = 1.0) -> dict:
    """先停泵并等流量归零，再允许关阀。"""

    pump.stop()
    for _ in range(MAX_STEPS):
        pump.step(dt)
        if pump.idle():
            break
    if not pump.idle():
        raise InterlockError("循环泵未停稳，禁止关闭混水阀", component="pump")
    valve.set_target(0.0)
    return {
        "ok": True,
        "flow_t_h": round(pump.flow_t_h(), 2),
        "valve_target_pct": round(valve.target_pct(), 2),
    }
