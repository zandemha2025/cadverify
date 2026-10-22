"""A notification's ``audience_role`` decides who in the org sees it (R2, minor).

"Governed change awaiting review" is emitted for admins (``audience_role``
``"admin"``): only an admin can approve it. The field was stored and returned
but never applied, so every member and viewer got it in their inbox. It is a
filter now, on the list and on read, dismiss, restore and read-all.

Skipped unless DATABASE_URL points at Postgres migrated to head.
"""
from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("RATE_LIMIT_DISABLED", "1")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL", "").startswith("postgresql"), reason="needs Postgres"
    ),
]


def _app():
    from fastapi import FastAPI

    from src.api.notifications import router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/v1/notifications")
    return app


def _act_as(app, uid: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=uid, api_key_id=0, key_prefix="session", role="analyst"
    )


async def test_an_admin_notification_reaches_admins_only():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng
    from src.services import notification_service as svc

    tag = uuid.uuid4().hex[:8]
    org = str(ULID())
    async with eng.get_session_factory()() as s:
        await s.execute(text("INSERT INTO organizations (id, name, slug) VALUES (:i, :n, :s)"),
                        {"i": org, "n": f"Inbox {tag}", "s": f"inbox-{tag}"})
        uids = {}
        for label, role in (("admin", "admin"), ("member", "member"), ("viewer", "viewer")):
            uids[label] = int((await s.execute(text(
                "INSERT INTO users (email, email_lower, role, auth_provider, current_org_id) "
                "VALUES (:e, :e, 'analyst', 'password', :o) RETURNING id"),
                {"e": f"inbox-{tag}-{label}@example.com", "o": org})).scalar_one())
            await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role) VALUES (:i, :o, :u, :r)"),
                            {"i": str(ULID()), "o": org, "u": uids[label], "r": role})
        for_admins = await svc.emit_notification(
            s, org_id=org, kind="governance.change_requested", title="Governed change awaiting review",
            source_type="change_request", source_id="1", audience_role="admin")
        for_members = await svc.emit_notification(
            s, org_id=org, kind="catalog.run_finished", title="Run finished",
            source_type="batch", source_id="b1", audience_role="member")
        for_all = await svc.emit_notification(
            s, org_id=org, kind="decision.created", title="Verification recorded",
            source_type="cost_decision", source_id="d1")
        odd = await svc.emit_notification(
            s, org_id=org, kind="x.y", title="Unknown audience", source_type="x", source_id="x",
            audience_role="owner")
        await s.commit()
        ids = {"admin": for_admins.ulid, "member": for_members.ulid, "all": for_all.ulid, "odd": odd.ulid}

    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            seen = {}
            for label in ("admin", "member", "viewer"):
                _act_as(app, uids[label])
                r = await ac.get("/api/v1/notifications")
                assert r.status_code == 200, r.text
                seen[label] = {n["id"] for n in r.json()["notifications"]}
            assert seen["admin"] == {ids["admin"], ids["member"], ids["all"]}
            assert seen["member"] == {ids["member"], ids["all"]}
            assert seen["viewer"] == {ids["all"]}

            # The member can't read, dismiss or restore the admins' one; read-all skips it.
            _act_as(app, uids["member"])
            for action in ("read", "dismiss", "restore"):
                r = await ac.post(f"/api/v1/notifications/{ids['admin']}/{action}")
                assert r.status_code == 404, (action, r.text)
            r = await ac.post("/api/v1/notifications/read-all")
            assert r.status_code == 200, r.text
            _act_as(app, uids["admin"])
            assert (await ac.post(f"/api/v1/notifications/{ids['admin']}/read")).status_code == 200
        async with eng.get_session_factory()() as s:
            marked = (await s.execute(text(
                "SELECT n.ulid FROM notification_reads r JOIN notifications n ON n.id = r.notification_id "
                "WHERE r.user_id = :u"), {"u": uids["member"]})).scalars().all()
            assert set(marked) == {ids["member"], ids["all"]}
    finally:
        async with eng.get_session_factory()() as s:
            await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
            await s.execute(text("DELETE FROM users WHERE id = ANY(:u)"), {"u": list(uids.values())})
            await s.commit()
        await eng.dispose_engine()
