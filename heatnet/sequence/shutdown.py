"""停运编排。

停运先把泵停稳、再关混水阀，然后把一次网流量撤掉，最后让热源停机。泵没停稳就
关阀会把泵憋住，热源先停而流量还在会把管网抽空。
"""

from __future__ import annotations

from ..errors import PlantError
from ..primary.network import PrimaryNetwork
from ..pump.pump import Pump
from ..pump.start import stop_pump_before_valve
from ..secondary.loop import SecondaryLoop
from ..source.source import HeatSource
from ..valve.valve import Valve


def shutdown_plant(
    source: HeatSource,
    network: PrimaryNetwork,
    loop: SecondaryLoop,
    pump: Pump,
    valve: Valve,
    reason: str = "planned-shutdown",
) -> dict:
    """从带负荷退回停运。"""

    steps: list[dict] = []
    violations: list[str] = []

    try:
        stopped = stop_pump_before_valve(pump, valve)
    except PlantError as error:
        violations.append(error.message)
        return {"ok": False, "steps": steps, "violations": violations, "stage": "pump"}
    steps.append({"component": "pump", "action": "stop_before_valve", "detail": stopped})

    network.set_flow(0.0)
    network.set_return(loop.return_c())
    steps.append(
        {"component": "primary", "action": "drop_flow", "detail": {"flow_t_h": round(network.flow_t_h(), 2)}}
    )

    try:
        source.trip(reason)
    except PlantError as error:  # pragma: no cover - 停机本身不应失败
        violations.append(error.message)
    steps.append(
        {"component": "source", "action": "trip", "detail": {"state": source.state(), "reason": reason}}
    )

    return {
        "ok": not violations,
        "steps": steps,
        "violations": violations,
        "reason": reason,
        "flow_t_h": round(network.flow_t_h(), 2),
    }
