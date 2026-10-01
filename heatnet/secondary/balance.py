"""水力平衡折算。

末端拿到的热量由流量与供回水温差共同决定：流量不够或温差不够，热量都上不去。
这里只做折算，不判断工况是否合规——判定留给 :class:`SecondaryLoop` 与联锁。
"""

from __future__ import annotations

from dataclasses import dataclass

REFERENCE_FLOW_T_H = 2400.0


@dataclass(frozen=True)
class BalanceReport:
    """一次水力平衡折算结果。"""

    flow_t_h: float
    delta_c: float
    load_kw: float
    flow_ratio: float

    def as_dict(self) -> dict:
        return {
            "flow_t_h": round(self.flow_t_h, 2),
            "delta_c": round(self.delta_c, 2),
            "load_kw": round(self.load_kw, 2),
            "flow_ratio": round(self.flow_ratio, 4),
        }


def hydraulic_balance(flow_t_h: float, supply_c: float, return_c: float) -> BalanceReport:
    """按流量与供回水温差折算热量。"""

    flow = max(0.0, float(flow_t_h))
    delta = float(supply_c) - float(return_c)
    load_kw = flow * delta / 1.163
    return BalanceReport(
        flow_t_h=flow,
        delta_c=delta,
        load_kw=load_kw,
        flow_ratio=flow / REFERENCE_FLOW_T_H,
    )
