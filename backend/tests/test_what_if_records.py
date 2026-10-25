"""A what-if never becomes the part's price by itself (round 11, ce-17, ce-08).

Priyanka tried overhead 15% on the pocket block's breakdown; the re-cost was saved
as the part's newest record, so the parts list and the part page then showed the
what-if's $56.99 as the pocket block's price. A price with ad-hoc overrides or a
sample shop's rates is now saved as a what-if ("What if: overhead 15%"): listed,
exportable, never the part's current price until she chooses "Use this as the
part's price".
"""
from __future__ import annotations

import uuid

import pytest

from src.services import cost_decision_service as csvc
from tests.test_part_summary import _Fixture, _cleanup, _cost_json, _persist_cost, _requires_pg


def test_what_if_marker_and_label():
    w = csvc.what_if_block({"overhead": 0.15}, None)
    assert w == {"overrides": {"overhead": 0.15}, "shop": None, "label": "What if: overhead 15%"}
    assert csvc.what_if_block({"labor_rate": 58, "machine_rate.CNC_3AXIS": 82}, None)["label"] == \
        "What if: labor $58/h, 3-axis milling machine $82/h"
    assert csvc.what_if_block({}, "acme-machining", "Acme Machining")["label"] == "What if: Acme Machining rates"
    assert csvc.what_if_block({"post_hr_part.CNC_3AXIS": 0.1}, None)["label"] == \
        "What if: 3-axis milling hand work 0.1 h a part"
    # the part's own inputs are no what-if
    assert csvc.what_if_block({}, None) is None and csvc.what_if_block(None, "") is None
    assert csvc.is_current_price({"estimates": []}) and not csvc.is_current_price({"what_if": w})


def _priced(unit, *, what_if=None):
    j = _cost_json()
    j["estimates"][0]["unit_cost_usd"] = unit
    if what_if:
        j["what_if"] = what_if
    return j


@_requires_pg
@pytest.mark.asyncio
async def test_a_what_if_leaves_the_part_summary_and_adopting_it_moves_it():
    import src.db.engine as eng
    from sqlalchemy import text

    fx = _Fixture(uuid.uuid4().hex[:8])
    try:
        async with eng.get_session_factory()() as s:
            org = await fx.org(s, "W")
            u = await fx.user(s, org, "w")
            mesh = f"pocket-{fx.tag}"
            base = await _persist_cost(s, u, mesh, _priced(49.63))
            await s.commit()
            base_id = base.ulid

        async def summary():
            async with eng.get_session_factory()() as s:
                return (await s.execute(
                    text("SELECT row_json FROM part_summaries WHERE org_id=:o AND mesh_hash=:m"),
                    {"o": org, "m": mesh})).scalar_one()

        row = await summary()
        assert row["cost_decision"]["id"] == base_id and row["unit_cost"]["usd"] == 49.63

        # her overhead-15% what-if: saved, newest, but not the part's price
        async with eng.get_session_factory()() as s:
            wi = await _persist_cost(s, u, mesh, _priced(56.99, what_if=csvc.what_if_block({"overhead": 0.15}, None)))
            await s.commit()
            wi_id = wi.ulid
        row = await summary()
        assert row["cost_decision"]["id"] == base_id and row["unit_cost"]["usd"] == 49.63

        async with eng.get_session_factory()() as s:
            assert (await csvc.newest_current(s, org, mesh)).ulid == base_id
            listed = await csvc.latest_per_part(s, u.user_id, limit=10, detail_limit=5)
            assert [p["id"] for p in listed["parts"]] == [base_id]
            item = csvc._list_item(await csvc.get_owned(s, wi_id, u.user_id))
            assert item["what_if"] == "What if: overhead 15%"

        # "Use this as the part's price": a new record, the what-if itself unchanged
        async with eng.get_session_factory()() as s:
            adopted = await csvc.adopt_what_if(s, u, wi_id)
            await s.commit()
            adopted_id = adopted.ulid
            assert adopted.result_json["adopted_what_if"]["from"] == wi_id
            assert "what_if" not in adopted.result_json
            assert csvc.what_if_of((await csvc.get_owned(s, wi_id, u.user_id)).result_json) is not None
        row = await summary()
        assert row["cost_decision"]["id"] == adopted_id and row["unit_cost"]["usd"] == 56.99

        # adopting a price at the part's own inputs is refused
        from fastapi import HTTPException

        async with eng.get_session_factory()() as s:
            with pytest.raises(HTTPException) as ei:
                await csvc.adopt_what_if(s, u, base_id)
            assert ei.value.status_code == 409
    finally:
        await _cleanup(fx)
