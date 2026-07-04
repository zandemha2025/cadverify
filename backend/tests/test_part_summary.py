"""Tests for the materialized part-summary projection (Aramco GAP 2 — scale).

Two layers, mirroring the repo's pure-vs-PG split:

  * PURE — ``derive_summary_fields`` maps hand-built ``derive_row`` dicts to the
    right bucket / route_process / flags / recency. No DB.
  * PG (DATABASE_URL-guarded) — the maintenance hooks, byte-identity vs the legacy
    fold, the cost dedup + drafted→costed transition, backfill idempotency +
    parity, and keyset pagination — all driven THROUGH the real
    ``_persist_analysis`` / ``persist_cost_decision`` so the write hooks fire.

The byte-identity guarantee is the crux: the summary-backed
``build_triage_scaled`` / ``build_catalog_page`` must reproduce the legacy
``build_triage`` / ``build_catalog`` output EXACTLY on identical data (the legacy
fold path is left untouched as the oracle).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import pytest

from src.services import catalog_service as svc
from src.services import part_summary_service as pss
from src.services.catalog_service import SourceRef


# ---------------------------------------------------------------------------
# result_json builders (real report_to_dict / analysis shapes)
# ---------------------------------------------------------------------------


def _analysis_json(best="cnc_3axis", *, clean=False):
    if clean:
        return {"best_process": best, "universal_issues": [], "process_scores": []}
    return {
        "best_process": best,
        "universal_issues": [
            {"code": "NON_WATERTIGHT", "severity": "error", "message": "not watertight"},
        ],
        "process_scores": [
            {
                "process": best,
                "recommended_material": "aluminum_6061",
                "issues": [
                    {"code": "DEEP_POCKET", "severity": "warning", "message": "deep pocket"},
                ],
            },
        ],
    }


def _cost_json(*, process="cnc_3axis", dfm_ready=True, blockers=None):
    return {
        "decision": {
            "make_now_process": process,
            "make_now_material": "aluminum_6061",
            "crossover_qty": 500.0,
        },
        "quantities": [50],
        "estimates": [
            {
                "process": process,
                "material": "aluminum_6061",
                "quantity": 50,
                "unit_cost_usd": 12.5,
                "dfm_ready": dfm_ready,
                "dfm_blockers": blockers or [],
                "confidence": {"validated": False, "label": "assumption band"},
                "drivers": [{"provenance": "MEASURED"}, {"provenance": "DEFAULT"}],
            }
        ],
    }


def _ref(result_json, *, id="01ABC", fn="part.stl", ts=None):
    return SourceRef(
        id=id,
        filename=fn,
        file_type="stl",
        created_at=ts or datetime(2026, 6, 1, tzinfo=timezone.utc),
        result_json=result_json,
    )


def _row(part_key, *, analysis=None, cost=None):
    return svc.derive_row(part_key=part_key, analysis=analysis, cost=cost)


# ===========================================================================
# PURE — derive_summary_fields
# ===========================================================================


def test_derive_summary_fields_makeable():
    row = _row("m", analysis=_ref(_analysis_json(clean=True)), cost=_ref(_cost_json()))
    f = pss.derive_summary_fields(row)
    assert f["triage_bucket"] == "makeable"
    assert f["route_process"] == "cnc_3axis"
    assert f["has_analysis"] is True
    assert f["has_cost"] is True
    assert f["row_json"] is row
    assert f["updated_at"] == datetime.fromisoformat(row["updated_at"])


def test_derive_summary_fields_needs_review():
    # universal critical finding on the route → needs_review
    row = _row("m", analysis=_ref(_analysis_json()), cost=_ref(_cost_json()))
    f = pss.derive_summary_fields(row)
    assert f["triage_bucket"] == "needs_review"
    assert f["route_process"] == "cnc_3axis"


def test_derive_summary_fields_unknown_costed_no_analysis():
    # routed by a cost decision, no DFM analysis → unknown, has_analysis False
    row = _row("m", analysis=None, cost=_ref(_cost_json()))
    f = pss.derive_summary_fields(row)
    assert f["triage_bucket"] == "unknown"
    assert f["route_process"] == "cnc_3axis"
    assert f["has_analysis"] is False
    assert f["has_cost"] is True


def test_derive_summary_fields_unknown_no_route():
    row = _row(
        "m",
        analysis=_ref({"best_process": "", "universal_issues": [], "process_scores": []}),
        cost=None,
    )
    f = pss.derive_summary_fields(row)
    assert f["triage_bucket"] == "unknown"
    assert f["route_process"] is None
    assert f["has_cost"] is False


def test_derive_summary_fields_drafted_makeable():
    # drafted-only (analysis, no cost), clean route → makeable, has_cost False
    row = _row("m", analysis=_ref(_analysis_json(best="injection_molding", clean=True)), cost=None)
    f = pss.derive_summary_fields(row)
    assert f["triage_bucket"] == "makeable"
    assert f["route_process"] == "injection_molding"
    assert f["has_analysis"] is True
    assert f["has_cost"] is False


# ===========================================================================
# PG — DATABASE_URL-guarded maintenance / byte-identity / backfill / keyset
# ===========================================================================

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


def _sort_key(r):
    """The (updated_at DESC, mesh_hash DESC) sort key — fully deterministic even
    when two parts share updated_at (legacy tie order is set-iteration, so we
    compare order-independent of ties)."""
    return (r["updated_at"], r["part_key"])


def _sorted_rows(rows):
    return sorted(rows, key=_sort_key, reverse=True)


class _Fixture:
    """Seeds orgs/users/keys/memberships and persists analyses + cost decisions
    THROUGH the real service funnels so the projection hooks fire."""

    def __init__(self, tag):
        self.tag = tag
        self.user_ids: list[int] = []
        self.org_ids: list[str] = []

    async def user(self, s, org_id, label):
        from ulid import ULID
        from sqlalchemy import text

        email = f"psum-{self.tag}-{label}@example.com"
        uid = int(
            (
                await s.execute(
                    text(
                        "INSERT INTO users (email, email_lower, role, auth_provider) "
                        "VALUES (:e, :el, 'analyst', 'password') RETURNING id"
                    ),
                    {"e": email, "el": email.lower()},
                )
            ).first()[0]
        )
        await s.execute(
            text(
                "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                "VALUES (:id, :o, :u, 'admin', now())"
            ),
            {"id": str(ULID()), "o": org_id, "u": uid},
        )
        kid = int(
            (
                await s.execute(
                    text(
                        "INSERT INTO api_keys (user_id, org_id, name, prefix, "
                        "hmac_index, secret_hash) VALUES (:u, :o, :n, :p, :h, 'x') "
                        "RETURNING id"
                    ),
                    {"u": uid, "o": org_id, "n": label,
                     "p": f"pfx{label}{self.tag}", "h": f"hmac-{self.tag}-{label}"},
                )
            ).first()[0]
        )
        self.user_ids.append(uid)
        from src.auth.require_api_key import AuthedUser

        return AuthedUser(user_id=uid, api_key_id=kid, key_prefix="test", role="analyst")

    async def org(self, s, label):
        from ulid import ULID
        from sqlalchemy import text

        oid = str(ULID())
        await s.execute(
            text(
                "INSERT INTO organizations (id, name, slug, created_at) "
                "VALUES (:id, :n, :sl, now())"
            ),
            {"id": oid, "n": f"PS {label} {self.tag}", "sl": f"ps-{label}-{self.tag}"},
        )
        self.org_ids.append(oid)
        return oid


async def _persist_an(s, user, mesh, result):
    from src.services import analysis_service as asvc

    return await asvc._persist_analysis(
        s,
        user,
        mesh_hash=mesh,
        process_set_hash=f"pset-{uuid.uuid4().hex}",
        analysis_version="0.3.0",
        filename=f"{mesh}.stl",
        file_type="stl",
        file_size_bytes=1024,
        result_json=result,
        verdict="issues",
        face_count=12,
        duration_ms=50.0,
    )


async def _persist_cost(s, user, mesh, result, *, params=None):
    from src.services import cost_decision_service as csvc

    return await csvc.persist_cost_decision(
        s,
        user,
        mesh_hash=mesh,
        params_hash=params or f"params-{uuid.uuid4().hex}",
        engine_version="0.3.0",
        filename=f"{mesh}.stl",
        file_type="stl",
        result_json=result,
    )


async def _cleanup(fx):
    import src.db.engine as eng
    from sqlalchemy import text

    async with eng.get_session_factory()() as s:
        if fx.user_ids:
            ids = fx.user_ids
            await s.execute(text("DELETE FROM part_summaries WHERE org_id = ANY(:o)"), {"o": fx.org_ids})
            await s.execute(text("DELETE FROM part_contexts WHERE org_id = ANY(:o)"), {"o": fx.org_ids})
            await s.execute(text("DELETE FROM analyses WHERE user_id = ANY(:i)"), {"i": ids})
            await s.execute(text("DELETE FROM cost_decisions WHERE user_id = ANY(:i)"), {"i": ids})
            await s.execute(text("DELETE FROM api_keys WHERE user_id = ANY(:i)"), {"i": ids})
            await s.execute(text("DELETE FROM memberships WHERE user_id = ANY(:i)"), {"i": ids})
            await s.execute(text("DELETE FROM users WHERE id = ANY(:i)"), {"i": ids})
        if fx.org_ids:
            await s.execute(text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": fx.org_ids})
        await s.commit()
    await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_maintenance_byte_identity_vs_legacy():
    """The KEY test: persist a spread through the REAL funnels (hooks fire), then
    the summary-backed reads must EQUAL the legacy fold output exactly, per org,
    with cross-tenant isolation."""
    import src.db.engine as eng
    from sqlalchemy import text
    from ulid import ULID

    fx = _Fixture(uuid.uuid4().hex[:8])
    try:
        async with eng.get_session_factory()() as s:
            org_a = await fx.org(s, "A")
            org_b = await fx.org(s, "B")
            ua = await fx.user(s, org_a, "a")
            ub = await fx.user(s, org_b, "b")

            # Org A: makeable (clean cnc costed), needs_review (blocked cnc),
            # unknown (costed no analysis), drafted-only makeable (injection).
            m_mk = f"a-mk-{fx.tag}"
            await _persist_an(s, ua, m_mk, _analysis_json(clean=True))
            await _persist_cost(s, ua, m_mk, _cost_json())
            await _persist_cost(
                s, ua, f"a-nr-{fx.tag}",
                _cost_json(dfm_ready=False, blockers=["Wall too thin for CNC."]),
            )
            await _persist_cost(s, ua, f"a-unk-{fx.tag}", _cost_json())
            await _persist_an(
                s, ua, f"a-draft-{fx.tag}",
                _analysis_json(best="injection_molding", clean=True),
            )

            # A declared program on two parts → exercises programs parity.
            await s.execute(
                text(
                    "INSERT INTO part_contexts (ulid, org_id, mesh_hash, program) "
                    "VALUES (:u1, :o, :m1, 'Alpha'), (:u2, :o, :m2, 'Alpha')"
                ),
                {"u1": str(ULID()), "o": org_a, "m1": m_mk,
                 "u2": str(ULID()), "m2": f"a-nr-{fx.tag}"},
            )

            # Org B: two makeable die_casting parts (must NEVER leak into A).
            for i in (1, 2):
                mb = f"b-{i}-{fx.tag}"
                await _persist_an(s, ub, mb, _analysis_json(best="die_casting", clean=True))
                await _persist_cost(s, ub, mb, _cost_json(process="die_casting"))

            await s.commit()

        # Fresh session for reads.
        async with eng.get_session_factory()() as s:
            for org in (org_a, org_b):
                legacy_triage = await svc.build_triage(s, org)
                scaled_triage = await svc.build_triage_scaled(s, org)
                # truncated differs by contract (scaled is whole-inventory) — but
                # under the cap legacy is also False, so they're equal here.
                assert scaled_triage == legacy_triage, org

                legacy_rows = _sorted_rows((await svc.build_catalog(s, org))["rows"])
                # Walk every keyset page and gather rows.
                walked = []
                cursor = None
                while True:
                    page = await svc.build_catalog_page(s, org, cursor=cursor, limit=2)
                    walked.extend(page["rows"])
                    cursor = page["next_cursor"]
                    if cursor is None:
                        break
                assert _sorted_rows(walked) == legacy_rows, org
                # same COUNT + set of part_keys
                assert {r["part_key"] for r in walked} == {r["part_key"] for r in legacy_rows}

            # Cross-tenant: org A rows never carry org B's die_casting parts.
            a_page = await svc.build_catalog_page(s, org_a, limit=500)
            a_keys = {r["part_key"] for r in a_page["rows"]}
            assert not any(k.startswith("b-") for k in a_keys)
    finally:
        await _cleanup(fx)


@_requires_pg
@pytest.mark.asyncio
async def test_dedup_and_drafted_to_costed_transition():
    """One mesh: analysis (drafted) then cost (costed) updates the ONE summary row
    (not two) and transitions the bucket; a dedup-hit cost persist leaves exactly
    one correct row."""
    import src.db.engine as eng
    from sqlalchemy import text

    fx = _Fixture(uuid.uuid4().hex[:8])
    try:
        async with eng.get_session_factory()() as s:
            org = await fx.org(s, "T")
            u = await fx.user(s, org, "t")
            mesh = f"t-1-{fx.tag}"

            # 1) drafted-only clean analysis → makeable, has_cost False
            await _persist_an(s, u, mesh, _analysis_json(clean=True))
            await s.commit()

        async with eng.get_session_factory()() as s:
            rows = (
                await s.execute(
                    text("SELECT triage_bucket, has_analysis, has_cost FROM "
                         "part_summaries WHERE org_id=:o AND mesh_hash=:m"),
                    {"o": org, "m": mesh},
                )
            ).all()
            assert len(rows) == 1
            assert rows[0][0] == "makeable"
            assert rows[0][1] is True and rows[0][2] is False

        # 2) cost the SAME mesh → still ONE row, now costed + has_cost True
        params = f"params-fixed-{fx.tag}"
        async with eng.get_session_factory()() as s:
            from src.auth.require_api_key import AuthedUser
            # rebind AuthedUser to the same persisted user id + key
            uid = fx.user_ids[-1]
            kid = int(
                (
                    await s.execute(
                        text("SELECT id FROM api_keys WHERE user_id=:u LIMIT 1"),
                        {"u": uid},
                    )
                ).first()[0]
            )
            user = AuthedUser(user_id=uid, api_key_id=kid, key_prefix="t", role="analyst")
            await _persist_cost(s, user, mesh, _cost_json(), params=params)
            await s.commit()

        async with eng.get_session_factory()() as s:
            rows = (
                await s.execute(
                    text("SELECT triage_bucket, has_analysis, has_cost, route_process "
                         "FROM part_summaries WHERE org_id=:o AND mesh_hash=:m"),
                    {"o": org, "m": mesh},
                )
            ).all()
            assert len(rows) == 1                       # updated, not duplicated
            assert rows[0][0] == "makeable"             # clean analysis on route
            assert rows[0][1] is True and rows[0][2] is True
            assert rows[0][3] == "cnc_3axis"

        # 3) dedup-hit cost persist (same params) → still exactly one correct row
        async with eng.get_session_factory()() as s:
            from src.auth.require_api_key import AuthedUser

            uid = fx.user_ids[-1]
            kid = int(
                (
                    await s.execute(
                        text("SELECT id FROM api_keys WHERE user_id=:u LIMIT 1"),
                        {"u": uid},
                    )
                ).first()[0]
            )
            user = AuthedUser(user_id=uid, api_key_id=kid, key_prefix="t", role="analyst")
            d = await _persist_cost(s, user, mesh, _cost_json(), params=params)
            await s.commit()

        async with eng.get_session_factory()() as s:
            cnt = (
                await s.execute(
                    text("SELECT count(*) FROM part_summaries WHERE org_id=:o AND mesh_hash=:m"),
                    {"o": org, "m": mesh},
                )
            ).scalar_one()
            assert cnt == 1
    finally:
        await _cleanup(fx)


@_requires_pg
@pytest.mark.asyncio
async def test_backfill_idempotency_and_parity():
    """Insert raw analyses/cost_decisions (bypassing hooks), backfill, assert the
    summary-backed triage equals the legacy triage; re-run backfill → no change,
    same count."""
    import src.db.engine as eng
    from sqlalchemy import text
    from ulid import ULID

    fx = _Fixture(uuid.uuid4().hex[:8])
    try:
        async with eng.get_session_factory()() as s:
            org = await fx.org(s, "BF")
            u = await fx.user(s, org, "bf")
            uid = fx.user_ids[-1]

            # Raw inserts WITHOUT the service hooks → part_summaries stays empty.
            async def raw_an(mesh, result):
                await s.execute(
                    text(
                        "INSERT INTO analyses (ulid, user_id, org_id, mesh_hash, "
                        "process_set_hash, analysis_version, filename, file_type, "
                        "file_size_bytes, result_json, verdict, face_count, duration_ms) "
                        "VALUES (:ul, :u, :o, :mh, :ph, '0.3.0', :fn, 'stl', 1024, "
                        "CAST(:rj AS jsonb), 'issues', 12, 50.0)"
                    ),
                    {"ul": str(ULID()), "u": uid, "o": org, "mh": mesh,
                     "ph": f"pset-{ULID()}", "fn": f"{mesh}.stl", "rj": json.dumps(result)},
                )

            async def raw_cost(mesh, result):
                await s.execute(
                    text(
                        "INSERT INTO cost_decisions (ulid, user_id, org_id, mesh_hash, "
                        "params_hash, engine_version, filename, file_type, result_json, "
                        "make_now_process, crossover_qty) VALUES (:ul, :u, :o, :mh, :ph, "
                        "'0.3.0', :fn, 'stl', CAST(:rj AS jsonb), :mnp, 500.0)"
                    ),
                    {"ul": str(ULID()), "u": uid, "o": org, "mh": mesh,
                     "ph": f"params-{ULID()}", "fn": f"{mesh}.stl", "rj": json.dumps(result),
                     "mnp": (result.get("decision") or {}).get("make_now_process")},
                )

            await raw_an(f"bf-mk-{fx.tag}", _analysis_json(clean=True))
            await raw_cost(f"bf-mk-{fx.tag}", _cost_json())
            await raw_cost(f"bf-unk-{fx.tag}", _cost_json())
            await raw_an(f"bf-draft-{fx.tag}", _analysis_json(best="die_casting", clean=True))
            await s.commit()

        # Backfill.
        async with eng.get_session_factory()() as s:
            n1 = await pss.backfill_part_summaries(s, org_id=org, batch_size=2)
            await s.commit()
        assert n1 == 3   # three distinct meshes

        async with eng.get_session_factory()() as s:
            legacy = await svc.build_triage(s, org)
            scaled = await svc.build_triage_scaled(s, org)
            assert scaled == legacy

        # Re-run backfill → idempotent (same count, no row change).
        async with eng.get_session_factory()() as s:
            before = (
                await s.execute(
                    text("SELECT count(*), max(triage_bucket) FROM part_summaries WHERE org_id=:o"),
                    {"o": org},
                )
            ).first()
            n2 = await pss.backfill_part_summaries(s, org_id=org, batch_size=500)
            await s.commit()
            after = (
                await s.execute(
                    text("SELECT count(*), max(triage_bucket) FROM part_summaries WHERE org_id=:o"),
                    {"o": org},
                )
            ).first()
        assert n2 == n1
        assert tuple(before) == tuple(after)
    finally:
        await _cleanup(fx)


@_requires_pg
@pytest.mark.asyncio
async def test_keyset_pagination_walks_every_part_once():
    """> limit parts: walking pages via next_cursor yields every part exactly once,
    in (updated_at DESC, mesh_hash DESC) order, next_cursor None only on the last
    page."""
    import src.db.engine as eng

    fx = _Fixture(uuid.uuid4().hex[:8])
    try:
        async with eng.get_session_factory()() as s:
            org = await fx.org(s, "KS")
            u = await fx.user(s, org, "ks")
            for i in range(7):
                await _persist_cost(s, u, f"ks-{i:02d}-{fx.tag}", _cost_json())
            await s.commit()

        async with eng.get_session_factory()() as s:
            legacy = _sorted_rows((await svc.build_catalog(s, org))["rows"])
            walked = []
            cursor = None
            pages = 0
            last_cursor_none_only_at_end = True
            while True:
                page = await svc.build_catalog_page(s, org, cursor=cursor, limit=3)
                pages += 1
                assert len(page["rows"]) <= 3
                walked.extend(page["rows"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
                # a non-final page must always be full (limit rows)
                assert len(page["rows"]) == 3
            # 7 parts / 3 per page → 3 pages (3+3+1)
            assert pages == 3
            keys = [r["part_key"] for r in walked]
            assert len(keys) == 7
            assert len(set(keys)) == 7                 # each exactly once
            assert _sorted_rows(walked) == legacy      # correct order + content
    finally:
        await _cleanup(fx)
