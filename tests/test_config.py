"""配置解析与校验。"""

from __future__ import annotations

import json

import pytest

from heatnet.config import ConfigError, config_to_mapping, default_config, load_config


def test_default_config_is_consistent():
    config = default_config()
    assert config.source.supply_target_c < config.source.supply_max_c
    assert config.secondary.makeup_min_kpa < config.secondary.makeup_target_kpa
    assert config.curve.outdoor_in_range(-10.0) is True
    assert config.curve.outdoor_in_range(40.0) is False
    assert config.source.flow_in_range(2000.0) is True
    assert config.source.overtemperature(config.source.supply_max_c + 1.0) is True


def test_config_reloads_from_mapping():
    original = default_config()
    restored = type(original).from_mapping(config_to_mapping(original))
    assert restored == original


def test_load_config_reads_json_file(tmp_path):
    path = tmp_path / "heatnet.json"
    path.write_text(json.dumps(config_to_mapping(default_config())), encoding="utf-8")
    loaded = load_config(str(path))
    assert loaded.primary.flow_baseline_t_h == default_config().primary.flow_baseline_t_h


def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError):
        load_config(str(tmp_path / "nope.json"))


def test_broken_pressure_band_is_rejected():
    mapping = config_to_mapping(default_config())
    mapping["limits"]["secondary"]["makeup_target_kpa"] = 100.0
    with pytest.raises(ConfigError):
        type(default_config()).from_mapping(mapping)


def test_broken_flow_range_is_rejected():
    mapping = config_to_mapping(default_config())
    mapping["limits"]["source"]["flow_min_t_h"] = 9000.0
    with pytest.raises(ConfigError):
        type(default_config()).from_mapping(mapping)


def test_primary_and_valve_helpers():
    config = default_config()
    assert config.primary.low_flow_threshold(2400.0) == pytest.approx(2400.0 - config.primary.flow_tolerance_t_h)
    assert config.valve.settled(50.0, 50.5) is True
    assert config.valve.settled(50.0, 60.0) is False
