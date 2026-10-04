"""多源气象合成与兜底。

平台同时接几家气象预报，每个合成轮次把各家读数并成一条室外温度序列。选源规则
是定死的：**新鲜度是硬门槛**（过期、未来、越界、迟到的报文直接作废，不参与排
序），**偏差是排序依据**（以当轮新鲜报文的中位数为基准，偏差带内的才可信，按
偏差平方反比加权合成）——再新鲜的野值也进不了序列。

某家缺报算部分失败：这家本轮不参与合成，也不许拿估计值凑数，只在健康度里记一
笔缺报。全部来源都不可信时按时段兜底：保守时段（默认深夜到凌晨）切保守经验曲
线（贴着曲线适用区间最冷端留一档余量，供热宁可偏暖）；其余时段沿用上一版合成
值撑着；连上一版都没有时一律按保守值处理。

时序约束：合成代际只在曲线真正应用之后才递增，晚于已应用版本的报文按迟到剔除，
序列不允许回退。合成序列、曲线与审计因此始终是同一份值。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace

from ..config import CurveLimits, FusionLimits
from ..errors import ConfigError, PlantError
from ..temp.curve import HeatCurve
from ..temp.table import CurveTable
from .source import HeatSource

MODE_FUSED = "fused"
MODE_HOLD = "hold_last"
MODE_CONSERVATIVE = "conservative"

# 降温预警只在观测窗足够长时才外推，避免把几秒钟的抖动放大成几小时的寒潮。
_MIN_WINDOW_RATIO = 0.25


@dataclass(frozen=True)
class ProviderReport:
    """一家预报源的一帧报文。"""

    provider: str
    outdoor_c: float
    issued_at: float

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "outdoor_c": round(self.outdoor_c, 2),
            "issued_at": round(self.issued_at, 3),
        }


@dataclass(frozen=True)
class FusionPoint:
    """合成序列里的一代。"""

    epoch: int
    ts: float
    outdoor_c: float
    mode: str

    def as_dict(self) -> dict:
        return {
            "epoch": self.epoch,
            "ts": round(self.ts, 3),
            "outdoor_c": round(self.outdoor_c, 2),
            "mode": self.mode,
        }


@dataclass(frozen=True)
class FusionDecision:
    """一轮合成的结论；``commit`` 之后才带代际与降温预警。"""

    mode: str
    outdoor_c: float
    issued_at: float
    trusted: tuple[str, ...]
    missing: tuple[str, ...]
    excluded: tuple[dict, ...]
    fallback_reason: str = ""
    epoch: int = 0
    alert: dict | None = None

    @property
    def partial(self) -> bool:
        """本轮是否属于部分失败（有缺报或被剔除的报文）。"""

        return bool(self.missing or self.excluded)

    def as_dict(self) -> dict:
        return {
            "epoch": self.epoch,
            "mode": self.mode,
            "outdoor_c": round(self.outdoor_c, 2),
            "issued_at": round(self.issued_at, 3),
            "trusted": list(self.trusted),
            "missing": list(self.missing),
            "excluded": [dict(item) for item in self.excluded],
            "partial": self.partial,
            "fallback_reason": self.fallback_reason,
            "alert": self.alert,
        }


class WeatherFusion:
    """多源气象合成器：评估报文、合成序列、按时段兜底、识别降温趋势。"""

    def __init__(self, limits: FusionLimits, curve_limits: CurveLimits) -> None:
        conservative = limits.conservative_outdoor_c(curve_limits)
        if not curve_limits.outdoor_in_range(conservative):
            raise ConfigError(
                f"保守经验曲线取值 {conservative:.1f}℃ 超出曲线适用区间 "
                f"[{curve_limits.outdoor_min_c:.1f}, {curve_limits.outdoor_max_c:.1f}]",
                component="config",
            )
        self._limits = limits
        self._curve_limits = curve_limits
        self._table = CurveTable(curve_limits)
        self._lock = threading.RLock()
        self._series: list[FusionPoint] = []
        self._epoch = 0
        # 已应用序列里最新一帧报文的签发时刻；比它老的报文一律算迟到。
        self._last_issued_at = 0.0
        self._stats = {
            name: {
                "received": 0,
                "missing": 0,
                "excluded": 0,
                "last_issued_at": 0.0,
                "last_exclusion": "",
            }
            for name in limits.providers
        }
        self._last_decision: FusionDecision | None = None

    # ---- 合成 ---------------------------------------------------------

    def decide(self, reports: list[ProviderReport], now: float) -> FusionDecision:
        """评估一轮报文并给出结论；只记健康度，不落序列（序列由 :meth:`commit` 落）。"""

        with self._lock:
            now = float(now)
            accepted: dict[str, ProviderReport] = {}
            excluded: list[dict] = []
            for report in reports:
                reason = self._gate(report, accepted, now)
                if reason is None:
                    accepted[report.provider] = report
                else:
                    excluded.append({"provider": report.provider, "reason": reason})

            missing = tuple(
                name
                for name in self._limits.providers
                if name not in accepted and all(item["provider"] != name for item in excluded)
            )

            trusted: list[ProviderReport] = []
            if accepted:
                median = _median([report.outdoor_c for report in accepted.values()])
                for report in accepted.values():
                    if abs(report.outdoor_c - median) <= self._limits.max_deviation_c:
                        trusted.append(report)
                    else:
                        excluded.append({"provider": report.provider, "reason": "divergent"})

            self._count_health(trusted, missing, excluded)

            if len(trusted) >= self._limits.min_providers:
                weights = []
                for report in trusted:
                    deviation = abs(report.outdoor_c - median)
                    weights.append(1.0 / (1.0 + deviation * deviation))
                outdoor = sum(
                    report.outdoor_c * weight for report, weight in zip(trusted, weights)
                ) / sum(weights)
                return FusionDecision(
                    mode=MODE_FUSED,
                    outdoor_c=outdoor,
                    issued_at=max(report.issued_at for report in trusted),
                    trusted=tuple(report.provider for report in trusted),
                    missing=missing,
                    excluded=tuple(excluded),
                )

            if self._limits.use_conservative(now):
                mode, reason = MODE_CONSERVATIVE, "all_untrusted_in_conservative_hours"
            elif self._series:
                mode, reason = MODE_HOLD, "all_untrusted_hold_last"
            else:
                mode, reason = MODE_CONSERVATIVE, "no_previous_value"
            outdoor = (
                self._limits.conservative_outdoor_c(self._curve_limits)
                if mode == MODE_CONSERVATIVE
                else self._series[-1].outdoor_c
            )
            return FusionDecision(
                mode=mode,
                outdoor_c=outdoor,
                issued_at=now,
                trusted=(),
                missing=missing,
                excluded=tuple(excluded),
                fallback_reason=reason,
            )

    def commit(self, draft: FusionDecision, now: float) -> FusionDecision:
        """曲线已按 ``draft`` 取值更新后调用：落序列、定代际、算降温预警。"""

        with self._lock:
            self._epoch += 1
            point = FusionPoint(self._epoch, float(now), draft.outdoor_c, draft.mode)
            self._series.append(point)
            if len(self._series) > self._limits.series_limit:
                del self._series[: len(self._series) - self._limits.series_limit]
            if draft.mode == MODE_FUSED:
                self._last_issued_at = max(self._last_issued_at, draft.issued_at)
            decision = replace(draft, epoch=self._epoch, alert=self._cooling_alert(point))
            self._last_decision = decision
            return decision

    # ---- 查询 ---------------------------------------------------------

    def series(self, limit: int = 96) -> list[dict]:
        """返回最近的合成序列（按时间升序），供控制台展示。"""

        with self._lock:
            return [point.as_dict() for point in self._series[-limit:]]

    def health(self) -> list[dict]:
        """返回各预报源的累计健康度。"""

        with self._lock:
            return [
                {
                    "provider": name,
                    "received": stats["received"],
                    "missing": stats["missing"],
                    "excluded": stats["excluded"],
                    "last_issued_at": round(stats["last_issued_at"], 3),
                    "last_exclusion": stats["last_exclusion"],
                }
                for name, stats in self._stats.items()
            ]

    def last_decision(self) -> dict | None:
        """返回最近一轮已落序列的结论。"""

        with self._lock:
            return self._last_decision.as_dict() if self._last_decision else None

    def report(self) -> dict:
        """汇总定死的选源规则、各家健康度、合成序列与最近一轮结论。"""

        with self._lock:
            return {
                "rules": {
                    "selection": "freshness_gate_then_deviation_weight",
                    "fresh_after_s": self._limits.fresh_after_s,
                    "max_deviation_c": self._limits.max_deviation_c,
                    "min_providers": self._limits.min_providers,
                    "fallback": "conservative_hours_else_hold_last",
                    "conservative_hours": list(self._limits.conservative_hours),
                    "conservative_outdoor_c": round(
                        self._limits.conservative_outdoor_c(self._curve_limits), 2
                    ),
                    "alert_drop_c": self._limits.alert_drop_c,
                    "alert_horizon_s": self._limits.alert_horizon_s,
                },
                "providers": self.health(),
                "series": self.series(self._limits.series_limit),
                "last": self.last_decision(),
            }

    # ---- 内部 ---------------------------------------------------------

    def _gate(self, report: ProviderReport, accepted: dict[str, ProviderReport], now: float) -> str | None:
        """新鲜度与合法性硬门槛；返回 ``None`` 表示通过，否则给出剔除原因。"""

        name = report.provider
        if name not in self._stats:
            return "unknown_provider"
        if name in accepted:
            return "duplicate"
        if report.issued_at > now:
            return "future_dated"
        if now - report.issued_at > self._limits.fresh_after_s:
            return "stale"
        if not self._curve_limits.outdoor_in_range(report.outdoor_c):
            return "out_of_range"
        if report.issued_at <= self._last_issued_at:
            return "late"
        return None

    def _count_health(
        self,
        trusted: list[ProviderReport],
        missing: tuple[str, ...],
        excluded: list[dict],
    ) -> None:
        """按本轮结论更新各家健康度（缺报只计数，绝不估值补位）。"""

        trusted_names = {report.provider for report in trusted}
        for report in trusted:
            stats = self._stats[report.provider]
            stats["received"] += 1
            stats["last_issued_at"] = max(stats["last_issued_at"], report.issued_at)
        for item in excluded:
            stats = self._stats.get(item["provider"])
            if stats is None:
                continue
            stats["excluded"] += 1
            stats["last_exclusion"] = item["reason"]
        for name in missing:
            if name not in trusted_names:
                self._stats[name]["missing"] += 1

    def _cooling_alert(self, point: FusionPoint) -> dict | None:
        """按合成序列的降温趋势外推，提前给出预警与应提的供温档。

        只用 ``fused`` 模式的点做趋势：兜底切换本身会造成序列跳变，拿它算趋势
        会把"切了保守曲线"误报成"寒潮"。观测窗不足预警周期的四分之一不外推。
        """

        horizon = self._limits.alert_horizon_s
        window = [
            item
            for item in self._series
            if item.mode == MODE_FUSED and item.ts >= point.ts - horizon
        ]
        if len(window) < 2:
            return None
        past = window[0]
        span = point.ts - past.ts
        if span < horizon * _MIN_WINDOW_RATIO:
            return None
        drop = past.outdoor_c - point.outdoor_c
        if drop <= 0:
            return None
        projected = drop * horizon / span
        if projected < self._limits.alert_drop_c:
            return None
        supply_now = self._table.interpolate(point.outdoor_c)
        supply_target = self._table.interpolate(point.outdoor_c - projected)
        return {
            "kind": "cooling_trend",
            "drop_c": round(projected, 2),
            "horizon_s": round(horizon, 1),
            "outdoor_now_c": round(point.outdoor_c, 2),
            "outdoor_projected_c": round(point.outdoor_c - projected, 2),
            "supply_now_c": round(supply_now, 2),
            "supply_target_c": round(supply_target, 2),
        }


def _median(values: list[float]) -> float:
    """返回一组读数的中位数（合成基准，抗个别野值）。"""

    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def push_fused_weather(
    source: HeatSource,
    curve: HeatCurve,
    fusion: WeatherFusion,
    reports: list[ProviderReport],
    now: float,
) -> dict:
    """合成一轮多源气象，按结论更新曲线并让热源点火。

    顺序定死：先合成评估，再更新曲线，曲线确认后合成序列才落代际，最后热源按
    新曲线点火——曲线校验失败时整轮作废，序列与曲线不会各走各的。
    """

    draft = fusion.decide(reports, now)
    try:
        forecast = curve.apply_forecast(draft.outdoor_c, now)
    except PlantError as error:
        return {
            "ok": False,
            "steps": [],
            "violations": [error.message],
            "mode": draft.mode,
            "partial": draft.partial,
            "decision": draft.as_dict(),
            "alert": None,
        }
    decision = fusion.commit(draft, now)
    steps: list[dict] = [
        {
            "component": "weather",
            "action": "fuse",
            "detail": {
                "mode": decision.mode,
                "fusion_epoch": decision.epoch,
                "outdoor_c": round(decision.outdoor_c, 2),
                "trusted": len(decision.trusted),
                "missing": len(decision.missing),
                "excluded": len(decision.excluded),
                "partial": decision.partial,
            },
        },
        {"component": "temp", "action": "apply_forecast", "detail": forecast},
    ]
    violations: list[str] = []

    if curve.is_stale(now):
        violations.append("curve_stale")
        return {
            "ok": False,
            "steps": steps,
            "violations": violations,
            "mode": decision.mode,
            "partial": decision.partial,
            "decision": decision.as_dict(),
            "alert": decision.alert,
            "outdoor_c": forecast["outdoor_c"],
        }

    try:
        fired = source.fire(curve.supply_c())
    except PlantError as error:
        violations.append(error.message)
        return {
            "ok": False,
            "steps": steps,
            "violations": violations,
            "mode": decision.mode,
            "partial": decision.partial,
            "decision": decision.as_dict(),
            "alert": decision.alert,
            "outdoor_c": forecast["outdoor_c"],
        }
    steps.append(
        {
            "component": "source",
            "action": "fire_forecast",
            "detail": {"temperature_c": round(fired, 2)},
        }
    )

    return {
        "ok": not violations,
        "steps": steps,
        "violations": violations,
        "mode": decision.mode,
        "partial": decision.partial,
        "decision": decision.as_dict(),
        "alert": decision.alert,
        "outdoor_c": forecast["outdoor_c"],
        "supply_c": round(curve.supply_c(), 2),
        "epoch": curve.epoch(),
        "fusion_epoch": decision.epoch,
    }
