"""Machine hours by machine never leave the organization.

The Cost and Decision views, the catalog board, the pilot report and the
machine load (GET /machine-inventory/load) read machine time per route and sum
it per machine of yours. None of that is an outbound copy, and a record that
somehow carried such a roll-up still wouldn't pass ``outbound.cost_record``:
the in-house route (its price, its machine time) is dropped, the machines are
never named, and keys the allowlist doesn't name stay inside.
"""
from __future__ import annotations

import copy
import json

from src.services import outbound
from tests.test_outbound_copies import MACHINES, assert_nothing_private, shop_result  # noqa: F401 (fixture)


def test_machine_hours_by_machine_stay_inside(shop_result):  # noqa: F811
    rec = copy.deepcopy(shop_result)
    owned = {e["process"] for e in rec["estimates"] if any(d["name"] == "owned_in_house" for d in e["drivers"])}
    assert owned, "the shop's record prices a route on its own machine"
    # Roll-ups the screens compute, as if one were ever saved on a record.
    rec["machine_load"] = {"machines": [{"machine": MACHINES[0], "hours": 52.4, "parts": 3}]}
    rec["breakdown"] = {"in_house": {"machines": [{"machine": MACHINES[0], "process": "fdm", "hours": 52.4}],
                                     "materials": [{"material": "PLA", "used_kg": 1.36}]}}
    rec["verification"]["hours_by_machine"] = {MACHINES[0]: 52.4}

    out = outbound.cost_record(rec, terms=MACHINES)
    blob = json.dumps(out)
    assert_nothing_private(blob, "cost_record with machine roll-ups")
    for key in ("machine_load", "breakdown", "verification", "hours_by_machine"):
        assert key not in out
    # The route priced on the shop's own machine, with its machine time, is gone.
    assert not [e for e in out["estimates"] if e["process"] in owned]
    # Machine time on routes outside stays: it's the engine's generic estimate.
    assert any(d["name"] == "cycle_time" for e in out["estimates"] for d in e["drivers"])
    assert outbound.cost_record(out, terms=MACHINES) == out
