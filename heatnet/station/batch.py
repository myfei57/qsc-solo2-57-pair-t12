"""批量调节编排。

先按分区优先级排出下发顺序并算出计划，再交给一次网按站独立分配流量，最后逐区
调节。流量分配与阀门动作分两步做，是为了让"计划里的流量"与"执行后的阀位"可以
分别核对。
"""

from __future__ import annotations

from ..primary.flow import StationFlow, batch_flows
from ..primary.network import PrimaryNetwork
from ..primary.order import priority_order
from ..ns.zone import ZoneRegistry
from .mapping import StationMapping
from .service import CancelToken, StationService


def build_plan(
    mapping: StationMapping,
    zones: ZoneRegistry,
    zone_names: list[str],
    demand_pct: float,
) -> list[tuple[str, float]]:
    """按分区优先级排出各站的调节计划。"""

    ordered = priority_order([(name, zones.get(name).setpoint_c) for name in zone_names])
    peak = max((setpoint for _, setpoint in ordered), default=0.0)
    plan: list[tuple[str, float]] = []
    for zone_name, setpoint in ordered:
        share = 1.0 if peak <= 0 else max(0.2, setpoint / peak)
        demand = max(0.0, min(100.0, float(demand_pct) * share))
        for station in mapping.stations_in(zone_name):
            plan.append((station, demand))
    return plan


def run_batch(
    service: StationService,
    mapping: StationMapping,
    zones: ZoneRegistry,
    network: PrimaryNetwork,
    zone_names: list[str],
    demand_pct: float,
    target_c: float,
    cancel: CancelToken | None = None,
    dt: float = 1.0,
) -> dict:
    """算流量、下发分区、汇总结果。"""

    plan = build_plan(mapping, zones, zone_names, demand_pct)
    flows: list[StationFlow] = batch_flows(network, plan)
    ordered = [name for name, _ in priority_order([(n, zones.get(n).setpoint_c) for n in zone_names])]
    network.count_dispatch()
    steps: list[dict] = [
        {"component": "primary", "action": "allocate_flow", "detail": flow.as_dict()} for flow in flows
    ]
    violations: list[str] = []
    adjusted: list[str] = []
    for zone_name in ordered:
        report = service.adjust_zone(mapping, zone_name, target_c, cancel, dt)
        steps.extend(report["steps"])
        violations.extend(report["violations"])
        adjusted.extend(report["adjusted"])
        if not report["ok"]:
            break
    return {
        "ok": not violations,
        "steps": steps,
        "violations": violations,
        "planned": len(plan),
        "adjusted": adjusted,
        "flows": [flow.as_dict() for flow in flows],
    }
