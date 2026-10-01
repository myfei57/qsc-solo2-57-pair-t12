"""配额结算行。

结算按站给出本期热量与折算费用，只读总账，不改任何状态。费率固定为基准费率，
超过配额的部分按倍率计费，结算行同时给出超配额占比，便于值班员核对。
"""

from __future__ import annotations

from .quota import QuotaLedger

BASE_RATE = 32.0
OVERAGE_MULTIPLIER = 1.6


def billing_lines(ledger: QuotaLedger, quota_mwh: float) -> list[dict]:
    """按站生成结算行（含超配额折算）。"""

    cap = max(0.0, float(quota_mwh))
    lines: list[dict] = []
    for station in ledger.stations():
        used = ledger.allocated_mwh(station)
        within = min(used, cap)
        overage = max(0.0, used - cap)
        charge = within * BASE_RATE + overage * BASE_RATE * OVERAGE_MULTIPLIER
        lines.append(
            {
                "station": station,
                "mwh": round(used, 4),
                "quota_mwh": round(cap, 4),
                "overage_mwh": round(overage, 4),
                "charge": round(charge, 2),
            }
        )
    return lines
