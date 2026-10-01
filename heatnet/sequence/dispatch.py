"""调度下发编排。

调度把目标负荷折算成各站的开度需求，按分区优先级排出计划，交给一次网按站独立
分配流量，再逐区下发。流量基线可以按实测重新标定，标定之后联锁门限同步变化。
"""

from __future__ import annotations

from ..ns.zone import ZoneRegistry
from ..primary.network import PrimaryNetwork
from ..station.batch import run_batch
from ..station.mapping import StationMapping
from ..station.service import CancelToken, StationService


def dispatch_demand(
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
    """按分区下发一次调度。"""

    report = run_batch(
        service, mapping, zones, network, zone_names, demand_pct, target_c, cancel, dt
    )
    return {
        **report,
        "demand_pct": round(float(demand_pct), 2),
        "target_c": round(float(target_c), 2),
        "flow_t_h": round(network.flow_t_h(), 2),
        "threshold_t_h": round(network.threshold_t_h(), 2),
    }


def recalibrate_flow(network: PrimaryNetwork, measured_t_h: float) -> dict:
    """按实测流量重新标定一次网基线。"""

    baseline = network.recalibrate(measured_t_h)
    return {
        "baseline_t_h": round(baseline, 2),
        "threshold_t_h": round(network.threshold_t_h(), 2),
        "recalibrations": network.recalibrations(),
    }
