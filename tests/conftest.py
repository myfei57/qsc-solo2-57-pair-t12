"""测试夹具：所有用例都从干净存储和可推进时钟起步。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from heatnet.app import Platform, build_platform  # noqa: E402
from heatnet.clock import ManualClock  # noqa: E402
from heatnet.config import default_config  # noqa: E402


@pytest.fixture()
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture()
def platform(tmp_path, clock) -> Platform:
    return build_platform(default_config(), clock=clock, storage_root=str(tmp_path / "state"))


@pytest.fixture()
def online(platform) -> Platform:
    """已下发气象、已投运、已带负荷的平台。"""

    platform.start()
    platform.push_weather(-8.0)
    platform.startup(-8.0, 60.0)
    platform.dispatch(60.0, 60.0)
    return platform
