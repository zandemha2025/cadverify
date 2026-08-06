"""BOM hierarchy service (customer-context Slice 3) — pure helpers + honesty pins.

No live DB: the edge-derivation, BOM parsing, ancestry, rollup, and volume-basis
logic are all pure and unit-tested here. The Postgres persistence + cross-tenant
isolation lifecycle is covered by the DATABASE_URL-guarded ``test_bom_api.py``.

Honesty pins:
  * A part with no tree has NO rollup — ``rolled_up_multiplier`` is None, and
    ``resolve_annual_volume`` falls back to the flat declared value (basis
    'declared') or 'default', NEVER a fabricated rollup.
  * A shared component (a DAG) sums its count over every path to the root — it is
    never double-counted and never a dropped path.
  * A bad BOM row is reported + skipped; the batch survives.
"""
from __future__ import annotations

import pytest

from src.services import bom_service as bom


# ---------------------------------------------------------------------------
# Fixtures: tiny fake AssemblyModel trees (mirror assembly_mesher.TreeNode shape)
# ---------------------------------------------------------------------------
class _Node:
    def __init__(self, name, children=None):
        self.name = name
        self.occurrence = name
        self.children = children or []


class _Model:
    def __init__(self, tree):
        self.tree = tree


def _as1_like():
    """A faithful stand-in for AS1's real tree: as1 -> {rod-assembly, 2x
    l-bracket-assembly, plate}; each l-bracket-assembly -> {3x nut-bolt-assembly,
    l-bracket}; each nut-bolt-assembly -> {bolt, nut}; rod-assembly -> {2x nut, rod}.
    """
    def nut_bolt():
        return _Node("nut-bolt-assembly", [_Node("bolt"), _Node("nut")])

    def l_bracket_asm():
        return _Node(
            "l-bracket-assembly",
            [nut_bolt(), nut_bolt(), nut_bolt(), _Node("l-bracket")],
        )

    rod_asm = _Node("rod-assembly", [_Node("nut"), _Node("nut"), _Node("rod")])
    return _Model(_Node("as1", [rod_asm, l_bracket_asm(), _Node("plate"), l_bracket_asm()]))


# ---------------------------------------------------------------------------
# edges_from_assembly — real design-collapsed edges + measured quantities
# ---------------------------------------------------------------------------
def test_edges_from_assembly_reproduces_hierarchy():
    edges = bom.edges_from_assembly(_as1_like())
    by_pair = {(e["parent_ref"], e["child_ref"]): e["qty_per_parent"] for e in edges}
    assert by_pair[("as1", "l-bracket-assembly")] == 2
    assert by_pair[("as1", "rod-assembly")] == 1
    assert by_pair[("as1", "plate")] == 1
    assert by_pair[("l-bracket-assembly", "nut-bolt-assembly")] == 3
    assert by_pair[("l-bracket-assembly", "l-bracket")] == 1
    assert by_pair[("nut-bolt-assembly", "bolt")] == 1
    assert by_pair[("nut-bolt-assembly", "nut")] == 1
    assert by_pair[("rod-assembly", "nut")] == 2
    # depths: root's children d1, their children d2, bolts/nuts d3.
    depth = {(e["parent_ref"], e["child_ref"]): e["depth"] for e in edges}
    assert depth[("as1", "l-bracket-assembly")] == 1
    assert depth[("l-bracket-assembly", "nut-bolt-assembly")] == 2
    assert depth[("nut-bolt-assembly", "bolt")] == 3
    assert bom._roots(edges) == {"as1"}


def test_ancestry_is_the_real_chain():
    edges = bom.edges_from_assembly(_as1_like())
    assert bom.ancestry(edges, "bolt") == [
        "bolt", "nut-bolt-assembly", "l-bracket-assembly", "as1",
    ]


def test_rolled_up_multiplier_matches_true_instance_counts():
    edges = bom.edges_from_assembly(_as1_like())
    # bolt: 1 per nut-bolt x 3 nut-bolt per l-bracket x 2 l-bracket per vehicle = 6.
    assert bom.rolled_up_multiplier(edges, "bolt") == 6
    # l-bracket: 1 per l-bracket-assembly x 2 = 2.
    assert bom.rolled_up_multiplier(edges, "l-bracket") == 2
    assert bom.rolled_up_multiplier(edges, "rod") == 1
    assert bom.rolled_up_multiplier(edges, "plate") == 1
    # nut is a real DAG: 2 via rod-assembly + (1x3x2)=6 via the l-brackets = 8.
    assert bom.rolled_up_multiplier(edges, "nut") == 8
    assert len(bom.ancestry_paths(edges, "nut")) == 2
    # the root is 1 per vehicle.
    assert bom.rolled_up_multiplier(edges, "as1") == 1


def test_unknown_part_has_no_rollup_never_fabricated():
    edges = bom.edges_from_assembly(_as1_like())
    assert bom.rolled_up_multiplier(edges, "widget") is None
    assert bom.ancestry(edges, "widget") == []
    assert bom.annual_volume(edges, "widget", 100000) is None


def test_empty_tree_yields_no_edges():
    assert bom.edges_from_assembly(_Model(_Node("solo"))) == []


def test_cycle_is_guarded():
    # a -> b -> a is a cycle; the walk must terminate, not recurse forever.
    edges = [
        {"parent_ref": "a", "child_ref": "b", "qty_per_parent": 1},
        {"parent_ref": "b", "child_ref": "a", "qty_per_parent": 1},
    ]
    mult = bom.rolled_up_multiplier(edges, "b")
    assert isinstance(mult, int)  # terminates with a finite number


# ---------------------------------------------------------------------------
# annual_volume + resolve_annual_volume — the multi-level rollup + honest basis
# ---------------------------------------------------------------------------
def test_handle_door_car_multi_level_rollup():
    # handle -> door (2 per) -> car (4 per).
    edges = [
        {"parent_ref": "car", "child_ref": "door", "qty_per_parent": 4},
        {"parent_ref": "door", "child_ref": "handle", "qty_per_parent": 2},
    ]
    assert bom.ancestry(edges, "handle") == ["handle", "door", "car"]
    assert bom.rolled_up_multiplier(edges, "handle") == 8  # 2 x 4
    assert bom.annual_volume(edges, "handle", 100000) == 800000  # 2 x 4 x 100000


def test_resolve_prefers_rollup_then_declared_then_default():
    # rollup wins when a multiplier + roots/year exist.
    assert bom.resolve_annual_volume(999, 8, 100000) == {
        "annual_volume": 800000, "annual_volume_basis": "bom_rollup",
    }
    # no tree (multiplier None) → the flat declared value, labelled 'declared'.
    assert bom.resolve_annual_volume(12000, None, 100000) == {
        "annual_volume": 12000, "annual_volume_basis": "declared",
    }
    # roots/year missing → cannot roll up → declared fallback.
    assert bom.resolve_annual_volume(12000, 8, None) == {
        "annual_volume": 12000, "annual_volume_basis": "declared",
    }
    # nothing declared and no tree → default (no fabricated volume).
    assert bom.resolve_annual_volume(None, None, None) == {
        "annual_volume": None, "annual_volume_basis": "default",
    }


# ---------------------------------------------------------------------------
# parse_bom — CSV/JSON contract + honest per-row skips
# ---------------------------------------------------------------------------
def test_parse_bom_csv_happy_and_bad_row_skipped():
    csv_text = (
        "parent_ref,child_ref,qty_per_parent,child_name\n"
        "car,door,4,Door\n"
        "door,handle,2,Handle\n"
        "door,,3,Nameless\n"            # missing child_ref -> reported + skipped
        "door,latch,notanint,Latch\n"   # bad qty -> reported + skipped
        "door,trim\n"                    # qty omitted -> defaults to 1
    )
    rows, errors = bom.parse_bom(csv_text)
    pairs = {(r["parent_ref"], r["child_ref"]): r["qty_per_parent"] for r in rows}
    assert pairs[("car", "door")] == 4
    assert pairs[("door", "handle")] == 2
    assert pairs[("door", "trim")] == 1  # optional qty defaulted, not fabricated
    assert len(rows) == 3
    assert len(errors) == 2  # the two bad rows, batch survived
    assert {e["line"] for e in errors} == {4, 5}


def test_parse_bom_json_form():
    rows, errors = bom.parse_bom(
        '[{"parent_ref":"car","child_ref":"door","qty_per_parent":4},'
        '{"parent_ref":"door","child_ref":"handle","qty_per_parent":2}]',
        content_hint="application/json",
    )
    assert errors == []
    assert len(rows) == 2


def test_parse_bom_rejects_bad_header_and_self_loop():
    _, errors = bom.parse_bom("foo,bar\nx,y\n")
    assert errors and "missing required column" in errors[0]["reason"]
    rows, errs = bom.parse_bom("parent_ref,child_ref\nx,x\n")
    assert rows == [] and errs and "self-referential" in errs[0]["reason"]
