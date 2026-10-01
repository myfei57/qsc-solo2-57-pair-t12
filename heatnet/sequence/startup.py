"""投运编排。

气象推送必须先更新曲线，热源再按新曲线调质；调质确认之后才允许调量，调量完成
一次网才跟随；随后按"先补后定"把压力拉回目标带，最后跑一个循环建立流量。任何
一步失败都停在原地，不带着半截状态继续往下走。
"""

from __future__ import annotations

from ..errors import PlantError
from ..primary.network import PrimaryNetwork
from ..pump.pump import Pump
from ..secondary.cycle import run_cycle
from ..secondary.loop import SecondaryLoop
from ..secondary.makeup import makeup_then_pressurise
from ..source.source import HeatSource
from ..source.weather import WeatherPush, push_weather
from ..store.state import DurableState
from ..temp.curve import HeatCurve
from ..valve.valve import Valve

MAX_STEPS = 1200


def startup_plant(
    source: HeatSource,
    curve: HeatCurve,
    network: PrimaryNetwork,
    loop: SecondaryLoop,
    pump: Pump,
    valve: Valve,
    durable: DurableState,
    outdoor_c: float,
    now: float,
    demand_pct: float = 60.0,
    dt: float = 1.0,
) -> dict:
    """把整条调度链从冷态带到带负荷。"""

    steps: list[dict] = []
    violations: list[str] = []

    weather = push_weather(source, curve, WeatherPush(outdoor_c, now), now)
    steps.extend(weather["steps"])
    violations.extend(weather["violations"])
    if not weather["ok"]:
        return {"ok": False, "steps": steps, "violations": violations, "stage": "weather"}

    for _ in range(MAX_STEPS):
        source.settle_quality(curve.supply_c(), dt)
        if source.quality_confirmed():
            break
    steps.append(
        {
            "component": "source",
            "action": "confirm_quality",
            "detail": {
                "temperature_c": round(source.temperature_c(), 2),
                "hold_s": round(source.quality_hold_s(), 3),
                "confirmed": source.quality_confirmed(),
            },
        }
    )
    if not source.quality_confirmed():
        violations.append("quality_not_confirmed")
        return {"ok": False, "steps": steps, "violations": violations, "stage": "quality"}

    flow = network.baseline_t_h() * max(0.0, min(1.0, demand_pct / 100.0))
    try:
        source.set_flow(flow)
    except PlantError as error:
        violations.append(error.message)
        return {"ok": False, "steps": steps, "violations": violations, "stage": "quantity"}
    network.set_supply(source.temperature_c())
    network.set_return(loop.return_c())
    network.set_flow(source.flow_t_h())
    steps.append(
        {
            "component": "primary",
            "action": "follow_source",
            "detail": {"flow_t_h": round(source.flow_t_h(), 2), "supply_c": round(source.temperature_c(), 2)},
        }
    )

    makeup = makeup_then_pressurise(loop, dt)
    steps.extend(makeup["steps"])
    violations.extend(makeup["violations"])
    if not makeup["ok"]:
        return {"ok": False, "steps": steps, "violations": violations, "stage": "makeup"}

    cycle = run_cycle(loop, pump, valve, durable, dt)
    steps.extend(cycle["steps"])
    violations.extend(cycle["violations"])
    if not cycle["ok"]:
        return {"ok": False, "steps": steps, "violations": violations, "stage": "cycle"}

    return {
        "ok": not violations,
        "steps": steps,
        "violations": violations,
        "stage": "done",
        "flow_t_h": round(source.flow_t_h(), 2),
        "supply_c": round(source.temperature_c(), 2),
        "return_c": round(loop.return_c(), 2),
    }
