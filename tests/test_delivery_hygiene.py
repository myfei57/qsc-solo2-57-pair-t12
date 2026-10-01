"""交付留存与死代码门禁。"""

from __future__ import annotations

import os
import subprocess
import sys

from heatnet.errors import InterlockError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_alarm_entries_are_captured(platform):
    platform.start()
    platform.push_weather(60.0)
    assert platform.audit.alarms()
    assert any(item["severity"] == "alarm" for item in platform.audit.alarms())
    assert platform.audit.entries(limit=5)
    assert platform.audit.tail(3)[0]["ts"] <= platform.audit.tail(3)[-1]["ts"]
    assert platform.audit.replay_from_journal()[0]["component"]
    assert platform.audit.replay_segment(0)


def test_platform_error_is_recorded_with_component(platform):
    platform.start()
    error = InterlockError("顺序不满足", component="valve")
    record = platform.note_error(error)
    assert record["component"] == "valve"
    assert record["action"] == "error"
    assert record["severity"] == "warning"


def test_events_are_published_to_subscribers(platform):
    seen: list[str] = []
    unsubscribe = platform.bus.subscribe("source", lambda event: seen.append(event.action))
    platform.push_weather(-8.0)
    assert "fire_forecast" in seen
    unsubscribe()
    assert platform.bus.history("source")


def test_source_tree_has_no_self_description_or_markers():
    blocked = ("TODO", "FIXME", "XXX", "HACK", "BUG(", "故意", "埋了", "留坑")
    package = os.path.join(ROOT, "heatnet")
    offenders: list[str] = []
    for base, _dirs, files in os.walk(package):
        if "__pycache__" in base:
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            for marker in blocked:
                if marker in text:
                    offenders.append(f"{os.path.relpath(path, ROOT)}:{marker}")
    assert offenders == []
    assert not os.path.exists(os.path.join(ROOT, "README.md"))
    assert not os.path.exists(os.path.join(ROOT, "BUG_REPRO.md"))


def test_deadcode_gate_reports_no_unused_symbols():
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "deadcode.py"), os.path.join(ROOT, "heatnet")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"unused_symbols": []' in result.stdout
    assert '"unreachable_modules": []' in result.stdout


def test_package_compiles_without_bytecode_errors():
    result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", os.path.join(ROOT, "heatnet")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
