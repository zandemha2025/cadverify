"""Org membership-lifecycle beat — invites, multi-membership, deactivation, audit.

The M6 proof for the org-membership beat that sits on top of 0009's tenancy
ISOLATION. Two layers:

  * Pure unit tests (no DB): the invite token contract — SHA-256 hashing,
    ``secrets``-generated uniqueness, the raw token never equalling its stored
    hash, the pending/expired/accepted/revoked status machine, and the org-role
    rank ordering.
  * Heavy live-Postgres integration: the whole lifecycle against a migrated
    scratch DB (schema at head, through 0024) driven both at the service layer
    (for the precise invite/expiry/last-admin edges) and end-to-end through the
    real routers with only the auth principal overridden — so a green run means
    the membership seam, the current_org_id-validated resolution, the
    deactivation gate on EVERY auth path, and the audit events are all real.

Skipped automatically unless DATABASE_URL is a Postgres URL at schema head. Run:

    DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/orgmem_gate \\
        .venv/bin/python -m pytest tests/test_org_membership.py -q
"""
from __future__ import annotations

import asyncio
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
    """Bind the asyncpg pool to each test's OWN event loop (loop hermeticity).

    ``src.db.engine`` keeps the async engine + session factory as module-level
    singletons. asyncpg attaches every pooled connection (and its Futures) to
    whichever event loop first opened it. pytest-asyncio runs each test on a
    fresh, function-scoped loop, so a pool opened — and left set — by an
    earlier live-Postgres test in another file is bound to a now-closed loop.
    Reusing it (SQLAlchemy's ``pool_pre_ping`` checkout pings the stale
    connection) raises ``RuntimeError: got Future attached to a different
    loop`` at this test's first DB call. In the full suite that is exactly the
    cross-loop poisoning that makes ``test_invite_lifecycle`` explode while it
    passes in isolation.

    We drop the singleton before every test so ``get_session_factory()``
    lazily rebuilds an engine bound to THIS loop, and again after so this file
    never hands a live-loop pool to the next one. We deliberately do NOT
    ``await engine.dispose()`` on the inherited engine — that would drive I/O
    on the foreign, dead loop; abandoning the reference lets it be reclaimed
    (the same benign leak that already exists suite-wide without this file).
    The per-test ``dispose_engine()`` calls inside the tests still run and
    cleanly tear down the engine we built on this loop. Mirrors
    ``tests/test_db_pool.py::reset_engine``.
    """
    import src.db.engine as _eng

    _eng._ENGINE = None
    _eng._SESSION_FACTORY = None
    try:
        yield
    finally:
        _eng._ENGINE = None
        _eng._SESSION_FACTORY = None


# ══════════════════════════════════════════════════════════════════════════
# Pure unit tests — the invite token contract (no DB)
# ══════════════════════════════════════════════════════════════════════════


def test_hash_invite_token_deterministic_sha256_hex():
    h1 = svc.hash_invite_token("hello-token")
    h2 = svc.hash_invite_token("hello-token")
    assert h1 == h2                     # deterministic (it is the lookup key)
    assert len(h1) == 64                # SHA-256 hex
    assert all(c in "0123456789abcdef" for c in h1)
    assert h1 != svc.hash_invite_token("hello-token2")


def test_generate_invite_token_unique_and_hashed():
    raw1, hash1 = svc.generate_invite_token()
    raw2, hash2 = svc.generate_invite_token()
    # secrets-generated: two tokens never collide.
    assert raw1 != raw2 and hash1 != hash2
    # The stored value is the HASH, never the raw token.
    assert hash1 != raw1
    assert svc.hash_invite_token(raw1) == hash1
    # A urlsafe token of real entropy (>= 32 bytes -> >= 43 chars).
    assert len(raw1) >= 40


def _invite(**kw):
    """An in-memory OrgInvite (no session) for status-machine assertions."""
    from src.db.models import OrgInvite

    inv = OrgInvite()
    inv.accepted_at = kw.get("accepted_at")
    inv.revoked_at = kw.get("revoked_at")
    inv.expires_at = kw.get("expires_at", datetime.now(timezone.utc) + timedelta(days=1))
    return inv


def test_invite_status_machine():
    now = datetime.now(timezone.utc)
    assert svc._invite_status(_invite()) == "pending"
    assert svc._invite_status(_invite(expires_at=now - timedelta(minutes=1))) == "expired"
    assert svc._invite_status(_invite(accepted_at=now)) == "accepted"
    assert svc._invite_status(_invite(revoked_at=now)) == "revoked"
    # accepted takes precedence over an expiry that also passed.
    assert (
        svc._invite_status(_invite(accepted_at=now, expires_at=now - timedelta(days=2)))
        == "accepted"
    )


def test_as_aware_treats_naive_as_utc():
    naive = datetime(2030, 1, 1, 12, 0, 0)
    aware = svc._as_aware(naive)
    assert aware.tzinfo is not None
    assert aware.utcoffset() == timedelta(0)
    # An already-aware timestamp is returned unchanged.
    already = datetime(2030, 1, 1, tzinfo=timezone.utc)
    assert svc._as_aware(already) is already


def test_org_role_rank_ordering():
    r = svc.ORG_ROLE_RANK
    assert r["admin"] > r["member"] > r["viewer"]
    assert svc.VALID_ORG_ROLES == {"admin", "member", "viewer"}


def test_invite_ttl_days_clamped(monkeypatch):
    monkeypatch.setenv("ORG_INVITE_TTL_DAYS", "3")
    assert svc._invite_ttl_days() == 3
    monkeypatch.setenv("ORG_INVITE_TTL_DAYS", "9999")   # clamp to max 30
    assert svc._invite_ttl_days() == 30
    monkeypatch.setenv("ORG_INVITE_TTL_DAYS", "0")      # clamp to min 1
    assert svc._invite_ttl_days() == 1
    monkeypatch.setenv("ORG_INVITE_TTL_DAYS", "not-a-number")  # default
    assert svc._invite_ttl_days() == 7


# ══════════════════════════════════════════════════════════════════════════
# Live-PG shared seed / teardown helpers
# ══════════════════════════════════════════════════════════════════════════


async def _mk_user(s, tag, label, *, role="analyst", password_hash=None):
    email = f"orgm-{tag}-{label}@example.com"
    row = (
        await s.execute(
            text(
                "INSERT INTO users (email, email_lower, role, auth_provider, "
                "password_hash) VALUES (:e, :el, :r, 'password', :ph) RETURNING id"
            ),
            {"e": email, "el": email.lower(), "r": role, "ph": password_hash},
        )
    ).first()
    return int(row[0])


async def _mk_org(s, tag, label):
    oid = str(ULID())
    await s.execute(
        text(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES (:id, :n, :sl, now())"
        ),
        {"id": oid, "n": f"Org {label} {tag}", "sl": f"org-{label}-{tag}".lower()},
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


async def _teardown(eng, users, orgs):
    async with eng.get_session_factory()() as s:
        # Any personal orgs auto-provisioned for these users must also go.
        if users:
            rows = (
                await s.execute(
                    text("SELECT DISTINCT org_id FROM memberships WHERE user_id = ANY(:u)"),
                    {"u": users},
                )
            ).all()
            orgs = list({*orgs, *[r[0] for r in rows]})
        if orgs:
            for tbl in ("machine_instances", "part_summaries", "org_invites"):
                await s.execute(
                    text(f"DELETE FROM {tbl} WHERE org_id = ANY(:o)"), {"o": orgs}
                )
        if users:
            await s.execute(
                text("DELETE FROM audit_log WHERE user_id = ANY(:u)"), {"u": users}
            )
            await s.execute(
                text("DELETE FROM api_keys WHERE user_id = ANY(:u)"), {"u": users}
            )
            await s.execute(
                text("DELETE FROM memberships WHERE user_id = ANY(:u)"), {"u": users}
            )
            await s.execute(
                text("DELETE FROM users WHERE id = ANY(:u)"), {"u": users}
            )
        if orgs:
            await s.execute(
                text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": orgs}
            )
        await s.commit()


async def _audit_actions(eng, *, user_ids=None, org_ids=None, resource_id=None):
    """Snapshot of audit_log action rows matching a scope."""
    clauses, params = [], {}
    if user_ids:
        clauses.append("user_id = ANY(:u)")
        params["u"] = user_ids
    if org_ids:
        clauses.append("org_id = ANY(:o)")
        params["o"] = org_ids
    if resource_id is not None:
        clauses.append("resource_id = :rid")
        params["rid"] = resource_id
    where = " AND ".join(clauses) if clauses else "TRUE"
    async with eng.get_session_factory()() as s:
        rows = (
            await s.execute(
                text(f"SELECT action, resource_type, resource_id FROM audit_log WHERE {where}"),
                params,
            )
        ).all()
    return rows


async def _wait_for_audit(eng, expected, *, user_ids=None, org_ids=None, timeout=4.0):
    """Poll audit_log until every action in ``expected`` has landed.

    Audit writes are fire-and-forget ``asyncio.create_task`` background jobs on
    the same loop; awaiting this poll yields control so they run and commit.
    """
    expected = set(expected)
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    seen: set[str] = set()
    while loop.time() < deadline:
        rows = await _audit_actions(eng, user_ids=user_ids, org_ids=org_ids)
        seen = {r[0] for r in rows}
        if expected <= seen:
            return seen
        await asyncio.sleep(0.05)
    return seen


def _act_as(app, user_id, role="analyst"):
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role=role
    )


# ══════════════════════════════════════════════════════════════════════════
# Invite lifecycle — issue / accept / expire / reuse / revoke / cross-org / cap
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_invite_lifecycle():
    import src.db.engine as eng
    from fastapi import HTTPException

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        async with eng.get_session_factory()() as s:
            org_a = await _mk_org(s, tag, "A")
            org_b = await _mk_org(s, tag, "B")
            orgs += [org_a, org_b]
            admin = await _mk_user(s, tag, "admin")
            invitee = await _mk_user(s, tag, "invitee")
            other = await _mk_user(s, tag, "other")
            users += [admin, invitee, other]
            await _mk_membership(s, org_a, admin, "admin")
            await _mk_membership(s, org_b, other, "admin")
            await s.commit()

        # ---- issue: token returned once, only the hash persisted -------------
        async with eng.get_session_factory()() as s:
            # Invite the invitee at their REAL account email (mixed-case, so we
            # still prove normalisation); recipient-binding requires the token
            # be redeemed by the account it was minted for.
            inv, raw = await svc.create_invite(
                s, org_a, "admin", f"ORGM-{tag}-Invitee@Example.com", "member", admin
            )
            await s.commit()
            inv_id = inv.id
            assert inv.email == f"orgm-{tag}-invitee@example.com"   # normalised
            assert inv.token_hash == svc.hash_invite_token(raw)
            assert raw not in inv.token_hash
        # The raw token is NOWHERE in the row.
        async with eng.get_session_factory()() as s:
            stored = (
                await s.execute(
                    text("SELECT token_hash FROM org_invites WHERE id = :i"), {"i": inv_id}
                )
            ).first()[0]
            assert stored != raw and stored == svc.hash_invite_token(raw)

        # ---- role cap (service, defence-in-depth) ----------------------------
        async with eng.get_session_factory()() as s:
            with pytest.raises(HTTPException) as e:
                await svc.create_invite(s, org_a, "member", "x@example.com", "admin", admin)
            assert e.value.status_code == 403
            with pytest.raises(HTTPException) as e:
                await svc.create_invite(s, org_a, "viewer", "y@example.com", "member", admin)
            assert e.value.status_code == 403
            # a member inviting a member (equal rank) is allowed
            ok, _ = await svc.create_invite(s, org_a, "member", "z@example.com", "member", admin)
            assert ok.role == "member"
            with pytest.raises(HTTPException) as e:                 # invalid role
                await svc.create_invite(s, org_a, "admin", "q@example.com", "wizard", admin)
            assert e.value.status_code == 400
            await s.rollback()

        # ---- accept: creates a membership in the TOKEN's org, not any other --
        async with eng.get_session_factory()() as s:
            m, inv2, created = await svc.accept_invite(s, invitee, raw)
            await s.commit()
            assert created is True
            assert m.org_id == org_a          # cross-org replay is impossible:
            assert m.org_role == "member"     # the org is fixed by the token
        async with eng.get_session_factory()() as s:
            # invitee is a member of A and of NO other org (not B).
            member_orgs = {
                r[0]
                for r in (
                    await s.execute(
                        text("SELECT org_id FROM memberships WHERE user_id = :u"),
                        {"u": invitee},
                    )
                ).all()
            }
            assert member_orgs == {org_a}
            assert org_b not in member_orgs

        # ---- reuse-reject: single-use -----------------------------------------
        async with eng.get_session_factory()() as s:
            with pytest.raises(HTTPException) as e:
                await svc.accept_invite(s, other, raw)
            assert e.value.status_code == 409
            await s.rollback()

        # ---- revoke-reject ----------------------------------------------------
        async with eng.get_session_factory()() as s:
            inv3, raw3 = await svc.create_invite(s, org_a, "admin", "rev@example.com", "member", admin)
            await s.commit()
            await svc.revoke_invite(s, org_a, inv3.id)
            await s.commit()
            with pytest.raises(HTTPException) as e:
                await svc.accept_invite(s, other, raw3)
            assert e.value.status_code == 409
            await s.rollback()
            # revoking an accepted invite is a 409 (cannot un-accept)
            with pytest.raises(HTTPException) as e:
                await svc.revoke_invite(s, org_a, inv_id)
            assert e.value.status_code == 409
            await s.rollback()

        # ---- expiry-reject (accept in a FRESH session so it reads the updated
        #      expires_at, not a stale identity-map copy — mirrors a real request)
        async with eng.get_session_factory()() as s:
            inv4, raw4 = await svc.create_invite(s, org_a, "admin", "exp@example.com", "member", admin)
            await s.execute(
                text("UPDATE org_invites SET expires_at = now() - interval '1 hour' WHERE id = :i"),
                {"i": inv4.id},
            )
            await s.commit()
        async with eng.get_session_factory()() as s:
            with pytest.raises(HTTPException) as e:
                await svc.accept_invite(s, other, raw4)
            assert e.value.status_code == 409
            assert "expired" in e.value.detail.lower()
            await s.rollback()

        # ---- bad token -> 404 (no existence leak) ----------------------------
        async with eng.get_session_factory()() as s:
            with pytest.raises(HTTPException) as e:
                await svc.accept_invite(s, other, "totally-made-up-token")
            assert e.value.status_code == 404
            await s.rollback()

        # ---- accept-when-already-member: consume, never escalate -------------
        async with eng.get_session_factory()() as s:
            # promote invitee to admin, issue a *member* invite, accept it:
            await s.execute(
                text("UPDATE memberships SET org_role='admin' WHERE org_id=:o AND user_id=:u"),
                {"o": org_a, "u": invitee},
            )
            inv5, raw5 = await svc.create_invite(s, org_a, "admin", f"orgm-{tag}-invitee@example.com", "member", admin)
            await s.commit()
            m5, _, created5 = await svc.accept_invite(s, invitee, raw5)
            await s.commit()
            assert created5 is False
            assert m5.org_role == "admin"     # NOT downgraded to the invite's role
    finally:
        await _teardown(eng, users, orgs)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Recipient binding — a token minted for one email cannot be redeemed by a
# DIFFERENT authenticated account (invite-abuse / cross-tenant admin grant).
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_invite_recipient_binding_rejects_wrong_email():
    """The core invite-abuse guard: an admin invite minted for victim@... may be
    redeemed ONLY by the victim's account. A different logged-in user (not the
    invitee, not a member) presenting the raw token is rejected with 403 and NO
    membership is created — closing the 'claim a leaked/forwarded seat, incl.
    admin of another tenant' vector."""
    import src.db.engine as eng
    from fastapi import HTTPException

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        async with eng.get_session_factory()() as s:
            org_a = await _mk_org(s, tag, "A")
            orgs.append(org_a)
            admin = await _mk_user(s, tag, "admin")
            attacker = await _mk_user(s, tag, "attacker")
            users += [admin, attacker]
            await _mk_membership(s, org_a, admin, "admin")
            await s.commit()

        # admin mints an ADMIN invite for a victim who has no account here
        victim_email = f"orgm-{tag}-victim@example.com"
        async with eng.get_session_factory()() as s:
            inv, raw = await svc.create_invite(
                s, org_a, "admin", victim_email, "admin", admin
            )
            await s.commit()

        # a DIFFERENT authenticated user (the attacker) presents the raw token
        async with eng.get_session_factory()() as s:
            with pytest.raises(HTTPException) as e:
                await svc.accept_invite(s, attacker, raw)
            assert e.value.status_code == 403
            await s.rollback()

        # NO membership was granted to the attacker; the invite is still pending
        async with eng.get_session_factory()() as s:
            granted = (
                await s.execute(
                    text("SELECT 1 FROM memberships WHERE org_id=:o AND user_id=:u"),
                    {"o": org_a, "u": attacker},
                )
            ).first()
            assert granted is None
            still_pending = (
                await s.execute(
                    text("SELECT accepted_at FROM org_invites WHERE id=:i"),
                    {"i": inv.id},
                )
            ).first()[0]
            assert still_pending is None       # token not consumed by the abuse
    finally:
        await _teardown(eng, users, orgs)
        await eng.dispose_engine()


async def _mk_user_raw(s, email, email_lower, *, role="analyst"):
    """Insert a user with an EXPLICIT email/email_lower pair.

    ``_mk_user`` derives email_lower from the label, so it can't build the
    normalise-collision scenario. This lets a test plant a row whose stored
    email_lower is NON-normalised (as SAML historically provisioned) yet still
    passes the unique(email_lower) constraint — i.e. a distinct account that
    normalise-collides with another.
    """
    row = (
        await s.execute(
            text(
                "INSERT INTO users (email, email_lower, role, auth_provider) "
                "VALUES (:e, :el, :r, 'saml') RETURNING id"
            ),
            {"e": email, "el": email_lower, "r": role},
        )
    ).first()
    return int(row[0])


@_requires_pg
@pytest.mark.asyncio
async def test_invite_recipient_binding_rejects_normalize_collision():
    """Regression for the normalize_email-collision bypass.

    Account uniqueness is on ``email_lower``, but SAML historically stored a
    NON-normalised email_lower (gmail dots/+tags retained), so two DISTINCT
    accounts can collide under ``normalize_email``. The old guard re-derived the
    accepting identity via ``normalize_email(accepting.email)`` and so treated the
    colliding attacker row as the invitee — granting cross-account ADMIN into
    another org. The guard now keys on the stored ``email_lower`` (the real unique
    identity), so:
      * the colliding attacker (email_lower keeps the dot) is REFUSED (403), and
      * the genuinely-invited victim (email_lower == normalised invite) SUCCEEDS.
    """
    import src.db.engine as eng
    from fastapi import HTTPException

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        # victim: normalised email_lower (the account the admin intends to invite)
        victim_email = f"pv{tag}victim@gmail.com"
        # attacker: DISTINCT row whose email_lower retains a gmail dot, so it is a
        # different unique key yet normalise-collides with the victim's.
        attacker_email = f"pv{tag}.victim@gmail.com"
        from src.auth.disposable import normalize_email as _ne
        assert _ne(attacker_email) == _ne(victim_email)     # they DO collide
        assert attacker_email != victim_email               # but are distinct rows

        async with eng.get_session_factory()() as s:
            org_a = await _mk_org(s, tag, "A")
            orgs.append(org_a)
            admin = await _mk_user(s, tag, "admin")
            victim = await _mk_user_raw(s, victim_email, victim_email)
            attacker = await _mk_user_raw(s, attacker_email, attacker_email)
            users += [admin, victim, attacker]
            await _mk_membership(s, org_a, admin, "admin")
            await s.commit()

        # admin mints an ADMIN invite bound to the victim's email
        async with eng.get_session_factory()() as s:
            inv, raw = await svc.create_invite(
                s, org_a, "admin", victim_email, "admin", admin
            )
            await s.commit()

        # the colliding attacker (a DIFFERENT user_id) presents the raw token
        async with eng.get_session_factory()() as s:
            with pytest.raises(HTTPException) as e:
                await svc.accept_invite(s, attacker, raw)
            assert e.value.status_code == 403
            await s.rollback()

        # NO membership granted to the attacker; invite still pending (not consumed)
        async with eng.get_session_factory()() as s:
            granted = (
                await s.execute(
                    text("SELECT org_role FROM memberships WHERE org_id=:o AND user_id=:u"),
                    {"o": org_a, "u": attacker},
                )
            ).first()
            assert granted is None, f"attacker wrongly granted {granted!r}"
            still_pending = (
                await s.execute(
                    text("SELECT accepted_at FROM org_invites WHERE id=:i"),
                    {"i": inv.id},
                )
            ).first()[0]
            assert still_pending is None

        # COMPLETENESS: the genuinely-invited victim CAN still redeem it.
        async with eng.get_session_factory()() as s:
            m, _, created = await svc.accept_invite(s, victim, raw)
            await s.commit()
            assert created is True
            assert m.org_role == "admin"
            assert m.user_id == victim
    finally:
        await _teardown(eng, users, orgs)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_invite_recipient_binding_rejects_mirror_normalize_collision():
    """MIRROR regression for the normalize_email-collision bypass.

    The sibling test above covers the direction where the INVITEE is the
    normalised account and the attacker keeps the dot. This covers the MIRROR —
    the direction the earlier ``email_lower`` guard STILL let through:

      * the invitee is a LEGACY-SAML row whose stored ``email_lower`` is
        NON-normalised (a gmail dot retained, as SAML historically provisioned),
        and
      * a DISTINCT account holds the NORMALISED form.

    The invite is minted for the legacy (dotted) address, so the old guard
    compared each accepting account's ``email_lower`` against
    ``normalize_email(inv.email)``: the NORMALISED attacker matched and redeemed
    the invite — up to an ADMIN seat — into an org it was never invited to, while
    the genuine (dotted) invitee was WRONGLY refused. The fix binds the invite to
    the invitee's resolved ``invited_user_id`` (exact ``email_lower`` match at
    creation), so:
      * the colliding NORMALISED attacker (a different id) is REFUSED (403), and
      * the genuinely-invited LEGACY (dotted) victim SUCCEEDS.
    """
    import src.db.engine as eng
    from fastapi import HTTPException

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        # victim: LEGACY-SAML row, email_lower keeps the gmail dot (NON-normalised)
        victim_email = f"mv{tag}.victim@gmail.com"
        # attacker: DISTINCT row holding the NORMALISED form (dot collapsed)
        attacker_email = f"mv{tag}victim@gmail.com"
        from src.auth.disposable import normalize_email as _ne
        assert _ne(victim_email) == _ne(attacker_email)     # they DO collide
        assert victim_email != attacker_email               # but are distinct rows
        # sanity: it is the VICTIM (not the attacker) whose email_lower is the
        # non-normalised one — the exact mirror of the sibling test.
        assert _ne(victim_email) != victim_email
        assert _ne(attacker_email) == attacker_email

        async with eng.get_session_factory()() as s:
            org_a = await _mk_org(s, tag, "A")
            orgs.append(org_a)
            admin = await _mk_user(s, tag, "admin")
            victim = await _mk_user_raw(s, victim_email, victim_email)
            attacker = await _mk_user_raw(s, attacker_email, attacker_email)
            users += [admin, victim, attacker]
            await _mk_membership(s, org_a, admin, "admin")
            await s.commit()

        # admin mints an ADMIN invite bound to the victim's (dotted, legacy) email
        async with eng.get_session_factory()() as s:
            inv, raw = await svc.create_invite(
                s, org_a, "admin", victim_email, "admin", admin
            )
            await s.commit()
            inv_id = inv.id
            # the invite resolved to the VICTIM's row, not the colliding attacker
            assert inv.invited_user_id == victim

        # the colliding NORMALISED attacker (a DIFFERENT user_id) presents the token
        async with eng.get_session_factory()() as s:
            with pytest.raises(HTTPException) as e:
                await svc.accept_invite(s, attacker, raw)
            assert e.value.status_code == 403
            await s.rollback()

        # NO membership granted to the attacker; invite still pending (not consumed)
        async with eng.get_session_factory()() as s:
            granted = (
                await s.execute(
                    text("SELECT org_role FROM memberships WHERE org_id=:o AND user_id=:u"),
                    {"o": org_a, "u": attacker},
                )
            ).first()
            assert granted is None, f"attacker wrongly granted {granted!r}"
            still_pending = (
                await s.execute(
                    text("SELECT accepted_at FROM org_invites WHERE id=:i"),
                    {"i": inv_id},
                )
            ).first()[0]
            assert still_pending is None

        # COMPLETENESS: the genuinely-invited LEGACY (dotted) victim CAN redeem it.
        async with eng.get_session_factory()() as s:
            m, _, created = await svc.accept_invite(s, victim, raw)
            await s.commit()
            assert created is True
            assert m.org_role == "admin"
            assert m.user_id == victim
    finally:
        await _teardown(eng, users, orgs)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Multi-membership resolution + switch (+ stale current_org_id fallback)
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_multi_membership_resolution_and_switch():
    import src.db.engine as eng
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from sqlalchemy import select

    from src.api.org_routes import router as org_router
    from src.auth.org_context import caller_org_subquery, resolve_org
    from src.auth.rate_limit import limiter

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        async with eng.get_session_factory()() as s:
            org_a = await _mk_org(s, tag, "A")
            org_b = await _mk_org(s, tag, "B")
            orgs += [org_a, org_b]
            u = await _mk_user(s, tag, "u")
            users.append(u)
            await _mk_membership(s, org_a, u, "member")   # oldest
            await _mk_membership(s, org_b, u, "admin")
            await s.commit()

        # default (no current_org_id) -> oldest membership (A), and the
        # correlated subquery used by every org-scoped read agrees.
        async with eng.get_session_factory()() as s:
            assert await resolve_org(s, u) == org_a
            sub = (await s.execute(select(caller_org_subquery(u)))).scalar_one()
            assert sub == org_a

        app = FastAPI()
        app.state.limiter = limiter
        app.include_router(org_router, prefix="/api/v1/orgs")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, u)
            # switch to B -> validated membership -> resolution follows
            r = await ac.post("/api/v1/orgs/switch", json={"org_id": org_b})
            assert r.status_code == 200, r.text
            assert r.json()["org_id"] == org_b and r.json()["org_role"] == "admin"

            r = await ac.get("/api/v1/orgs")
            assert r.status_code == 200
            body = r.json()
            assert body["active_org_id"] == org_b
            assert {o["org_id"] for o in body["organizations"]} == {org_a, org_b}

            # switching to an org the user does NOT belong to -> 403 (never silent)
            outsider_org = str(ULID())
            r = await ac.post("/api/v1/orgs/switch", json={"org_id": outsider_org})
            assert r.status_code == 403

        async with eng.get_session_factory()() as s:
            assert await resolve_org(s, u) == org_b        # switch persisted

        # stale current_org_id: it points at a REAL org (the FK forbids a dangling
        # id) that the user is NOT a member of — e.g. an org they were removed
        # from. Resolution must ignore the un-validated pointer and fall back to
        # the oldest real membership; never a 500, never a leak of org_c.
        async with eng.get_session_factory()() as s:
            org_c = await _mk_org(s, tag, "C")
            orgs.append(org_c)
            await s.execute(
                text("UPDATE users SET current_org_id = :x WHERE id = :u"),
                {"x": org_c, "u": u},
            )
            await s.commit()
        async with eng.get_session_factory()() as s:
            assert await resolve_org(s, u) == org_a
            sub = (await s.execute(select(caller_org_subquery(u)))).scalar_one()
            assert sub == org_a
    finally:
        await _teardown(eng, users, orgs)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Removed member loses access on the very next request
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_removed_member_loses_access_next_request():
    import src.db.engine as eng
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.api.org_routes import router as org_router
    from src.auth.org_context import resolve_org
    from src.auth.rate_limit import limiter

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        async with eng.get_session_factory()() as s:
            org_a = await _mk_org(s, tag, "A")
            orgs.append(org_a)
            admin = await _mk_user(s, tag, "admin")
            member = await _mk_user(s, tag, "member")
            users += [admin, member]
            await _mk_membership(s, org_a, admin, "admin")
            await _mk_membership(s, org_a, member, "member")
            await s.execute(
                text("UPDATE users SET current_org_id = :o WHERE id = :u"),
                {"o": org_a, "u": member},
            )
            await s.commit()

        app = FastAPI()
        app.state.limiter = limiter
        app.include_router(org_router, prefix="/api/v1/orgs")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # member can read the roster BEFORE removal
            _act_as(app, member)
            assert (await ac.get("/api/v1/orgs/members")).status_code == 200

            # admin removes the member
            _act_as(app, admin)
            r = await ac.delete(f"/api/v1/orgs/members/{member}")
            assert r.status_code == 200, r.text

            # next request from the removed member -> 403 (membership re-validated)
            _act_as(app, member)
            r = await ac.get("/api/v1/orgs/members")
            assert r.status_code == 403
            assert r.json()["detail"]["code"] == "insufficient_org_role"

        async with eng.get_session_factory()() as s:
            # membership gone; stale current_org_id cleared; resolution -> None
            gone = (
                await s.execute(
                    text("SELECT 1 FROM memberships WHERE org_id=:o AND user_id=:u"),
                    {"o": org_a, "u": member},
                )
            ).first()
            assert gone is None
            cur = (
                await s.execute(
                    text("SELECT current_org_id FROM users WHERE id=:u"), {"u": member}
                )
            ).first()[0]
            assert cur is None
            assert await resolve_org(s, member) is None
    finally:
        await _teardown(eng, users, orgs)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Last-admin protection — demote / remove / leave
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_last_admin_protection():
    import src.db.engine as eng
    from fastapi import FastAPI, HTTPException
    from httpx import ASGITransport, AsyncClient

    from src.api.org_routes import router as org_router
    from src.auth.rate_limit import limiter

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        async with eng.get_session_factory()() as s:
            org_a = await _mk_org(s, tag, "A")
            orgs.append(org_a)
            admin = await _mk_user(s, tag, "admin")
            admin2 = await _mk_user(s, tag, "admin2")
            users += [admin, admin2]
            await _mk_membership(s, org_a, admin, "admin")
            await _mk_membership(s, org_a, admin2, "admin")
            await s.commit()

        # Service: with two admins, demoting one is allowed; the survivor is the
        # last admin and can no longer be demoted / removed / leave.
        async with eng.get_session_factory()() as s:
            await svc.change_member_role(s, org_a, admin2, "member")
            await s.commit()
            with pytest.raises(HTTPException) as e:
                await svc.change_member_role(s, org_a, admin, "member")
            assert e.value.status_code == 409
            await s.rollback()
            with pytest.raises(HTTPException) as e:      # last admin can't leave
                await svc.remove_member(s, org_a, admin, admin)
            assert e.value.status_code == 409
            await s.rollback()
            with pytest.raises(HTTPException) as e:      # last admin can't be removed
                await svc.remove_member(s, org_a, admin, admin2)
            assert e.value.status_code == 409
            await s.rollback()

        # Router: the sole admin cannot demote self nor leave.
        app = FastAPI()
        app.state.limiter = limiter
        app.include_router(org_router, prefix="/api/v1/orgs")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, admin)
            r = await ac.patch(f"/api/v1/orgs/members/{admin}/role", json={"role": "member"})
            assert r.status_code == 409
            r = await ac.delete(f"/api/v1/orgs/members/{admin}")
            assert r.status_code == 409
            # the still-present admin remains an admin
            assert (
                await ac.get("/api/v1/orgs/members")
            ).status_code == 200
    finally:
        await _teardown(eng, users, orgs)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Deactivation matrix — every auth path is blocked
# ══════════════════════════════════════════════════════════════════════════


def _authpath_app():
    """password router + a Bearer-protected and a session-protected route, all
    on the REAL auth dependencies (no override) so we exercise the true gate."""
    from fastapi import Depends, FastAPI

    from src.auth.dashboard_session import require_dashboard_session
    from src.auth.password import router as password_router
    from src.auth.require_api_key import AuthedUser, require_api_key

    app = FastAPI()
    app.include_router(password_router, prefix="/auth")

    @app.get("/protected")
    async def _protected(user: AuthedUser = Depends(require_api_key)):
        return {"user_id": user.user_id, "role": user.role, "api_key_id": user.api_key_id}

    @app.get("/session-only")
    async def _session_only(uid: int = Depends(require_dashboard_session)):
        return {"user_id": uid}

    return app


@_requires_pg
@pytest.mark.asyncio
async def test_deactivation_blocks_password_login():
    import src.db.engine as eng
    from httpx import ASGITransport, AsyncClient

    tag = uuid.uuid4().hex[:10]
    email = f"pwdeact-{tag}@example.com"
    users: list[int] = []
    orgs: list[str] = []
    app = _authpath_app()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.post("/auth/signup", json={"email": email, "password": "Passw0rd123"})
            assert r.status_code == 200, r.text
            uid = r.json()["user"]["id"]
            users.append(uid)

            # active account logs in fine
            assert (
                await ac.post("/auth/login", json={"email": email, "password": "Passw0rd123"})
            ).status_code == 200

            # deactivate the account
            async with eng.get_session_factory()() as s:
                await s.execute(
                    text("UPDATE users SET is_active=false, deactivated_at=now() WHERE id=:u"),
                    {"u": uid},
                )
                await s.commit()

            # correct password now -> 403 account_deactivated (only the real owner
            # sees this; it comes AFTER the password check)
            r = await ac.post("/auth/login", json={"email": email, "password": "Passw0rd123"})
            assert r.status_code == 403
            assert r.json()["detail"]["code"] == "account_deactivated"

            # wrong password on the deactivated account still -> generic 401 (no
            # account-existence / status enumeration for an outsider)
            r = await ac.post("/auth/login", json={"email": email, "password": "WrongPass99"})
            assert r.status_code == 401
            assert r.json()["detail"]["code"] == "invalid_credentials"
    finally:
        # _teardown collects the signup-provisioned personal org from the user's
        # memberships, then deletes memberships/user/org (uid is always captured
        # on the success path; on a failure path nothing was provisioned).
        await _teardown(eng, users, orgs)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_deactivation_blocks_session_and_api_key():
    import src.db.engine as eng
    from httpx import ASGITransport, AsyncClient

    from src.auth.dashboard_session import sign
    from src.auth.hashing import hmac_index, mint_token
    from src.auth.org_context import resolve_org

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    app = _authpath_app()
    transport = ASGITransport(app=app)
    try:
        async with eng.get_session_factory()() as s:
            org_a = await _mk_org(s, tag, "A")
            orgs.append(org_a)
            uid = await _mk_user(s, tag, "u")
            users.append(uid)
            await _mk_membership(s, org_a, uid, "admin")
            await s.commit()

        # mint a real API key for the user
        token, prefix, secret_hash = mint_token()
        async with eng.get_session_factory()() as s:
            await s.execute(
                text(
                    "INSERT INTO api_keys (user_id, org_id, name, prefix, hmac_index, "
                    "secret_hash) VALUES (:u, :o, 'k', :p, :h, :sh)"
                ),
                {"u": uid, "o": org_a, "p": prefix, "h": hmac_index(token), "sh": secret_hash},
            )
            await s.commit()

        cookie = {"Cookie": f"dash_session={sign(uid)}"}
        bearer = {"Authorization": f"Bearer {token}"}
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # ACTIVE: every path works
            assert (await ac.get("/protected", headers=bearer)).status_code == 200
            assert (await ac.get("/protected", headers=cookie)).status_code == 200
            assert (await ac.get("/session-only", headers=cookie)).status_code == 200

            # deactivate
            async with eng.get_session_factory()() as s:
                await s.execute(
                    text("UPDATE users SET is_active=false, deactivated_at=now() WHERE id=:u"),
                    {"u": uid},
                )
                await s.commit()

            # DEACTIVATED: API key, session-via-api-key, and dashboard-session all 403
            r = await ac.get("/protected", headers=bearer)
            assert r.status_code == 403 and r.json()["detail"]["code"] == "account_deactivated"
            r = await ac.get("/protected", headers=cookie)
            assert r.status_code == 403 and r.json()["detail"]["code"] == "account_deactivated"
            r = await ac.get("/session-only", headers=cookie)
            assert r.status_code == 403 and r.json()["detail"]["code"] == "account_deactivated"
    finally:
        await _teardown(eng, users, orgs)
        await eng.dispose_engine()


@_requires_pg
@pytest.mark.asyncio
async def test_deactivation_blocks_sso_reprovision_no_resurrection():
    """upsert_user (the shared Google/SAML/magic-link entry) must refuse — and
    NOT resurrect — a deactivated account on re-login."""
    import src.db.engine as eng
    from fastapi import HTTPException

    from src.auth.disposable import normalize_email
    from src.auth.models import upsert_user

    tag = uuid.uuid4().hex[:10]
    email = f"sso-{tag}@example.com"
    email_norm = normalize_email(email)
    users: list[int] = []
    orgs: list[str] = []
    try:
        # first login provisions a brand-new, ACTIVE account
        uid = await upsert_user(email, f"google-{tag}", email_norm)
        users.append(uid)
        async with eng.get_session_factory()() as s:
            active = (
                await s.execute(text("SELECT is_active FROM users WHERE id=:u"), {"u": uid})
            ).first()[0]
            assert active is True

            # an admin deactivates the account
            await s.execute(
                text("UPDATE users SET is_active=false, deactivated_at=now() WHERE id=:u"),
                {"u": uid},
            )
            await s.commit()

        # re-login via SSO -> 403, and the row is NOT reactivated
        with pytest.raises(HTTPException) as e:
            await upsert_user(email, f"google-{tag}", email_norm)
        assert e.value.status_code == 403
        async with eng.get_session_factory()() as s:
            still = (
                await s.execute(text("SELECT is_active FROM users WHERE id=:u"), {"u": uid})
            ).first()[0]
            assert still is False    # never resurrected
    finally:
        await _teardown(eng, users, orgs)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Admin deactivate/reactivate endpoint + its audit events (superadmin-only)
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_admin_deactivate_reactivate_and_audit():
    import src.db.engine as eng
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.api.admin_routes import router as admin_router

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        async with eng.get_session_factory()() as s:
            org_a = await _mk_org(s, tag, "A")
            orgs.append(org_a)
            superadmin = await _mk_user(s, tag, "super", role="superadmin")
            target = await _mk_user(s, tag, "target")
            org_admin = await _mk_user(s, tag, "orgadmin")
            users += [superadmin, target, org_admin]
            await _mk_membership(s, org_a, org_admin, "admin")
            await _mk_membership(s, org_a, target, "member")
            await s.commit()

        app = FastAPI()
        app.include_router(admin_router)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # a non-superadmin (even an org admin) cannot deactivate
            _act_as(app, org_admin, "analyst")
            r = await ac.post(f"/api/v1/admin/users/{target}/deactivate")
            assert r.status_code == 403

            _act_as(app, superadmin, "superadmin")
            # cannot deactivate yourself
            r = await ac.post(f"/api/v1/admin/users/{superadmin}/deactivate")
            assert r.status_code == 400

            # deactivate the target
            r = await ac.post(f"/api/v1/admin/users/{target}/deactivate")
            assert r.status_code == 200, r.text
            assert r.json()["is_active"] is False
            assert r.json()["deactivated_at"] is not None

            # reactivate
            r = await ac.post(f"/api/v1/admin/users/{target}/reactivate")
            assert r.status_code == 200
            assert r.json()["is_active"] is True
            assert r.json()["deactivated_at"] is None

        async with eng.get_session_factory()() as s:
            final = (
                await s.execute(text("SELECT is_active FROM users WHERE id=:u"), {"u": target})
            ).first()[0]
            assert final is True

        seen = await _wait_for_audit(
            eng, {"user.deactivated", "user.reactivated"}, user_ids=[superadmin]
        )
        assert {"user.deactivated", "user.reactivated"} <= seen
    finally:
        await _teardown(eng, users, orgs)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Org-lifecycle audit events, end-to-end through the org router
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_org_lifecycle_audit_events():
    import src.db.engine as eng
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.api.org_routes import router as org_router
    from src.auth.rate_limit import limiter

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        async with eng.get_session_factory()() as s:
            seed_org = await _mk_org(s, tag, "seed")
            orgs.append(seed_org)
            founder = await _mk_user(s, tag, "founder")
            teammate = await _mk_user(s, tag, "teammate")
            users += [founder, teammate]
            # founder already admins a seed org so create/invite have a context
            await _mk_membership(s, seed_org, founder, "admin")
            await s.commit()

        app = FastAPI()
        app.state.limiter = limiter
        app.include_router(org_router, prefix="/api/v1/orgs")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, founder)
            # org.created
            r = await ac.post("/api/v1/orgs", json={"name": f"NewCo {tag}"})
            assert r.status_code == 201, r.text
            new_org = r.json()["org_id"]
            orgs.append(new_org)

            # switch into it so subsequent invite/member ops target NewCo
            assert (await ac.post("/api/v1/orgs/switch", json={"org_id": new_org})).status_code == 200

            # member.invited
            r = await ac.post(
                "/api/v1/orgs/invites",
                json={"email": f"orgm-{tag}-teammate@example.com", "role": "member"},
            )
            assert r.status_code == 201, r.text
            assert "accept_link" in r.json() and r.json()["accept_link"]
            raw = r.json()["accept_link"].split("token=")[1]

            # member.joined (as the invitee)
            _act_as(app, teammate)
            r = await ac.post("/api/v1/orgs/invites/accept", json={"token": raw})
            assert r.status_code == 200, r.text
            assert r.json()["org_id"] == new_org and r.json()["created"] is True

            # member.role_changed (founder promotes teammate)
            _act_as(app, founder)
            r = await ac.patch(f"/api/v1/orgs/members/{teammate}/role", json={"role": "admin"})
            assert r.status_code == 200

            # member.left (teammate leaves themselves — now safe, two admins)
            _act_as(app, teammate)
            r = await ac.delete(f"/api/v1/orgs/members/{teammate}")
            assert r.status_code == 200

            # member.removed (re-invite, re-accept, founder removes)
            _act_as(app, founder)
            r = await ac.post(
                "/api/v1/orgs/invites",
                json={"email": f"orgm-{tag}-teammate@example.com", "role": "member"},
            )
            raw2 = r.json()["accept_link"].split("token=")[1]
            _act_as(app, teammate)
            assert (await ac.post("/api/v1/orgs/invites/accept", json={"token": raw2})).status_code == 200
            _act_as(app, founder)
            assert (await ac.delete(f"/api/v1/orgs/members/{teammate}")).status_code == 200

        expected = {
            "org.created", "org.switched", "member.invited",
            "member.joined", "member.role_changed", "member.left", "member.removed",
        }
        seen = await _wait_for_audit(eng, expected, user_ids=[founder, teammate])
        assert expected <= seen, f"missing: {expected - seen}"
    finally:
        await _teardown(eng, users, orgs)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Product-CRUD audit: machine.created end-to-end (representative)
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_machine_created_audit_event():
    import src.db.engine as eng
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from src.api.machine_inventory import router as m_router
    from src.auth.rate_limit import limiter

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        async with eng.get_session_factory()() as s:
            org_a = await _mk_org(s, tag, "A")
            orgs.append(org_a)
            uid = await _mk_user(s, tag, "u")
            users.append(uid)
            await _mk_membership(s, org_a, uid, "admin")
            await s.commit()

        app = FastAPI()
        app.state.limiter = limiter
        app.include_router(m_router, prefix="/api/v1/machine-inventory")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            _act_as(app, uid)
            body = {
                "name": f"VF-2 {tag}", "process": "cnc_3axis", "count": 1,
                "max_workpiece_kg": 200, "hourly_rate_usd": 75, "capital_frac": 0.4,
                "capabilities": {"x": 762, "y": 406, "z": 508, "axes": 3,
                                 "achievable_it_grade": 9},
                "materials": ["304 Stainless"],
            }
            r = await ac.post("/api/v1/machine-inventory", json=body)
            assert r.status_code == 201, r.text

        seen = await _wait_for_audit(eng, {"machine.created"}, user_ids=[uid])
        assert "machine.created" in seen
    finally:
        await _teardown(eng, users, orgs)
        await eng.dispose_engine()


# ══════════════════════════════════════════════════════════════════════════
# Product audit-sink plumbing for the remaining §35 events. The endpoint wiring
# for these is a single ``emit_event`` / ``fire_and_forget_audit`` call each
# (each router has its own green live-PG test); here we prove the shared sink
# actually persists a row for every one of those action names.
# ══════════════════════════════════════════════════════════════════════════


@_requires_pg
@pytest.mark.asyncio
async def test_product_audit_events_persist():
    import src.db.engine as eng

    from src.services.audit_service import emit_event, fire_and_forget_audit

    tag = uuid.uuid4().hex[:10]
    users: list[int] = []
    orgs: list[str] = []
    try:
        async with eng.get_session_factory()() as s:
            org_a = await _mk_org(s, tag, "A")
            orgs.append(org_a)
            uid = await _mk_user(s, tag, "u")
            users.append(uid)
            await _mk_membership(s, org_a, uid, "admin")
            await s.commit()

        rid = f"res-{tag}"
        # fire_and_forget_audit is a coroutine -> awaiting it commits synchronously.
        for action, rtype in (
            ("decision.created", "cost_decision"),
            ("library.version_published", "rate_card"),
            ("governance.approved", "change_request"),
            ("governance.rejected", "change_request"),
            ("groundtruth.ingested", "ground_truth"),
        ):
            await fire_and_forget_audit(
                user_id=uid, user_email=f"orgm-{tag}@example.com", action=action,
                resource_type=rtype, resource_id=rid, detail={"org_id": org_a},
            )
        # emit_event schedules a background task -> poll for it.
        emit_event(uid, "machine.updated", "machine", rid, {"org_id": org_a})

        expected = {
            "decision.created", "library.version_published", "governance.approved",
            "governance.rejected", "groundtruth.ingested", "machine.updated",
        }
        seen = await _wait_for_audit(eng, expected, user_ids=[uid])
        assert expected <= seen, f"missing: {expected - seen}"
    finally:
        await _teardown(eng, users, orgs)
        await eng.dispose_engine()
