"""定压基线的校验与回滚。"""

from __future__ import annotations

import pytest

from heatnet.config import default_config
from heatnet.errors import InterlockError
from heatnet.pressure.baseline import PressureBaseline
from heatnet.pressure.control import PressurisingController
from heatnet.secondary.loop import SecondaryLoop


def _stack() -> tuple[PressureBaseline, PressurisingController, SecondaryLoop]:
    limits = default_config().pressure
    baseline = PressureBaseline(limits)
    controller = PressurisingController(baseline, limits)
    return baseline, controller, SecondaryLoop(default_config().secondary)


def test_retrofit_validates_before_writing():
    baseline, _, _ = _stack()
    original = baseline.value_kpa()
    with pytest.raises(InterlockError):
        baseline.apply_retrofit(9999.0)
    assert baseline.value_kpa() == pytest.approx(original)
    assert baseline.rejected() == 1
    assert baseline.revisions() == 0
    assert baseline.last_target_kpa() == pytest.approx(9999.0)
    assert baseline.snapshot().in_range is True


def test_retrofit_rolls_back_and_keeps_loop_pressure():
    baseline, controller, loop = _stack()
    original = baseline.value_kpa()
    before_pressure = loop.pressure_kpa()
    report = controller.retrofit(loop, original + 2000.0)
    assert report["ok"] is False
    assert report["rolled_back"] is True
    assert report["baseline_kpa"] == pytest.approx(original)
    assert loop.pressure_kpa() == pytest.approx(before_pressure)


def test_valid_retrofit_settles_loop_pressure():
    baseline, controller, loop = _stack()
    target = baseline.limits.baseline_max_kpa - 10.0
    report = controller.retrofit(loop, target)
    assert report["ok"] is True
    assert report["rolled_back"] is False
    assert baseline.value_kpa() == pytest.approx(target)
    assert loop.pressure_kpa() == pytest.approx(target, abs=2.5)
    assert controller.settles() == 1
    assert baseline.revisions() == 1


def test_pressurising_controller_rejects_bad_step():
    _, controller, loop = _stack()
    with pytest.raises(ValueError):
        controller.settle(loop, 0.0)
