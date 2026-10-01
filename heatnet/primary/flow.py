"""一次网流量分配。

每个站的目标流量只跟它自己的目标开度与全网基线有关，因此必须在循环里用局部
变量计算；把中间结果写回 ``network.flow_t_h`` 再作为下一站的起点，越靠后的站
流量越大。全网总流量在全部站算完之后一次性写回。
"""

from __future__ import annotations

from dataclasses import dataclass

from .network import PrimaryNetwork


@dataclass(frozen=True)
class StationFlow:
    """一个站的目标流量。"""

    station: str
    target_pct: float
    flow_t_h: float

    def as_dict(self) -> dict:
        return {
            "station": self.station,
            "target_pct": round(self.target_pct, 2),
            "flow_t_h": round(self.flow_t_h, 2),
        }


def batch_flows(network: PrimaryNetwork, plan: list[tuple[str, float]]) -> list[StationFlow]:
    """按站独立计算目标流量，最后一次性写回全网总流量。"""

    baseline = network.baseline_t_h()
    count = max(1, len(plan))
    flows: list[StationFlow] = []
    total = 0.0
    for station, target_pct in plan:
        share = max(0.0, min(1.0, float(target_pct) / 100.0))
        target = baseline * share / count
        total += target
        flows.append(StationFlow(station=str(station), target_pct=float(target_pct), flow_t_h=target))
    network.set_flow(total)
    return flows
