"""平台配置。

配置来自 JSON 文件（标准库解析），覆盖热源供温带与调质确认时间、供热曲线的
室外温度区间与过期时间、换热站混水阀行程与批量确认时间、一次网流量基线与
调度速率、二次网补水定压带、阀门行程公差、循环泵升速斜率、定压基线范围与
热量表回绕阈值，以及状态存储目录。任何缺失或越界取值都在装配阶段抛出
:class:`ConfigError`，不允许带着半份配置启动控制链。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import ConfigError

_MISSING = object()


def _section(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    if value is None:
        raise ConfigError(f"配置缺少段落 {key!r}", component="config")
    if not isinstance(value, Mapping):
        raise ConfigError(f"配置段落 {key!r} 必须是映射", component="config")
    return value


def _number(section: Mapping[str, Any], key: str, *, minimum: float | None = None) -> float:
    value = section.get(key, _MISSING)
    if value is _MISSING:
        raise ConfigError(f"配置缺少字段 {key!r}", component="config")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"配置字段 {key!r} 必须是数值", component="config")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ConfigError(f"配置字段 {key!r} 不得小于 {minimum}", component="config")
    return number


@dataclass(frozen=True)
class SourceLimits:
    """热源供温带、流量边界与调质确认约束。"""

    supply_target_c: float
    supply_max_c: float
    return_min_c: float
    flow_min_t_h: float
    flow_max_t_h: float
    quality_confirm_s: float
    adjust_rate_c_s: float

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> "SourceLimits":
        limits = cls(
            supply_target_c=_number(section, "supply_target_c", minimum=1.0),
            supply_max_c=_number(section, "supply_max_c", minimum=1.0),
            return_min_c=_number(section, "return_min_c", minimum=0.0),
            flow_min_t_h=_number(section, "flow_min_t_h", minimum=1.0),
            flow_max_t_h=_number(section, "flow_max_t_h", minimum=1.0),
            quality_confirm_s=_number(section, "quality_confirm_s", minimum=0.1),
            adjust_rate_c_s=_number(section, "adjust_rate_c_s", minimum=0.01),
        )
        if limits.supply_target_c >= limits.supply_max_c:
            raise ConfigError("热源目标供温必须低于上限", component="config")
        if limits.return_min_c >= limits.supply_target_c:
            raise ConfigError("回水下限必须低于目标供温", component="config")
        if limits.flow_min_t_h >= limits.flow_max_t_h:
            raise ConfigError("流量下限必须小于上限", component="config")
        return limits

    def overtemperature(self, temperature_c: float) -> bool:
        """供温是否越上限。"""

        return float(temperature_c) > self.supply_max_c

    def flow_in_range(self, flow_t_h: float) -> bool:
        """流量是否落在可信区间内。"""

        return self.flow_min_t_h <= float(flow_t_h) <= self.flow_max_t_h


@dataclass(frozen=True)
class CurveLimits:
    """供热曲线的室外温度区间与新鲜度约束。"""

    outdoor_min_c: float
    outdoor_max_c: float
    supply_low_c: float
    supply_high_c: float
    stale_after_s: float

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> "CurveLimits":
        limits = cls(
            outdoor_min_c=_number(section, "outdoor_min_c"),
            outdoor_max_c=_number(section, "outdoor_max_c"),
            supply_low_c=_number(section, "supply_low_c", minimum=1.0),
            supply_high_c=_number(section, "supply_high_c", minimum=1.0),
            stale_after_s=_number(section, "stale_after_s", minimum=1.0),
        )
        if limits.outdoor_min_c >= limits.outdoor_max_c:
            raise ConfigError("室外温度下限必须小于上限", component="config")
        if limits.supply_low_c >= limits.supply_high_c:
            raise ConfigError("曲线低温供温必须小于高温供温", component="config")
        return limits

    def outdoor_in_range(self, outdoor_c: float) -> bool:
        """室外温度是否落在曲线适用区间内。"""

        return self.outdoor_min_c <= float(outdoor_c) <= self.outdoor_max_c


@dataclass(frozen=True)
class StationLimits:
    """换热站混水阀行程、设定点带与批量确认约束。"""

    setpoint_c: float
    setpoint_band_c: float
    mix_travel_pct_s: float
    batch_confirm_s: float

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> "StationLimits":
        return cls(
            setpoint_c=_number(section, "setpoint_c", minimum=1.0),
            setpoint_band_c=_number(section, "setpoint_band_c", minimum=0.1),
            mix_travel_pct_s=_number(section, "mix_travel_pct_s", minimum=0.1),
            batch_confirm_s=_number(section, "batch_confirm_s", minimum=0.1),
        )

    def at_setpoint(self, temperature_c: float) -> bool:
        """二次侧供温是否落在设定点带内。"""

        return abs(float(temperature_c) - self.setpoint_c) <= self.setpoint_band_c

@dataclass(frozen=True)
class PrimaryLimits:
    """一次网流量基线、容差与调度速率。"""

    flow_baseline_t_h: float
    flow_tolerance_t_h: float
    dispatch_rate_pct_s: float

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> "PrimaryLimits":
        limits = cls(
            flow_baseline_t_h=_number(section, "flow_baseline_t_h", minimum=1.0),
            flow_tolerance_t_h=_number(section, "flow_tolerance_t_h", minimum=0.1),
            dispatch_rate_pct_s=_number(section, "dispatch_rate_pct_s", minimum=0.1),
        )
        if limits.flow_tolerance_t_h >= limits.flow_baseline_t_h:
            raise ConfigError("流量容差必须小于基线", component="config")
        return limits

    def low_flow_threshold(self, baseline_t_h: float) -> float:
        """按当前基线给出低流量联锁门限。"""

        return float(baseline_t_h) - self.flow_tolerance_t_h

@dataclass(frozen=True)
class SecondaryLimits:
    """二次网补水定压带与回水温度目标。"""

    makeup_target_kpa: float
    makeup_min_kpa: float
    makeup_max_kpa: float
    makeup_confirm_s: float
    return_target_c: float

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> "SecondaryLimits":
        limits = cls(
            makeup_target_kpa=_number(section, "makeup_target_kpa", minimum=1.0),
            makeup_min_kpa=_number(section, "makeup_min_kpa", minimum=1.0),
            makeup_max_kpa=_number(section, "makeup_max_kpa", minimum=1.0),
            makeup_confirm_s=_number(section, "makeup_confirm_s", minimum=0.1),
            return_target_c=_number(section, "return_target_c", minimum=1.0),
        )
        if not limits.makeup_min_kpa < limits.makeup_target_kpa < limits.makeup_max_kpa:
            raise ConfigError("补水定压带必须满足 下限 < 目标 < 上限", component="config")
        return limits

    def needs_makeup(self, pressure_kpa: float) -> bool:
        """定压是否跌破补水门限。"""

        return float(pressure_kpa) < self.makeup_min_kpa

    def overpressure(self, pressure_kpa: float) -> bool:
        """定压是否越上限。"""

        return float(pressure_kpa) > self.makeup_max_kpa


@dataclass(frozen=True)
class ValveLimits:
    """阀门行程速率与到位公差。"""

    travel_pct_s: float
    settle_band_pct: float

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> "ValveLimits":
        return cls(
            travel_pct_s=_number(section, "travel_pct_s", minimum=0.1),
            settle_band_pct=_number(section, "settle_band_pct", minimum=0.1),
        )

    def settled(self, position_pct: float, target_pct: float) -> bool:
        """开度是否已经落在到位公差内。"""

        return abs(float(position_pct) - float(target_pct)) <= self.settle_band_pct


@dataclass(frozen=True)
class PumpLimits:
    """循环泵升速斜率与转速边界。"""

    ramp_t_h_s: float
    min_speed_pct: float
    max_speed_pct: float

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> "PumpLimits":
        limits = cls(
            ramp_t_h_s=_number(section, "ramp_t_h_s", minimum=0.1),
            min_speed_pct=_number(section, "min_speed_pct", minimum=0.0),
            max_speed_pct=_number(section, "max_speed_pct", minimum=1.0),
        )
        if limits.min_speed_pct >= limits.max_speed_pct:
            raise ConfigError("泵转速下限必须小于上限", component="config")
        return limits


@dataclass(frozen=True)
class PressureLimits:
    """定压基线的许可范围与改造确认时间。"""

    baseline_min_kpa: float
    baseline_max_kpa: float
    retrofit_confirm_s: float

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> "PressureLimits":
        limits = cls(
            baseline_min_kpa=_number(section, "baseline_min_kpa", minimum=1.0),
            baseline_max_kpa=_number(section, "baseline_max_kpa", minimum=1.0),
            retrofit_confirm_s=_number(section, "retrofit_confirm_s", minimum=0.1),
        )
        if limits.baseline_min_kpa >= limits.baseline_max_kpa:
            raise ConfigError("定压基线下限必须小于上限", component="config")
        return limits

    def in_range(self, baseline_kpa: float) -> bool:
        """基线是否落在许可范围内。"""

        return self.baseline_min_kpa <= float(baseline_kpa) <= self.baseline_max_kpa


@dataclass(frozen=True)
class QuotaLimits:
    """热量表回绕阈值与结算周期。"""

    meter_wrap_mwh: float
    sample_period_s: float
    period_hours: float

    @classmethod
    def from_mapping(cls, section: Mapping[str, Any]) -> "QuotaLimits":
        return cls(
            meter_wrap_mwh=_number(section, "meter_wrap_mwh", minimum=1.0),
            sample_period_s=_number(section, "sample_period_s", minimum=1.0),
            period_hours=_number(section, "period_hours", minimum=0.1),
        )


@dataclass(frozen=True)
class PlatformConfig:
    """一份完整的平台配置。"""

    name: str
    storage_root: str
    source: SourceLimits
    curve: CurveLimits
    station: StationLimits
    primary: PrimaryLimits
    secondary: SecondaryLimits
    valve: ValveLimits
    pump: PumpLimits
    pressure: PressureLimits
    quota: QuotaLimits

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "PlatformConfig":
        meta = _section(mapping, "platform")
        name = meta.get("name")
        storage_root = meta.get("storage_root")
        if not isinstance(name, str) or not name:
            raise ConfigError("platform.name 必须是非空字符串", component="config")
        if not isinstance(storage_root, str) or not storage_root:
            raise ConfigError("platform.storage_root 必须是非空字符串", component="config")

        limits = _section(mapping, "limits")
        return cls(
            name=name,
            storage_root=storage_root,
            source=SourceLimits.from_mapping(_section(limits, "source")),
            curve=CurveLimits.from_mapping(_section(limits, "curve")),
            station=StationLimits.from_mapping(_section(limits, "station")),
            primary=PrimaryLimits.from_mapping(_section(limits, "primary")),
            secondary=SecondaryLimits.from_mapping(_section(limits, "secondary")),
            valve=ValveLimits.from_mapping(_section(limits, "valve")),
            pump=PumpLimits.from_mapping(_section(limits, "pump")),
            pressure=PressureLimits.from_mapping(_section(limits, "pressure")),
            quota=QuotaLimits.from_mapping(_section(limits, "quota")),
        )


def load_config(path: str) -> PlatformConfig:
    """从 JSON 文件读取配置。"""

    if not os.path.isfile(path):
        raise ConfigError(f"配置文件不存在: {path}", component="config")
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, Mapping):
        raise ConfigError("配置文件顶层必须是映射", component="config")
    return PlatformConfig.from_mapping(raw)


def default_config() -> PlatformConfig:
    """内置默认配置，供未指定配置文件时装配使用。"""

    return PlatformConfig(
        name="heatnet",
        storage_root="var/state",
        source=SourceLimits(92.0, 115.0, 35.0, 900.0, 4200.0, 12.0, 0.35),
        curve=CurveLimits(-26.0, 18.0, 55.0, 95.0, 1800.0),
        station=StationLimits(60.0, 2.5, 9.0, 8.0),
        primary=PrimaryLimits(2400.0, 180.0, 4.0),
        secondary=SecondaryLimits(320.0, 260.0, 420.0, 10.0, 45.0),
        valve=ValveLimits(12.0, 1.5),
        pump=PumpLimits(40.0, 20.0, 100.0),
        pressure=PressureLimits(240.0, 430.0, 6.0),
        quota=QuotaLimits(100000.0, 30.0, 24.0),
    )


def config_to_mapping(cfg: PlatformConfig) -> dict:
    """把配置还原成可打印的映射。"""

    return {
        "platform": {"name": cfg.name, "storage_root": cfg.storage_root},
        "limits": {
            "source": {
                "supply_target_c": cfg.source.supply_target_c,
                "supply_max_c": cfg.source.supply_max_c,
                "return_min_c": cfg.source.return_min_c,
                "flow_min_t_h": cfg.source.flow_min_t_h,
                "flow_max_t_h": cfg.source.flow_max_t_h,
                "quality_confirm_s": cfg.source.quality_confirm_s,
                "adjust_rate_c_s": cfg.source.adjust_rate_c_s,
            },
            "curve": {
                "outdoor_min_c": cfg.curve.outdoor_min_c,
                "outdoor_max_c": cfg.curve.outdoor_max_c,
                "supply_low_c": cfg.curve.supply_low_c,
                "supply_high_c": cfg.curve.supply_high_c,
                "stale_after_s": cfg.curve.stale_after_s,
            },
            "station": {
                "setpoint_c": cfg.station.setpoint_c,
                "setpoint_band_c": cfg.station.setpoint_band_c,
                "mix_travel_pct_s": cfg.station.mix_travel_pct_s,
                "batch_confirm_s": cfg.station.batch_confirm_s,
            },
            "primary": {
                "flow_baseline_t_h": cfg.primary.flow_baseline_t_h,
                "flow_tolerance_t_h": cfg.primary.flow_tolerance_t_h,
                "dispatch_rate_pct_s": cfg.primary.dispatch_rate_pct_s,
            },
            "secondary": {
                "makeup_target_kpa": cfg.secondary.makeup_target_kpa,
                "makeup_min_kpa": cfg.secondary.makeup_min_kpa,
                "makeup_max_kpa": cfg.secondary.makeup_max_kpa,
                "makeup_confirm_s": cfg.secondary.makeup_confirm_s,
                "return_target_c": cfg.secondary.return_target_c,
            },
            "valve": {
                "travel_pct_s": cfg.valve.travel_pct_s,
                "settle_band_pct": cfg.valve.settle_band_pct,
            },
            "pump": {
                "ramp_t_h_s": cfg.pump.ramp_t_h_s,
                "min_speed_pct": cfg.pump.min_speed_pct,
                "max_speed_pct": cfg.pump.max_speed_pct,
            },
            "pressure": {
                "baseline_min_kpa": cfg.pressure.baseline_min_kpa,
                "baseline_max_kpa": cfg.pressure.baseline_max_kpa,
                "retrofit_confirm_s": cfg.pressure.retrofit_confirm_s,
            },
            "quota": {
                "meter_wrap_mwh": cfg.quota.meter_wrap_mwh,
                "sample_period_s": cfg.quota.sample_period_s,
                "period_hours": cfg.quota.period_hours,
            },
        },
    }
