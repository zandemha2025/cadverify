"""Staff can grant a pilot plan with a script, audited, never by hand in the database.

``backend/scripts/set_plan.py --email … --plan trial|pro|pilot --reason …`` sets
``users.plan``, prints the account before and after, and writes a
``user.plan_changed`` audit row whose actor is "staff script", in the same
transaction. It is a command an operator runs with database access, not a web
route. Runs the real script as a subprocess against live Postgres.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from ulid import ULID

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)")
BACKEND = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "scripts.set_plan", *args], cwd=BACKEND, env=os.environ.copy(),
                          capture_output=True, text=True, timeout=120)


@pytest_asyncio.fixture
async def account():
    import src.db.engine as eng

    tag = uuid.uuid4().hex[:10]
    email = f"plan-{tag}@northfieldpumps.com"
    org = str(ULID())
    async with eng.get_session_factory()() as s:
        uid = int((await s.execute(text(
            "INSERT INTO users (email, email_lower, role, auth_provider) VALUES (:e, :e, 'analyst', 'password') RETURNING id"),
            {"e": email})).first()[0])
        await s.execute(text("INSERT INTO organizations (id, name, slug, is_personal, created_at) "
                             "VALUES (:o, 'Northfield Pumps', :sl, true, now())"), {"o": org, "sl": f"plan-{tag}"})
        await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                             "VALUES (:id, :o, :u, 'admin', now())"), {"id": str(ULID()), "o": org, "u": uid})
        await s.execute(text("UPDATE users SET current_org_id = :o WHERE id = :u"), {"o": org, "u": uid})
        await s.commit()
    yield uid, email, org
    async with eng.get_session_factory()() as s:
        await s.execute(text("DELETE FROM audit_log WHERE resource_type = 'user' AND resource_id = :u"), {"u": str(uid)})
        await s.execute(text("DELETE FROM memberships WHERE user_id = :u"), {"u": uid})
        await s.execute(text("UPDATE users SET current_org_id = NULL WHERE id = :u"), {"u": uid})
        await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
        await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        await s.commit()
    await eng.dispose_engine()


async def _plan_and_rows(uid):
    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        plan = (await s.execute(text("SELECT plan FROM users WHERE id = :u"), {"u": uid})).scalar_one()
        rows = (await s.execute(text(
            "SELECT user_id, user_email, org_id, detail_json FROM audit_log "
            "WHERE action = 'user.plan_changed' AND resource_type = 'user' AND resource_id = :u ORDER BY id"),
            {"u": str(uid)})).all()
    return plan, rows


@_requires_pg
@pytest.mark.asyncio
async def test_staff_grant_a_pilot_plan_with_a_reason_and_it_is_audited(account):
    uid, email, org = account
    reason = "Pilot agreed with Dana Ortiz, 2026-10-22"
    r = _run("--email", email.upper(), "--plan", "pilot", "--reason", reason)
    assert r.returncode == 0, r.stderr
    assert f"Before: account {uid} {email} · plan trial" in r.stdout
    assert f"After:  account {uid} {email} · plan pilot" in r.stdout
    plan, rows = await _plan_and_rows(uid)
    assert plan == "pilot"
    assert len(rows) == 1
    user_id, actor, org_id, detail = rows[0]
    assert (user_id, actor, org_id) == (None, "staff script", org)
    assert detail == {"from": "trial", "to": "pilot", "reason": reason, "by": "staff script",
                      "user_id": uid, "email": email}

    # The same plan again changes nothing and writes no second row.
    r = _run("--email", email, "--plan", "pilot", "--reason", "again")
    assert r.returncode == 0 and "Already on pilot; nothing changed." in r.stdout
    assert len((await _plan_and_rows(uid))[1]) == 1


@_requires_pg
@pytest.mark.asyncio
async def test_pro_without_a_subscription_says_what_it_gets_and_trial_takes_it_back(account):
    uid, email, _org = account
    r = _run("--email", email, "--plan", "pro", "--reason", "Comped Pro for the October webinar")
    assert r.returncode == 0, r.stderr
    assert "No active Pro subscription: until Stripe records one, this account has the free allowance." in r.stdout
    r = _run("--email", email, "--plan", "trial", "--reason", "Webinar over")
    assert r.returncode == 0, r.stderr
    plan, rows = await _plan_and_rows(uid)
    assert plan == "trial" and [row[3]["to"] for row in rows] == ["pro", "trial"]


@_requires_pg
def test_refusals_change_nothing():
    r = _run("--email", f"nobody-{uuid.uuid4().hex[:8]}@northfieldpumps.com", "--plan", "pilot", "--reason", "x")
    assert r.returncode == 2 and "No account with that email." in r.stderr
    r = _run("--email", "dana@northfieldpumps.com", "--plan", "pilot")
    assert r.returncode == 2 and "--reason" in r.stderr
    r = _run("--email", "dana@northfieldpumps.com", "--plan", "enterprise", "--reason", "x")
    assert r.returncode == 2 and "invalid choice" in r.stderr
    r = _run("--email", "dana@northfieldpumps.com", "--plan", "pilot", "--reason", "   ")
    assert r.returncode == 2 and "A reason is required" in r.stderr


def test_it_is_not_a_web_route():
    """Nothing the API serves imports the script, and no route sets a plan."""
    src = BACKEND / "src"
    assert not [p for p in src.rglob("*.py") if "set_plan" in p.read_text(encoding="utf-8", errors="ignore")]
