"""Issue #147: high-quantity lead times model the market, not one shop's queue.

The audit fixture (3-axis, 38.3 hr/part, 1,000 units) quoted 309 mid days
because production serialized behind one 8-machine pool. Real buys that size
span parallel suppliers. The model now: the pool grows with the order
(bounded), production caps at a 30-day horizon, and orders past one horizon
ship in stated waves — monotonic in quantity (G5) throughout.
"""
from __future__ import annotations

import pytest

from src.analysis.models import ProcessType
from src.costing.leadtime import lead_time
from src.costing.rates import build_rate_card


@pytest.fixture(scope="module")
def rates():
    return build_rate_card()


def test_the_audit_case_is_market_scaled_not_serial(rates):
    lt = lead_time(ProcessType.CNC_3AXIS, 38.308, 1000, rates)
    assert lt.components["production"] <= 30.0
    assert lt.mid_days < 60.0                    # was 309 serial
    assert "market-scaled" in lt.capacity["basis"]
    assert lt.capacity["market_n_machines"] > 8


def test_small_orders_are_unchanged(rates):
    small = lead_time(ProcessType.CNC_3AXIS, 0.5, 10, rates)
    assert small.capacity["market_n_machines"] is None
    assert "capacity-bound" in small.capacity["basis"]
    assert "parallel_supply_waves" not in small.components


def test_monotonic_in_quantity(rates):
    prev = -1.0
    for qty in (1, 10, 100, 500, 1000, 5000, 50_000):
        lt = lead_time(ProcessType.CNC_3AXIS, 38.308, qty, rates)
        assert lt.mid_days >= prev, f"lead fell at qty={qty}: {lt.mid_days} < {prev}"
        prev = lt.mid_days


def test_beyond_one_horizon_ships_in_stated_waves(rates):
    lt = lead_time(ProcessType.CNC_3AXIS, 38.308, 50_000, rates)
    assert lt.components.get("parallel_supply_waves", 0) > 1
    assert lt.components["production"] <= 30.0
    # honest words, not a 4,000-day serial calendar
    assert lt.mid_days < 365.0
