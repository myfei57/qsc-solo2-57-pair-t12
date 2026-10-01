"""热量表回绕、并发累加与配额结算。"""

from __future__ import annotations

import threading

import pytest

from heatnet.config import default_config
from heatnet.quota.accumulator import QuotaAccumulator
from heatnet.quota.billing import billing_lines
from heatnet.quota.meter import HeatMeter
from heatnet.quota.quota import QuotaLedger


def test_meter_wraps_reading_but_keeps_total():
    meter = HeatMeter("st01.heat-meter", 10.0)
    meter.add(6.0)
    meter.add(6.0)
    assert meter.reading_mwh() == pytest.approx(2.0)
    assert meter.total_mwh() == pytest.approx(12.0)
    assert meter.wraps() == 1
    assert meter.increments() == 2
    assert meter.snapshot().as_dict()["reading_mwh"] == pytest.approx(2.0)
    assert meter.name == "st01.heat-meter"
    assert meter.wrap_mwh == pytest.approx(10.0)
    with pytest.raises(ValueError):
        meter.add(-1.0)
    with pytest.raises(ValueError):
        HeatMeter("bad", 0.0)


def test_concurrent_increments_are_not_lost():
    meter = HeatMeter("st01.heat-meter", 10_000_000.0)

    def worker() -> None:
        for _ in range(250):
            meter.add(1.0)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert meter.total_mwh() == pytest.approx(1000.0)
    assert meter.increments() == 1000


def test_accumulator_and_ledger():
    accumulator = QuotaAccumulator()
    accumulator.register(HeatMeter("st01.heat-meter", 1000.0))
    accumulator.register(HeatMeter("st02.heat-meter", 1000.0))
    with pytest.raises(ValueError):
        accumulator.register(HeatMeter("st01.heat-meter", 1000.0))
    accumulator.collect("st01.heat-meter", 12.0)
    accumulator.collect("st02.heat-meter", 8.0)
    assert accumulator.meters() == ["st01.heat-meter", "st02.heat-meter"]
    assert accumulator.total_mwh() == pytest.approx(20.0)
    assert accumulator.collections() == 2
    assert accumulator.describe()["count"] == 2
    with pytest.raises(KeyError):
        accumulator.get("nope")

    ledger = QuotaLedger(default_config().quota, accumulator)
    ledger.allocate("st01", 12.0)
    ledger.allocate("st02", 8.0)
    assert ledger.stations() == ["st01", "st02"]
    assert ledger.total_mwh() == pytest.approx(20.0)
    lines = billing_lines(ledger, 10.0)
    assert [line["station"] for line in lines] == ["st01", "st02"]
    assert lines[0]["overage_mwh"] == pytest.approx(2.0)
    assert lines[0]["charge"] == pytest.approx(10.0 * 32.0 + 2.0 * 32.0 * 1.6)
    assert lines[1]["overage_mwh"] == pytest.approx(0.0)

    settled = ledger.settle()
    assert settled["period"] == 1
    assert settled["total_mwh"] == pytest.approx(20.0)
    assert ledger.periods() == 1
    assert ledger.stations() == []
    assert ledger.snapshot().as_dict()["period_hours"] == pytest.approx(24.0)
    assert ledger.accumulator is accumulator
