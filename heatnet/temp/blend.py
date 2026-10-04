"""多源气象融合与兜底切换。

气象只接一家时，推送一断或者飘了，曲线只能跟着飘，值班员凭经验手改。这里同时
维护几家预报源的来报状态，每轮合成先做硬筛，再在可信源里按固定规则合成一条
室外温度序列：

* **选源规则（定死）**：缺报、超新鲜度、与上一版合成值偏差过大是入场门槛，
  门槛之内按"与上一版合成值的偏差"升序排名（平手按源名字典序），合成值取
  可信源读数的中位数。不按新鲜度排名——新鲜但发飘的读数正是要防的事故；
* **缺报只是部分失败**：该家本轮出局并记原因，其余家照常参与合成，不允许
  按缺报那家的旧值或估值凑数；
* **全部不可信时按时段定兜底**：距上一版好值不超过 ``hold_after_s`` 就按上一版
  撑着（``hold``），超过则切保守经验曲线（``fallback``，日变化余弦再向冷侧
  偏置，宁可多供不能欠供）；
* **时序不能乱**：来报 ``issued_at`` 早于上一决策点的拒收，序列点时刻单调不减、
  序号连续，``live → hold → fallback`` 随时间单向推进，任何一家恢复可信即回到
  ``live``；合成只认提交的决策，不允许回头改历史点。

合成序列、供热曲线与审计必须一致：平台先 :meth:`ForecastBlender.commit` 序列点，
再把合成值应用到曲线；曲线校验失败时 :meth:`ForecastBlender.rollback` 把序列点
撤掉，整条推送作废，审计里只留下被拒绝的痕迹，不会出现"序列有、曲线没有"的
分叉。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from ..config import ForecastLimits
from ..errors import ForecastError, InterlockError

MODE_LIVE = "live"
MODE_HOLD = "hold"
MODE_FALLBACK = "fallback"

REASON_MISSING = "missing"
REASON_STALE = "stale"
REASON_DEVIATING = "deviating"
REASON_OUT_OF_ORDER = "out_of_order"


@dataclass(frozen=True)
class ProviderReading:
    """一家预报源最近一次被登记的来报。"""

    outdoor_c: float
    issued_at: float
    received_at: float


@dataclass(frozen=True)
class BlendPoint:
    """合成序列里的一点，落审计与控制台展示都用这份字段。"""

    seq: int
    decided_at: float
    mode: str
    outdoor_c: float
    trusted: tuple[str, ...]
    excluded: dict[str, str]
    drop_c_per_h: float

    def as_dict(self) -> dict:
        return {
            "seq": self.seq,
            "decided_at": round(self.decided_at, 3),
            "mode": self.mode,
            "outdoor_c": round(self.outdoor_c, 2),
            "trusted": list(self.trusted),
            "excluded": dict(self.excluded),
            "drop_c_per_h": round(self.drop_c_per_h, 3),
        }


@dataclass(frozen=True)
class BlendDecision:
    """一轮待提交的合成决策：序列点加上趋势预警结论。"""

    point: BlendPoint
    warning: bool
    projected_outdoor_c: float


class ForecastBlender:
    """多家预报的可信筛选、合成与兜底切换。"""

    def __init__(self, limits: ForecastLimits) -> None:
        self._limits = limits
        self._readings: dict[str, ProviderReading] = {}
        self._rejections: dict[str, int] = {name: 0 for name in limits.providers}
        self._series: list[BlendPoint] = []
        self._last_good: BlendPoint | None = None
        self._undo: tuple[BlendPoint, BlendPoint | None] | None = None

    def ingest(self, provider: str, outdoor_c: float, issued_at: float, now: float) -> dict:
        """登记一家来报；时序倒挂的读数拒收并计数，不参与后续合成。"""

        name = str(provider)
        if name not in self._limits.providers:
            raise ForecastError(f"未登记的预报源 {name!r}", component="temp")
        issued = float(issued_at)
        received = float(now)
        last_decided = self._series[-1].decided_at if self._series else None
        previous = self._readings.get(name)
        if (last_decided is not None and issued < last_decided) or (
            previous is not None and issued <= previous.issued_at
        ):
            self._rejections[name] += 1
            return {
                "provider": name,
                "accepted": False,
                "reason": REASON_OUT_OF_ORDER,
                "outdoor_c": round(float(outdoor_c), 2),
                "issued_at": round(issued, 3),
            }
        self._readings[name] = ProviderReading(float(outdoor_c), issued, received)
        return {
            "provider": name,
            "accepted": True,
            "reason": "",
            "outdoor_c": round(float(outdoor_c), 2),
            "issued_at": round(issued, 3),
        }

    def decide(self, now: float) -> BlendDecision:
        """按各家当前状态算一轮合成决策；只读状态，不落序列。"""

        moment = float(now)
        reference = self._last_good.outdoor_c if self._last_good is not None else None
        ranked: list[tuple[str, float, float]] = []
        excluded: dict[str, str] = {}
        for name in self._limits.providers:
            reading = self._readings.get(name)
            if reading is None or moment - reading.received_at > self._limits.expect_period_s:
                excluded[name] = REASON_MISSING
                continue
            if moment - reading.issued_at > self._limits.fresh_after_s:
                excluded[name] = REASON_STALE
                continue
            deviation = abs(reading.outdoor_c - reference) if reference is not None else 0.0
            if reference is not None and deviation > self._limits.max_deviation_c:
                excluded[name] = REASON_DEVIATING
                continue
            ranked.append((name, reading.outdoor_c, deviation))
        # 选源定死：偏差小者优先，平手按源名字典序，与新鲜度排名无关。
        ranked.sort(key=lambda item: (item[2], item[0]))
        trusted = tuple(name for name, _value, _deviation in ranked)
        if ranked:
            values = sorted(value for _name, value, _deviation in ranked)
            mid = len(values) // 2
            outdoor = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0
            mode = MODE_LIVE
        elif self._last_good is not None and moment - self._last_good.decided_at <= self._limits.hold_after_s:
            outdoor = self._last_good.outdoor_c
            mode = MODE_HOLD
        else:
            outdoor = self.empirical_outdoor_c(moment)
            mode = MODE_FALLBACK
        previous = None
        for point in reversed(self._series):
            if point.decided_at < moment:
                previous = point
                break
        drop_c_per_h = 0.0
        if previous is not None:
            drop_c_per_h = (outdoor - previous.outdoor_c) / (moment - previous.decided_at) * 3600.0
        projected = outdoor + drop_c_per_h * self._limits.warn_horizon_s / 3600.0
        warning = drop_c_per_h < 0.0 and outdoor - projected >= self._limits.warn_drop_c
        last = self._series[-1] if self._series else None
        seq = last.seq + 1 if last is not None else 1
        point = BlendPoint(seq, moment, mode, outdoor, trusted, excluded, drop_c_per_h)
        return BlendDecision(point=point, warning=warning, projected_outdoor_c=projected)

    def commit(self, decision: BlendDecision) -> BlendPoint:
        """把一轮决策落进合成序列；时刻回退或序号跳变一律拒绝。"""

        point = decision.point
        if self._series:
            last = self._series[-1]
            if point.decided_at < last.decided_at:
                raise InterlockError("合成序列时刻不能回退", component="temp")
            if point.seq != last.seq + 1:
                raise InterlockError("合成序列序号必须连续", component="temp")
        elif point.seq != 1:
            raise InterlockError("合成序列必须从 1 开始", component="temp")
        self._undo = (point, self._last_good)
        self._series.append(point)
        if len(self._series) > self._limits.series_limit:
            del self._series[: len(self._series) - self._limits.series_limit]
        if point.mode == MODE_LIVE:
            self._last_good = point
        return point

    def rollback(self, seq: int) -> None:
        """撤销最近一次提交的序列点（曲线校验失败时整条作废）。"""

        if (
            self._undo is None
            or not self._series
            or self._series[-1].seq != seq
            or self._undo[0].seq != seq
        ):
            raise InterlockError("只能撤销最近提交的序列点", component="temp")
        self._series.pop()
        self._last_good = self._undo[1]
        self._undo = None

    def due(self, now: float) -> bool:
        """是否到了该由控制周期补一轮合成决策的时刻。"""

        if not self._series and not self._readings:
            return False
        if not self._series:
            return True
        return float(now) - self._series[-1].decided_at >= self._limits.expect_period_s

    def empirical_outdoor_c(self, now: float) -> float:
        """保守经验曲线：日变化余弦再向冷侧偏置，最暖在 15 时、最冷在 03 时。"""

        moment = time.gmtime(float(now))
        hour = moment.tm_hour + moment.tm_min / 60.0 + moment.tm_sec / 3600.0
        center = self._limits.fallback_mean_c - self._limits.fallback_margin_c
        return center + self._limits.fallback_amplitude_c * math.cos(2.0 * math.pi * (hour - 15.0) / 24.0)

    def providers(self, now: float) -> list[dict]:
        """各家来报状态，供控制台展示与巡检核对。"""

        moment = float(now)
        reference = self._last_good.outdoor_c if self._last_good is not None else None
        report: list[dict] = []
        for name in self._limits.providers:
            reading = self._readings.get(name)
            entry: dict = {"provider": name, "rejections": self._rejections[name]}
            if reading is None:
                entry.update(state=REASON_MISSING, outdoor_c=None, issued_at=None, age_s=None, deviation_c=None)
            else:
                deviation = abs(reading.outdoor_c - reference) if reference is not None else None
                state = "ok"
                if moment - reading.received_at > self._limits.expect_period_s:
                    state = REASON_MISSING
                elif moment - reading.issued_at > self._limits.fresh_after_s:
                    state = REASON_STALE
                elif deviation is not None and deviation > self._limits.max_deviation_c:
                    state = REASON_DEVIATING
                entry.update(
                    state=state,
                    outdoor_c=round(reading.outdoor_c, 2),
                    issued_at=round(reading.issued_at, 3),
                    age_s=round(moment - reading.received_at, 3),
                    deviation_c=None if deviation is None else round(deviation, 2),
                )
            report.append(entry)
        return report

    def series(self, limit: int = 24) -> list[dict]:
        """最近的合成序列点（时间升序）。"""

        return [point.as_dict() for point in self._series[-max(1, limit) :]]

    def report(self, now: float) -> dict:
        """控制台用的一份融合总览：当前模式、各家状态、合成序列与门槛。"""

        last = self._series[-1] if self._series else None
        return {
            "mode": last.mode if last else "idle",
            "providers": self.providers(now),
            "series": self.series(),
            "last_point": last.as_dict() if last else None,
            "last_good": self._last_good.as_dict() if self._last_good else None,
            "limits": {
                "providers": list(self._limits.providers),
                "expect_period_s": self._limits.expect_period_s,
                "fresh_after_s": self._limits.fresh_after_s,
                "max_deviation_c": self._limits.max_deviation_c,
                "hold_after_s": self._limits.hold_after_s,
                "warn_drop_c": self._limits.warn_drop_c,
                "warn_horizon_s": self._limits.warn_horizon_s,
            },
        }
