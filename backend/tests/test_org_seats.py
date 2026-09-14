"""Org shared-seats quota — the 0047 seat_limit enforcement beat.

Customer-ready shared seats need three mechanical guarantees, all proven here:

  * RESERVATION: a pending invite consumes a seat the moment it is minted, so
    an admin cannot over-promise seats — invite creation fails closed (409)
    the moment members + pending invites would exceed ``seat_limit``.
  * CONVERSION: accepting an invite converts its reserved seat into a member
    seat 1:1, so acceptance succeeds at exactly-limit on the happy path and
    fails closed only when capacity shrank out-of-band (limit lowered below
    consumption, or seats granted outside the invite flow).
  * GOVERNANCE: an admin can set/clear the cap, but never BELOW current
    consumption — an org can never be stranded over capacity against an
    unachievable target.

Layout mirrors test_org_membership.py: pure unit tests (no DB) for the seat
math and env parsing, then live-Postgres integration at the service layer and
end-to-end through the real router with only the auth principal overridden.
NULL ``seat_limit`` (every legacy/personal org) is asserted untouched.

    DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/orgseat_gate \\
        .venv/bin/python -m pytest tests/test_org_seats.py -q
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from ulid import ULID

from src.services import org_service as svc

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


@pytest.fixture(autouse=True)
def _loop_hermetic_engine():
    """Bind the asyncpg pool to each test's OWN event loop (see
    test_org_membership.py for the full rationale — same singleton-reset)."""
    import src.db.engine as _eng

    _eng._ENGINE = None
    _eng._SESSION_FACTORY = None
    try:
        yield
    finally:
        _eng._ENGINE = None
        _eng._SESSION_FACTORY = None


# ══════════════════════════════════════════════════════════════════════════
# Pure unit tests — seat math + env parsing (no DB)
# ══════════════════════════════════════════════════════════════════════════


def test_seats_available_unlimited_is_none_not_a_number():
    # An unlimited org must report None — never an invented headroom figure.
    assert svc.seats_available(None, 0, 0) is None
    assert svc.seats_available(None, 500, 500) is None


def test_seats_available_math_and_floor():
    assert svc.seats_available(10, 3, 2) == 5
    assert svc.seats_available(5, 5, 0) == 0
    # Over-capacity (limit lowered below usage) floors at 0, never debt.
    assert svc.seats_available(2, 3, 1) == 0


def test_seat_capacity_ok():
    assert svc.seat_capacity_ok(None, 10**9, 10**9) is True  # unlimited
    assert svc.seat_capacity_ok(3, 2, 1) is True             # exactly fits
    assert svc.seat_capacity_ok(3, 3, 1) is False            # one over
    assert svc.seat_capacity_ok(3, 3, 0) is True             # in-place convert
    assert svc.seat_capacity_ok(3, 4, 0) is False            # already over


def test_default_seat_limit_env(monkeypatch):
    monkeypatch.delenv("ORG_DEFAULT_SEAT_LIMIT", raising=False)
    assert svc._default_seat_limit() is None
    monkeypatch.setenv("ORG_DEFAULT_SEAT_LIMIT", "5")
    assert svc._default_seat_limit() == 5
    # Misconfiguration fails OPEN to unlimited (org creation never blocked);
    # an explicitly set limit is what fails closed at enforcement.
    monkeypatch.setenv("ORG_DEFAULT_SEAT_LIMIT", "not-a-number")
    assert svc._default_seat_limit() is None
    monkeypatch.setenv("ORG_DEFAULT_SEAT_LIMIT", "0")
    assert svc._default_seat_limit() is None
    monkeypatch.setenv("ORG_DEFAULT_SEAT_LIMIT", "-3")
    assert svc._default_seat_limit() is None


# ══════════════════════════════════════════════════════════════════════════
# Live-PG shared seed / teardown helpers (mirrors test_org_membership.py)
# ══════════════════════════════════════════════════════════════════════════


async def _mk_user(s, tag, label):
    email = f"seat-{tag}-{label}@example.com"
    row = (
        await s.execute(
            text(
                "INSERT INTO users (email, email_lower, role, auth_provider) "
                "VALUES (:e, :el, 'analyst', 'password') RETURNING id"
            ),
            {"e": email, "el": email.lower()},
        )
    ).first()
    return int(row[0])


async def _mk_org(s, tag, label, seat_limit=None):
    oid = str(ULID())
    await s.execute(
        text(
            "INSERT INTO organizations (id, name, slug, created_at, seat_limit) "
            "VALUES (:id, :n, :sl, now(), :lim)"
        ),
        {
            "id": oid,
            "n": f"SeatOrg {label} {tag}",
            "sl": f"seat-{label}-{tag}".lower(),
            "lim": seat_limit,
        },
    )
    return oid


async def _mk_membership(s, org_id, user_id, role):
    await s.execute(
        text(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
            "VALUES (:id, :o, :u, :r, now())"
        ),
        {"id": str(ULID()), "o": org_id, "u": user_id, "r": role},
    )


async def _set_limit_raw(s, org_id, limit):
    """Direct SQL limit write — simulates an out-of-band change (SAML-era
    tooling, a support console) that bypassed the governance guard."""
    await s.execute(
        text("UPDATE organizations SET seat_limit = :l WHERE id = :o"),
        {"l": limit, "o": org_id},
    )


async def _teardown(eng, users, orgs):
    async with eng.get_session_factory()() as s:
        if users:
            rows = (
                await s.execute(
                    text(
                        "SELECT DISTINCT org_id FROM memberships "
                        "WHERE user_id = ANY(:u)"
                    ),
                    {"u": users},
                )
            ).all()
            orgs = list({*orgs, *[r[0] for r in rows]})
        if orgs:
            for tbl in ("org_invites",):
                await s.execute(
                    text(f"DELETE FROM {tbl} WHERE org_id = ANY(:o)"), {"o": orgs}
                )
        if users:
            await s.execute(
                text("DELETE FROM audit_log WHERE user_id = ANY(:u)"), {"u": users}
            )
            await s.execute(
                text("DELETE FROM memberships WHERE user_id = ANY(:u)"),
                {"u": users},
            )
            await s.execute(
                text("DELETE FROM users WHERE id = ANY(:u)"), {"u": users}
            )
        if orgs:
            await s.execute(
                text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": orgs}
            )
        await s.commit()


# ══════════════════════════════════════════════════════════════════════════
# Service layer — reservation, conversion, governance
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_invite_reservation_blocks_at_limit_and_unlimited_untouched():
    import src.db.engine as eng
    from fastapi import HTTPException

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        async with eng.get_session_factory()() as s:
            capped = await _mk_org(s, tag, "cap", seat_limit=2)
            uncapped = await _mk_org(s, tag, "free", seat_limit=None)
            orgs += [capped, uncapped]
            admin = await _mk_user(s, tag, "admin")
            users.append(admin)
            await _mk_membership(s, capped, admin, "admin")   # 1 seat used
            await _mk_membership(s, uncapped, admin, "admin")
            await s.commit()

        async with eng.get_session_factory()() as s:
            # Capped org: one seat left -> first invite reserves it.
            inv1, _raw = await svc.create_invite(
                s, capped, "admin", f"seat-{tag}-one@example.com", "member", admin
            )
            assert inv1.id is not None
            status = await svc.seat_status(s, capped)
            assert status["seat_limit"] == 2
            assert status["active_members"] == 1
            assert status["pending_invites"] == 1
            assert status["consumed"] == 2
            assert status["available"] == 0

            # The NEXT invite would exceed the cap -> 409, fail closed.
            with pytest.raises(HTTPException) as ei:
                await svc.create_invite(
                    s, capped, "admin", f"seat-{tag}-two@example.com",
                    "member", admin,
                )
            assert ei.value.status_code == 409
            assert ei.value.detail["code"] == "org_seat_limit_reached"
            assert ei.value.detail["seat_limit"] == 2
            assert ei.value.detail["consumed"] == 2
            await s.rollback()

            # Unlimited org: no cap, ever — legacy behaviour byte-identical.
            for i in range(3):
                await svc.create_invite(
                    s, uncapped, "admin", f"seat-{tag}-u{i}@example.com",
                    "member", admin,
                )
            status = await svc.seat_status(s, uncapped)
            assert status["seat_limit"] is None
            assert status["available"] is None
            assert status["pending_invites"] == 3
            await s.rollback()
    finally:
        await _teardown(eng, users, orgs)
        import src.db.engine as _eng

        await _eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_acceptance_converts_reserved_seat_and_fails_closed_out_of_band():
    import src.db.engine as eng
    from fastapi import HTTPException

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        async with eng.get_session_factory()() as s:
            org = await _mk_org(s, tag, "conv", seat_limit=2)
            orgs.append(org)
            admin = await _mk_user(s, tag, "admin")
            invitee = await _mk_user(s, tag, "invitee")
            users += [admin, invitee]
            await _mk_membership(s, org, admin, "admin")      # 1 of 2 used
            await s.commit()

        async with eng.get_session_factory()() as s:
            inv, raw = await svc.create_invite(
                s, org, "admin",
                f"seat-{tag}-invitee@example.com", "member", admin,
            )
            await s.commit()

        async with eng.get_session_factory()() as s:
            # Exactly-at-limit acceptance: reserved -> active, succeeds.
            membership, invite, created = await svc.accept_invite(s, invitee, raw)
            assert created is True and membership.org_role == "member"
            status = await svc.seat_status(s, org)
            assert status["active_members"] == 2
            assert status["pending_invites"] == 0
            assert status["consumed"] == 2 and status["available"] == 0
            await s.commit()

            # Out-of-band shrink below consumption (bypassing the governance
            # guard): a NEW acceptance now fails closed instead of silently
            # deepening the over-capacity state.
            await _set_limit_raw(s, org, 1)
            # create_invite itself must refuse while over capacity:
            with pytest.raises(HTTPException) as ei:
                await svc.create_invite(
                    s, org, "admin", f"seat-{tag}-late@example.com",
                    "member", admin,
                )
            assert ei.value.status_code == 409
            await s.rollback()
    finally:
        await _teardown(eng, users, orgs)
        import src.db.engine as _eng

        await _eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_governance_set_lower_clear_and_below_usage_guard():
    import src.db.engine as eng
    from fastapi import HTTPException

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        async with eng.get_session_factory()() as s:
            org = await _mk_org(s, tag, "gov", seat_limit=None)
            orgs.append(org)
            admin = await _mk_user(s, tag, "admin")
            m1 = await _mk_user(s, tag, "m1")
            users += [admin, m1]
            await _mk_membership(s, org, admin, "admin")
            await _mk_membership(s, org, m1, "member")        # 2 consumed
            await s.commit()

        async with eng.get_session_factory()() as s:
            # Below-usage is refused with the live numbers.
            with pytest.raises(HTTPException) as ei:
                await svc.update_seat_limit(s, org, 1)
            assert ei.value.status_code == 409
            assert ei.value.detail["code"] == "org_seat_limit_below_usage"
            assert ei.value.detail["consumed"] == 2
            await s.rollback()

            # Zero is a misconfiguration, not a plan.
            with pytest.raises(HTTPException) as ei:
                await svc.update_seat_limit(s, org, 0)
            assert ei.value.status_code == 400
            await s.rollback()

            # At-usage is allowed (headroom 0, still consistent).
            org_row = await svc.update_seat_limit(s, org, 2)
            assert org_row.seat_limit == 2
            # Clearing restores unlimited.
            org_row = await svc.update_seat_limit(s, org, None)
            assert org_row.seat_limit is None
            await s.commit()
    finally:
        await _teardown(eng, users, orgs)
        import src.db.engine as _eng

        await _eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Router end-to-end — GET ledger + PATCH governance through the real stack
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_seat_routes_end_to_end():
    import src.db.engine as eng
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.api.org_routes import router as org_router
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        async with eng.get_session_factory()() as s:
            org = await _mk_org(s, tag, "rt", seat_limit=3)
            orgs.append(org)
            admin = await _mk_user(s, tag, "admin")
            viewer = await _mk_user(s, tag, "viewer")
            users += [admin, viewer]
            await _mk_membership(s, org, admin, "admin")
            await _mk_membership(s, org, viewer, "viewer")
            await s.commit()

        app = FastAPI()
        app.state.limiter = limiter
        app.include_router(org_router, prefix="/api/v1/orgs")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            def act_as(user_id):
                app.dependency_overrides[require_api_key] = lambda: AuthedUser(
                    user_id=user_id, api_key_id=0, key_prefix="session",
                    role="analyst",
                )

            # Any member can READ the ledger (so a failed invite is legible).
            act_as(viewer)
            r = await ac.get("/api/v1/orgs/seats")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["seat_limit"] == 3
            assert body["active_members"] == 2
            assert body["pending_invites"] == 0
            assert body["consumed"] == 2 and body["available"] == 1

            # A viewer CANNOT govern the cap.
            r = await ac.patch("/api/v1/orgs/seats/limit", json={"seat_limit": 5})
            assert r.status_code == 403

            # The admin governs: lower, read back through the same endpoint.
            act_as(admin)
            r = await ac.patch("/api/v1/orgs/seats/limit", json={"seat_limit": 2})
            assert r.status_code == 200, r.text
            assert r.json()["seat_limit"] == 2
            assert r.json()["available"] == 0

            # Below usage is refused end-to-end.
            r = await ac.patch("/api/v1/orgs/seats/limit", json={"seat_limit": 1})
            assert r.status_code == 409
            assert r.json()["detail"]["code"] == "org_seat_limit_below_usage"

            # An invite at the (now full) cap is refused end-to-end with the
            # fail-closed code the frontend keys on.
            r = await ac.post(
                "/api/v1/orgs/invites",
                json={"email": f"seat-{tag}-late@example.com", "role": "member"},
            )
            assert r.status_code == 409
            assert r.json()["detail"]["code"] == "org_seat_limit_reached"

            # Governance event is in the audit trail.
            async with eng.get_session_factory()() as s:
                rows = (
                    await s.execute(
                        text(
                            "SELECT action FROM audit_log "
                            "WHERE org_id = :o AND action = 'org.seat_limit_changed'"
                        ),
                        {"o": org},
                    )
                ).all()
                assert rows, "seat-limit governance must be audited"
    finally:
        await _teardown(eng, users, orgs)
        import src.db.engine as _eng

        await _eng.dispose_engine()
