"""A what-if never moves the parts list row or the accuracy check (ce-17, after 05748fb).

Priyanka's overhead-15% re-cost is the pocket block's newest record. The parts
list (``build_catalog``) still shows the part's own price, and her actual for
the block is still graded against that price, never against the what-if.
"""
from __future__ import annotations

import uuid

import pytest

from src.services import cost_decision_service as csvc
from tests.test_part_summary import _Fixture, _cleanup, _cost_json, _persist_cost, _requires_pg


def _priced(unit, *, what_if=None):
    j = _cost_json()
    j["estimates"][0]["unit_cost_usd"] = unit
    if what_if:
        j["what_if"] = what_if
    return j


@_requires_pg
@pytest.mark.asyncio
async def test_a_newer_what_if_changes_neither_the_parts_list_row_nor_the_accuracy_check():
    import src.db.engine as eng
    from src.db.models import GroundTruthRecordRow
    from src.services import accuracy_service as acc
    from src.services.catalog_service import build_catalog

    fx = _Fixture(uuid.uuid4().hex[:8])
    try:
        async with eng.get_session_factory()() as s:
            org = await fx.org(s, "WI")
            u = await fx.user(s, org, "wi")
            mesh = f"pocket-{fx.tag}"
            base = await _persist_cost(s, u, mesh, _priced(49.63))
            await s.commit()
            base_id = base.ulid
            await _persist_cost(s, u, mesh, _priced(56.99, what_if=csvc.what_if_block({"overhead": 0.15}, None)))
            s.add(GroundTruthRecordRow(org_id=org, user_id=u.user_id, part_id="pocket block", process="cnc_3axis",
                                       quantity=50, actual_unit_cost_usd=51.0, evidence_sha256=mesh))
            await s.commit()

        async with eng.get_session_factory()() as s:
            for key in (mesh, None):  # the part's own lookup and the whole list
                rows = [r for r in (await build_catalog(s, org, part_key=key))["rows"] if r["part_key"] == mesh]
                assert len(rows) == 1
                assert rows[0]["cost_decision"]["id"] == base_id
                assert rows[0]["unit_cost"]["usd"] == 49.63

            assert (await acc.latest_records(s, org))[mesh]["id"] == base_id
            graded = await acc.comparisons(s, org, acc.Scope())
            assert [c["record_id"] for c in graded] == [base_id]
            assert graded[0]["cost"]["estimate"] == 49.63
    finally:
        from sqlalchemy import text

        async with eng.get_session_factory()() as s:
            if fx.org_ids:
                await s.execute(text("DELETE FROM ground_truth_records WHERE org_id = ANY(:o)"), {"o": fx.org_ids})
                await s.commit()
        await _cleanup(fx)
