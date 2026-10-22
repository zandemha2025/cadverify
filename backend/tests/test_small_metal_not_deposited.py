"""A small metal block's pick is not wire-arc or metal deposition (ce-07, like-for-like).

DED/WAAM finish machining is priced as milling the part prices it: mill time, the mill's
setup, programming and first article, and the 3-axis route's hand work and in-process
inspection. A deposited part carries machining stock on every face (2 mm DED, 3 mm WAAM,
the low end of the analyzers' cited ranges), so a thin wall is deposited several times
its thickness. Before, the 60 × 20 × 25 mm aluminum bridge read DED $19.23 against
3-axis milling's $28.34 at 100 and the 80 × 60 × 40 mm enclosure DED $68.60 against
$70.39: both picked DED.
"""

from __future__ import annotations

import pytest
import trimesh

from src.costing import EstimateOptions, estimate_decision, report_to_dict
from tests.test_quantity_model import _analyze


def _bridge():
    slab = trimesh.creation.box(extents=[60.0, 20.0, 5.0])
    slab.apply_translation([0, 0, 22.5])
    legs = [trimesh.creation.box(extents=[10.0, 20.0, 20.0]) for _ in range(2)]
    legs[0].apply_translation([-25.0, 0, 10.0])
    legs[1].apply_translation([25.0, 0, 10.0])
    return trimesh.boolean.union([slab, *legs])


def _enclosure():
    outer = trimesh.creation.box(extents=[80.0, 60.0, 40.0])
    inner = trimesh.creation.box(extents=[75.0, 55.0, 40.0])
    inner.apply_translation([0, 0, 2.5])
    return trimesh.boolean.difference([outer, inner])


SHAPES = {
    "bridge": _bridge,
    "enclosure": _enclosure,
    "cube30": lambda: trimesh.creation.box(extents=[30.0, 30.0, 30.0]),
    "tiny2": lambda: trimesh.creation.box(extents=[2.0, 2.0, 2.0]),
}


@pytest.mark.parametrize("shape", list(SHAPES))
@pytest.mark.parametrize("material_class", ["aluminum", "titanium"])
def test_a_small_metal_block_is_not_picked_for_deposition(shape, material_class):
    mesh = SHAPES[shape]()
    assert mesh.is_watertight
    r, m, f = _analyze(mesh)
    rep = report_to_dict(estimate_decision(r, m, f, EstimateOptions(quantities=[1, 100, 1000],
                                                                     material_class=material_class)))
    rec = rep["decision"]["recommendation"]
    for q, pick in rec.items():
        assert (pick or {}).get("process") not in ("ded", "waam"), (shape, material_class, q, pick)
    at100 = {e["process"]: e for e in rep["estimates"] if e["quantity"] == 100}
    if "ded" in at100 and "cnc_3axis" in at100:
        # like-for-like: the deposited part pays the mill's hand work and inspection too
        src = next(d for d in at100["ded"]["drivers"] if d["name"] == "finish_machining")["source"]
        assert "hand work and handling" in src and "in-process inspection" in src
        assert at100["ded"]["unit_cost_usd"] > at100["cnc_3axis"]["unit_cost_usd"]
