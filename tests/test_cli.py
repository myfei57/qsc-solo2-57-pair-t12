"""命令行入口与端到端演示。"""

from __future__ import annotations

import json

from heatnet.cli import main


def test_demo_runs_end_to_end(tmp_path, capsys):
    exit_code = main(
        ["demo", "--fast", "--cycles", "40", "--rounds", "12", "--storage-root", str(tmp_path / "state")]
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["weather"]["ok"] is True
    assert payload["launch"]["ok"] is True
    assert payload["launch"]["stage"] == "done"
    assert payload["dispatch"]["ok"] is True
    assert payload["dispatch"]["planned"] == 6
    assert payload["secondary"]["pump_idle"] is True
    assert payload["retrofit"]["ok"] is True
    assert payload["split"]["zone"]["stations"] == ["st02", "st03"]
    assert payload["replayed"]["replayed"] == 2
    assert payload["concurrency"]["ok"] is True
    assert payload["trip"]["state"] == "tripped"
    assert payload["reset"]["state"] == "idle"
    assert all(item["ok"] for item in payload["probe"].values())
    assert payload["status"]["stations"]["count"] == 6


def test_demo_is_repeatable_on_the_same_storage_root(tmp_path, capsys):
    root = str(tmp_path / "state")
    first = main(["demo", "--fast", "--cycles", "20", "--rounds", "8", "--storage-root", root])
    capsys.readouterr()
    second = main(["demo", "--fast", "--cycles", "20", "--rounds", "8", "--storage-root", root])
    payload = json.loads(capsys.readouterr().out)
    assert first == 0
    assert second == 0
    assert payload["launch"]["ok"] is True
    assert payload["trip"]["state"] == "tripped"


def test_status_reports_every_subsystem(tmp_path, capsys):
    exit_code = main(["status", "--storage-root", str(tmp_path / "state")])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    for key in ("source", "curve", "primary", "secondary", "pump", "stations", "quota", "audit", "store"):
        assert key in payload
    assert payload["topology"]["order"][0] == "weather"
    assert payload["forecast"]["count"] == 4


def test_config_command_prints_effective_config(capsys):
    exit_code = main(["config"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["limits"]["source"]["supply_max_c"] == 115.0
    assert payload["limits"]["primary"]["flow_baseline_t_h"] > 0.0


def test_reset_command_reports_removed_flag(tmp_path, capsys):
    exit_code = main(["reset", "--storage-root", str(tmp_path / "state")])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["platform_state_removed"] is False


def test_load_config_file_is_used(tmp_path, capsys):
    from heatnet.config import config_to_mapping, default_config

    path = tmp_path / "heatnet.json"
    path.write_text(json.dumps(config_to_mapping(default_config())), encoding="utf-8")
    exit_code = main(["status", "--config", str(path), "--storage-root", str(tmp_path / "state")])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["platform"] == default_config().name
