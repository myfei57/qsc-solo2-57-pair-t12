"""热源调整入口。

一次调整要么把温度与流量都写进去，要么一个都不写。这里把"越界校验"和"整体
写入"放在同一个调用里，校验失败时不触碰任何字段，返回的 :class:`Adjustment`
里带出被拒的原因，由平台写审计。并发调用不会互相看见中间态。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import PlantError
from .source import HeatSource


@dataclass(frozen=True)
class Adjustment:
    """一次调质调量的结果。"""

    ok: bool
    temperature_c: float
    flow_t_h: float
    source: str
    violations: list[str]

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "temperature_c": round(self.temperature_c, 2),
            "flow_t_h": round(self.flow_t_h, 2),
            "source": self.source,
            "violations": list(self.violations),
        }


def apply_adjustment(
    source: HeatSource,
    target_temp_c: float,
    target_flow_t_h: float,
    origin: str = "manual",
) -> Adjustment:
    """原子地把供温与流量调整到目标值。"""

    try:
        temperature, flow = source.adjust(target_temp_c, target_flow_t_h)
    except PlantError as error:
        snapshot = source.snapshot()
        return Adjustment(
            ok=False,
            temperature_c=snapshot.temperature_c,
            flow_t_h=snapshot.flow_t_h,
            source=origin,
            violations=[error.message],
        )
    return Adjustment(ok=True, temperature_c=temperature, flow_t_h=flow, source=origin, violations=[])
