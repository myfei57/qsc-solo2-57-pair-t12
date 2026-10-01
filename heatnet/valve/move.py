"""阀门动作的落盘顺序。

先落盘、再改内存：写盘失败时内存开度保持不变，错误向上抛出，调用方可以原样
重试；反过来先改内存再写盘，一旦写失败，内存里的开度就比盘上的新，进程重启后
阀门回退到旧位置，与调节结果对不上。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import StorageError
from ..store.state import DurableState
from .valve import Valve


@dataclass(frozen=True)
class ValveMove:
    """一次阀门动作的结果。"""

    ok: bool
    name: str
    position_pct: float
    durable_pct: float
    persisted: bool

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "name": self.name,
            "position_pct": round(self.position_pct, 2),
            "durable_pct": round(self.durable_pct, 2),
            "persisted": self.persisted,
        }


def move_valve(valve: Valve, durable: DurableState, target_pct: float) -> ValveMove:
    """把阀门开到目标开度：先落盘，落盘成功后再改内存。"""

    clamped = max(0.0, min(100.0, float(target_pct)))
    payload = {
        "name": valve.name,
        "position_pct": round(clamped, 4),
        "moves": valve.moves() + 1,
    }
    try:
        durable.save(f"valve/{valve.name}", payload)
    except StorageError:
        valve.reject()
        raise
    position = valve.apply(clamped)
    return ValveMove(
        ok=True,
        name=valve.name,
        position_pct=position,
        durable_pct=clamped,
        persisted=True,
    )


def load_valve(valve: Valve, durable: DurableState) -> float:
    """从落盘状态恢复阀门开度，缺失时保持现值。"""

    raw = durable.load(f"valve/{valve.name}")
    if not raw:
        return valve.position_pct()
    try:
        position = float(raw.get("position_pct", valve.position_pct()))
    except (TypeError, ValueError):
        return valve.position_pct()
    return valve.apply(position)
