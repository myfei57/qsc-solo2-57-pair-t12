"""补水定压顺序。

先补后定：压力低于补水门限时先把水补进去，压力进到目标带内才允许定压完成。
反过来先判定"定压合格"再补水，判定看到的永远是补压之前的值，流程会一直停在
第一步。
"""

from __future__ import annotations

from .loop import SecondaryLoop

MAX_STEPS = 600


def makeup_then_pressurise(loop: SecondaryLoop, dt: float = 1.0) -> dict:
    """按先补后定的顺序把定压拉回目标带。"""

    steps: list[dict] = []
    violations: list[str] = []
    before = loop.pressure_kpa()

    for _ in range(MAX_STEPS):
        if not loop.needs_makeup():
            break
        loop.makeup_step(dt)
    steps.append(
        {
            "component": "secondary",
            "action": "makeup",
            "detail": {"from_kpa": round(before, 2), "to_kpa": round(loop.pressure_kpa(), 2)},
        }
    )
    if loop.needs_makeup():
        violations.append("makeup_incomplete")
        return {"ok": False, "steps": steps, "violations": violations, "pressure_kpa": loop.pressure_kpa()}

    if loop.overpressure():
        loop.bleed_pressure(loop.pressure_kpa() - loop.limits.makeup_target_kpa)
        steps.append(
            {
                "component": "secondary",
                "action": "bleed",
                "detail": {"pressure_kpa": round(loop.pressure_kpa(), 2)},
            }
        )
    if loop.overpressure():
        violations.append("overpressure")

    return {
        "ok": not violations,
        "steps": steps,
        "violations": violations,
        "pressure_kpa": round(loop.pressure_kpa(), 2),
    }
