"""Two-step sign-in (authenticator-app codes), unit and end to end.

Unit (no database): RFC 6238 vectors, the drift window and replay rule, the
QR encoder against reference matrices, challenge tokens, recovery-code shape.

End to end against Postgres migrated to head (skipped otherwise), through the
real /auth routes: enrolment with a sealed secret, sign-in with a code, a wrong
code, a replayed code in the same step, a recovery code used once, the lock
after repeated wrong codes, turning it off, sign out other sessions, the
organization rule (with members signed out and set up at the next sign-in),
the email-link and Google paths asking for the code, and organization single
sign-on (OIDC) exempt. Accounts without two-step keep signing in exactly as
before (also covered by tests/test_auth_password.py's full flow).
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import text

from src.auth import qr, totp
from src.auth import two_step as ts

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
requires_pg = pytest.mark.skipif(not _PG, reason="requires Postgres migrated to head")

RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


# ── TOTP ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "t,code",
    [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"), (2000000000, "279037")],
)
def test_rfc6238_sha1_vectors(t, code):
    assert totp.code_at_step(RFC_SECRET, totp.step_at(t)) == code


def test_codes_match_one_step_either_side_and_never_twice():
    now = 1_700_000_000.0
    step = totp.step_at(now)
    for delta in (-1, 0, 1):
        assert totp.matching_step(RFC_SECRET, totp.code_at_step(RFC_SECRET, step + delta), now=now) == step + delta
    for delta in (-2, 2):
        assert totp.matching_step(RFC_SECRET, totp.code_at_step(RFC_SECRET, step + delta), now=now) is None
    current = totp.code_at_step(RFC_SECRET, step)
    assert totp.matching_step(RFC_SECRET, current, last_used_step=step, now=now) is None
    assert totp.matching_step(RFC_SECRET, current, last_used_step=step - 1, now=now) == step


def test_code_input_is_forgiving_about_spaces_only():
    assert totp.clean_code(" 123 456 ") == "123456"
    assert totp.clean_code("123-456") == "123456"
    for bad in ("12345", "1234567", "12a456", None, 123456):
        assert totp.clean_code(bad) is None


def test_secret_and_link_shape():
    secret = totp.new_secret()
    assert len(secret) == 32 and set(secret) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    assert totp.manual_key(secret).replace(" ", "") == secret
    uri = totp.otpauth_uri(secret, "sam@kestrel.example")
    assert uri == f"otpauth://totp/ScaleCAD:sam@kestrel.example?secret={secret}&issuer=ScaleCAD"
    long = totp.otpauth_uri(secret, "x" * 300 + "@example.com", max_len=qr.MAX_BYTES)
    assert len(long) <= qr.MAX_BYTES and long.startswith("otpauth://totp/ScaleCAD?secret=")


# ── QR ────────────────────────────────────────────────────────────────────────
# Reference matrices from an independent encoder (segno 1.6.6, level M, byte
# mode, fixed mask), at full capacity so no pad-codeword choice can differ.
_V1_TEXT = "ScaleCAD 2-ste"
_V1_MASK2 = [
    "111111100110001111111",
    "100000100011101000001",
    "101110101100101011101",
    "101110101101001011101",
    "101110101110101011101",
    "100000101010101000001",
    "111111101010101111111",
    "000000001001100000000",
    "101111100101101111100",
    "010011011110010100101",
    "100001100011100001010",
    "000100001100100001111",
    "110011111011101100000",
    "000000001111000100110",
    "111111100001100001110",
    "100000101011000011101",
    "101110101110111100011",
    "101110101101000101000",
    "101110101011101000100",
    "100000100001100001100",
    "111111101011001000010",
]
_V7_TEXT = 'otpauth://totp/ScaleCAD:sam.okafor@kestrelaero-parts.com?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=ScaleCAD&x=0123456'
_V7_MASK5 = [
    "111111100101100111001000001101111100101111111",
    "100000101101100100010111100010000101001000001",
    "101110101110100010110000010010101101001011101",
    "101110101111001101100000001110011101101011101",
    "101110100101100011111111100111111011101011101",
    "100000100110000011101000101000000000001000001",
    "111111101010101010101010101010101010101111111",
    "000000001000010111101000110010000111100000000",
    "100000101100110100111111110001010010111001110",
    "101000011101001011010011011010101011111111110",
    "111101110101011111011010100011000111011000010",
    "011111010110111111000100110000111000101011111",
    "101101101100101000111111111010101100000011000",
    "101010011111011000010001010101110101110011110",
    "000100101000000000100000111100010110101000110",
    "000110011011101101011011101011010111101110110",
    "010001101001001011110010001001010100011001000",
    "000001011111010011010000010001100100110010111",
    "101111101101010001110000101110101011001111101",
    "101100010110101000110101010111001100001011110",
    "101111111111100011111111101001010001111111110",
    "101110001001010000111000111110110111100011100",
    "011010101000110111101010111100000011101010110",
    "100010001110111110001000100010110110100011110",
    "111011111101100011111111100010001000111110011",
    "011110000110011000110010110101100101110101001",
    "011001100001010011101011000101101010010101010",
    "101010011010001110000110101011000111110011100",
    "101001110110100001011100111000110000010011001",
    "110101011111011110110111100111110100100101011",
    "100000101100111101010010010111011100001010111",
    "000110001110000110110000100100111001001001111",
    "110101101000110111000001111001010100010110101",
    "010001001101100001100111011011110111111010000",
    "000010111000001000000101110110011100010100110",
    "011110011000110011000011101011010001111001101",
    "100110100101011100111111111010101101111110111",
    "000000001111010011111000100001110000100010101",
    "111111100100100111111010111101011010101010110",
    "100000100110100111011000101000101110100011110",
    "101110100001111100101111110000110101111110001",
    "101110100000100000011001010111110101010000111",
    "101110100011000101000000111110101100100011001",
    "100000100000000010101000011001101111010011100",
    "111111101010001010110001101001110100110110110",
]


def test_qr_matches_reference_version_1():
    assert qr.encode(_V1_TEXT, version=1, mask=2) == _V1_MASK2


def test_qr_matches_reference_version_7_with_version_information():
    assert len(_V7_TEXT) == qr.capacity(7)
    assert qr.encode(_V7_TEXT, version=7, mask=5) == _V7_MASK5


def test_qr_structure_for_a_real_enrolment_link():
    uri = totp.otpauth_uri(totp.new_secret(), "sam.okafor.8luxx@kestrelaero-parts.com", max_len=qr.MAX_BYTES)
    rows = qr.encode(uri)
    size = len(rows)
    assert all(len(r) == size for r in rows) and (size - 17) % 4 == 0
    version = (size - 17) // 4
    assert 1 <= version <= qr.MAX_VERSION and qr.capacity(version) >= len(uri)
    finder = ["1111111", "1000001", "1011101", "1011101", "1011101", "1000001", "1111111"]
    for y in range(7):
        assert rows[y][:7] == finder[y]
        assert rows[y][size - 7:] == finder[y]
        assert rows[size - 7 + y][:7] == finder[y]
    assert rows[size - 8][8] == "1"  # the dark module
    assert "".join(rows[6][8:size - 8]) == "".join("1" if i % 2 == 0 else "0" for i in range(8, size - 8))


def test_qr_refuses_text_longer_than_version_10():
    with pytest.raises(ValueError):
        qr.encode("x" * (qr.MAX_BYTES + 1))


# ── challenge tokens and recovery codes ───────────────────────────────────────
def test_challenge_round_trip_and_tamper():
    token = ts.make_challenge(7, 3, "verify", "password")
    ch = ts.read_challenge(token)
    assert ch is not None and (ch.user_id, ch.session_version, ch.purpose, ch.method) == (7, 3, "verify", "password")
    tag, body, sig = token.split(".")
    assert ts.read_challenge(f"{tag}.{body}.{sig[:-2]}AA") is None
    assert ts.read_challenge(f"{tag}.{body[:-2]}xx.{sig}") is None


def test_challenge_expires_and_is_not_a_session(monkeypatch):
    from src.auth.dashboard_session import sign, unsign_payload

    token = ts.make_challenge(7, 0, "setup", "email_link")
    assert unsign_payload(token) is None
    assert ts.read_challenge(sign(7)) is None
    real = time.time
    monkeypatch.setattr(ts.time, "time", lambda: real() + ts.CHALLENGE_TTL + 5)
    assert ts.read_challenge(token) is None


def test_recovery_codes_shape():
    codes = ts.new_recovery_codes()
    assert len(codes) == 10 == len(set(codes))
    for c in codes:
        assert len(c) == 11 and c[5] == "-"
        assert ts.clean_recovery_code(c.upper()) == c.replace("-", "")
    assert ts.clean_recovery_code("abcde-fghi0") is None  # 0 isn't in the alphabet
    assert ts.recovery_hash(1, "abcdefghjk") != ts.recovery_hash(2, "abcdefghjk")


def test_wait_words_are_exact():
    assert ts.wait_words(30) == "30 seconds"
    assert ts.wait_words(9 * 60) == "9 minutes"
    assert ts.wait_words(8 * 60 + 1) == "9 minutes"
    assert ts.wait_words(3600) == "1 hour"
    assert ts.wait_words(5400) == "1 hour 30 minutes"


# ── end to end (Postgres) ─────────────────────────────────────────────────────
def _app() -> FastAPI:
    from src.auth.magic_link import router as magic_router
    from src.auth.password import router as password_router
    from src.auth.require_api_key import AuthedUser, require_api_key

    app = FastAPI()
    app.include_router(password_router, prefix="/auth")
    app.include_router(magic_router, prefix="/auth")

    @app.get("/protected")
    async def protected(user: AuthedUser = Depends(require_api_key)):  # noqa: ANN001
        return {"user_id": user.user_id}

    return app


@pytest.fixture
def clock(monkeypatch):
    """A fixed TOTP clock the test moves step by step."""
    state = {"step": totp.step_at() + 1000}
    monkeypatch.setattr(totp, "step_at", lambda now=None: state["step"])
    return state


@pytest.fixture
def env(monkeypatch):
    from src.auth.rate_limit import limiter

    monkeypatch.delenv("RELEASE", raising=False)
    monkeypatch.delenv("PRODUCTION_AUTH_PROXY_REQUIRED", raising=False)
    monkeypatch.setenv("SIGNUP_RATE_LIMIT_DISABLED", "1")
    monkeypatch.setattr(limiter, "enabled", False)


class World:
    def __init__(self) -> None:
        self.tag = uuid.uuid4().hex[:10]
        self.emails: list[str] = []
        self.orgs: list[str] = []

    def email(self, who: str) -> str:
        e = f"ts-{self.tag}-{who}@example.com"
        self.emails.append(e)
        return e


async def _cleanup(w: World) -> None:
    import src.db.engine as eng

    try:
        async with eng.get_session_factory()() as s:
            ids = (await s.execute(text("SELECT id FROM users WHERE email_lower = ANY(:e)"), {"e": w.emails})).scalars().all()
            orgs = (await s.execute(text("SELECT org_id FROM memberships WHERE user_id = ANY(:u)"), {"u": list(ids)})).scalars().all()
            await s.execute(text("DELETE FROM audit_log WHERE user_id = ANY(:u)"), {"u": list(ids)})
            await s.execute(text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": list({*orgs, *w.orgs})})
            await s.execute(text("DELETE FROM users WHERE id = ANY(:u)"), {"u": list(ids)})
            await s.commit()
    finally:
        await eng.dispose_engine()


PASSWORD = "Passw0rd-two-step-1"


async def _signup(ac: httpx.AsyncClient, email: str) -> tuple[int, str]:
    r = await ac.post("/auth/signup", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["user"]["id"], r.json()["session"]


def _cookie(session: str) -> dict:
    return {"Cookie": f"dash_session={session}"}


async def _enrol(ac, session: str, clock) -> tuple[str, list[str], str]:
    r = await ac.post("/auth/two-step/enrol", headers=_cookie(session))
    assert r.status_code == 200, r.text
    data = r.json()
    secret = data["manual_key"].replace(" ", "")
    assert data["otpauth_uri"].startswith("otpauth://totp/ScaleCAD:") and f"secret={secret}" in data["otpauth_uri"]
    assert len(data["qr"]) >= 21
    r = await ac.post("/auth/two-step/enrol/confirm", headers=_cookie(session), json={"code": totp.code_at_step(secret, clock["step"])})
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"], r.json()["session"]


async def _actions(user_id: int) -> list[str]:
    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        return list((await s.execute(text("SELECT action FROM audit_log WHERE user_id = :u ORDER BY id"), {"u": user_id})).scalars().all())


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://t")


@requires_pg
@pytest.mark.asyncio
async def test_enrol_sign_in_wrong_replayed_and_recovery(env, clock):
    import src.db.engine as eng

    w = World()
    try:
        async with _client() as ac:
            email = w.email("pat")
            uid, first = await _signup(ac, email)

            # Before two-step: password sign-in issues a session, as always.
            r = await ac.post("/auth/login", json={"email": email, "password": PASSWORD})
            assert r.status_code == 200 and "two_step" not in r.json() and r.json()["session"]
            other_browser = r.json()["session"]

            # A wrong first code doesn't turn it on.
            r = await ac.post("/auth/two-step/enrol", headers=_cookie(first))
            pending = r.json()["manual_key"].replace(" ", "")
            async with eng.get_session_factory()() as s:
                row = (await s.execute(text("SELECT pending_secret_sealed, secret_sealed FROM user_two_step WHERE user_id = :u"), {"u": uid})).first()
            assert row[0].startswith("fernet:v1:") and pending not in row[0] and row[1] is None
            assert ts.unseal(row[0]) == pending
            wrong = totp.code_at_step(pending, clock["step"] + 5)
            r = await ac.post("/auth/two-step/enrol/confirm", headers=_cookie(first), json={"code": wrong})
            assert r.status_code == 400 and r.json()["detail"]["code"] == "two_step_code_wrong"

            secret, codes, session = await _enrol(ac, first, clock)
            assert len(codes) == 10 and len(set(codes)) == 10
            async with eng.get_session_factory()() as s:
                row = (await s.execute(text("SELECT secret_sealed, enabled_at FROM user_two_step WHERE user_id = :u"), {"u": uid})).first()
                hashes = (await s.execute(text("SELECT code_hash FROM user_two_step_recovery_codes WHERE user_id = :u"), {"u": uid})).scalars().all()
            assert row[0].startswith("fernet:v1:") and secret not in row[0] and row[1] is not None
            assert len(hashes) == 10 and not set(hashes) & {c.replace("-", "") for c in codes} and not set(hashes) & set(codes)
            # Turning it on signs out the other browsers; this one keeps a fresh session.
            assert (await ac.get("/protected", headers=_cookie(other_browser))).status_code == 401
            assert (await ac.get("/protected", headers=_cookie(session))).status_code == 200
            status = (await ac.get("/auth/two-step", headers=_cookie(session))).json()
            assert status["enabled"] is True and status["recovery_codes_left"] == 10

            # Password sign-in now returns a challenge, never a session.
            r = await ac.post("/auth/login", json={"email": email, "password": PASSWORD})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["two_step"] == "verify" and "session" not in body
            challenge = body["challenge"]
            r = await ac.post("/auth/two-step/challenge/state", json={"challenge": challenge})
            assert r.json()["purpose"] == "verify" and r.json()["method"] == "password"

            # A wrong code.
            r = await ac.post("/auth/two-step/challenge/verify", json={"challenge": challenge, "code": totp.code_at_step(secret, clock["step"] + 7)})
            assert r.status_code == 400 and r.json()["detail"]["code"] == "two_step_code_wrong"
            assert "session" not in r.text
            # The enrolment code again, in the same 30-second step: refused as used.
            r = await ac.post("/auth/two-step/challenge/verify", json={"challenge": challenge, "code": totp.code_at_step(secret, clock["step"])})
            assert r.status_code == 400 and r.json()["detail"]["code"] == "two_step_code_used"
            # The next step's code signs in.
            clock["step"] += 1
            code = totp.code_at_step(secret, clock["step"])
            r = await ac.post("/auth/two-step/challenge/verify", json={"challenge": challenge, "code": code})
            assert r.status_code == 200, r.text
            assert r.json()["used"] == "code" and (await ac.get("/protected", headers=_cookie(r.json()["session"]))).status_code == 200
            # Replaying that code in the same step fails, even with a fresh challenge.
            fresh = (await ac.post("/auth/login", json={"email": email, "password": PASSWORD})).json()["challenge"]
            r = await ac.post("/auth/two-step/challenge/verify", json={"challenge": fresh, "code": code})
            assert r.status_code == 400 and r.json()["detail"]["code"] == "two_step_code_used"

            # A recovery code works once.
            r = await ac.post("/auth/two-step/challenge/verify", json={"challenge": fresh, "recovery_code": codes[0].upper()})
            assert r.status_code == 200, r.text
            assert r.json()["used"] == "recovery" and r.json()["recovery_codes_left"] == 9
            r = await ac.post("/auth/two-step/challenge/verify", json={"challenge": fresh, "recovery_code": codes[0]})
            assert r.status_code == 400 and r.json()["detail"]["code"] == "two_step_recovery_wrong"

            actions = await _actions(uid)
            assert "auth.two_step_enabled" in actions and "auth.two_step_recovery_used" in actions
            # One plain sign-in before two-step, then the two completed with a code
            # or recovery code. The three challenges themselves log no sign-in.
            assert actions.count("auth.login") == 3
    finally:
        await _cleanup(w)


@requires_pg
@pytest.mark.asyncio
async def test_wrong_codes_lock_with_the_real_wait_then_turning_off_needs_a_code(env, clock):
    w = World()
    try:
        async with _client() as ac:
            email = w.email("lock")
            uid, first = await _signup(ac, email)
            secret, codes, session = await _enrol(ac, first, clock)
            challenge = (await ac.post("/auth/login", json={"email": email, "password": PASSWORD})).json()["challenge"]
            for i in range(ts.LOCK_AFTER - 1):
                r = await ac.post("/auth/two-step/challenge/verify", json={"challenge": challenge, "code": "000000" if totp.code_at_step(secret, clock["step"] + 1) != "000000" else "111111"})
                assert r.status_code == 400, r.text
            r = await ac.post("/auth/two-step/challenge/verify", json={"challenge": challenge, "code": totp.code_at_step(secret, clock["step"] + 9)})
            assert r.status_code == 429
            assert r.json()["detail"]["code"] == "two_step_locked"
            assert "Try again in 15 minutes." in r.json()["detail"]["message"]
            # Even the right code is refused while locked; nothing is compared.
            clock["step"] += 1
            r = await ac.post("/auth/two-step/challenge/verify", json={"challenge": challenge, "code": totp.code_at_step(secret, clock["step"])})
            assert r.status_code == 429 and "session" not in r.text
            assert "auth.two_step_locked" in await _actions(uid)

            import src.db.engine as eng

            async with eng.get_session_factory()() as s:
                await s.execute(text("UPDATE user_two_step SET locked_until = now() - interval '1 second' WHERE user_id = :u"), {"u": uid})
                await s.commit()
            # Turning it off: no code, refused; a recovery code works.
            r = await ac.post("/auth/two-step/disable", headers=_cookie(session), json={})
            assert r.status_code == 400 and r.json()["detail"]["code"] == "two_step_code_format"
            r = await ac.post("/auth/two-step/disable", headers=_cookie(session), json={"recovery_code": codes[3]})
            assert r.status_code == 200, r.text and r.json()["enabled"] is False
            async with eng.get_session_factory()() as s:
                left = (await s.execute(text("SELECT count(*) FROM user_two_step_recovery_codes WHERE user_id = :u"), {"u": uid})).scalar_one()
            assert left == 0
            assert "auth.two_step_disabled" in await _actions(uid)
            # And sign-in is a plain password sign-in again.
            r = await ac.post("/auth/login", json={"email": email, "password": PASSWORD})
            assert "two_step" not in r.json() and r.json()["session"]
    finally:
        await _cleanup(w)


@requires_pg
@pytest.mark.asyncio
async def test_sign_out_other_sessions_keeps_this_one(env):
    w = World()
    try:
        async with _client() as ac:
            email = w.email("out")
            _uid, a = await _signup(ac, email)
            b = (await ac.post("/auth/login", json={"email": email, "password": PASSWORD})).json()["session"]
            r = await ac.post("/auth/sessions/sign-out-others", headers=_cookie(a))
            assert r.status_code == 200, r.text
            assert (await ac.get("/protected", headers=_cookie(b))).status_code == 401
            assert (await ac.get("/protected", headers=_cookie(a))).status_code == 401
            assert (await ac.get("/protected", headers=_cookie(r.json()["session"]))).status_code == 200
    finally:
        await _cleanup(w)


@requires_pg
@pytest.mark.asyncio
async def test_org_rule_signs_out_members_and_sets_them_up_at_next_sign_in(env, clock):
    import src.db.engine as eng

    w = World()
    try:
        async with _client() as ac:
            admin_email, member_email = w.email("admin"), w.email("member")
            admin, admin_s = await _signup(ac, admin_email)
            member, member_s = await _signup(ac, member_email)
            org = f"01TS{w.tag.upper()}"[:26]
            w.orgs.append(org)
            async with eng.get_session_factory()() as s:
                await s.execute(text("INSERT INTO organizations (id, name, slug) VALUES (:o, :n, :sl)"), {"o": org, "n": f"Kestrel {w.tag}", "sl": f"kestrel-{w.tag}"})
                for uid, role in ((admin, "admin"), (member, "member")):
                    await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role) VALUES (:i, :o, :u, :r)"), {"i": uuid.uuid4().hex, "o": org, "u": uid, "r": role})
                    await s.execute(text("UPDATE users SET current_org_id = :o WHERE id = :u"), {"o": org, "u": uid})
                await s.commit()

            # Members can read the rule but not change it.
            r = await ac.get("/auth/two-step/org", headers=_cookie(member_s))
            assert r.status_code == 200 and r.json()["required"] is False and "members" not in r.json()
            assert (await ac.put("/auth/two-step/org", headers=_cookie(member_s), json={"required": True})).status_code == 403
            # The admin needs two-step first.
            r = await ac.put("/auth/two-step/org", headers=_cookie(admin_s), json={"required": True})
            assert r.status_code == 409 and r.json()["detail"]["code"] == "two_step_admin_first"
            _secret, _codes, admin_s = await _enrol(ac, admin_s, clock)
            r = await ac.put("/auth/two-step/org", headers=_cookie(admin_s), json={"required": True})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["required"] is True and body["members_signed_out"] == 1
            people = {m["email"]: m["two_step_on"] for m in body["members"]}
            assert people == {admin_email: True, member_email: False}
            assert "org.two_step_policy_changed" in await _actions(admin)

            # The member's existing session ended; the next sign-in sets it up first.
            assert (await ac.get("/protected", headers=_cookie(member_s))).status_code == 401
            r = await ac.post("/auth/login", json={"email": member_email, "password": PASSWORD})
            assert r.json()["two_step"] == "setup" and "session" not in r.json()
            challenge = r.json()["challenge"]
            state = (await ac.post("/auth/two-step/challenge/state", json={"challenge": challenge})).json()
            assert state["purpose"] == "setup" and state["required_by"] == [f"Kestrel {w.tag}"]
            # A setup challenge can't be spent as a verify one.
            r = await ac.post("/auth/two-step/challenge/verify", json={"challenge": challenge, "code": "123456"})
            assert r.status_code == 409
            setup = (await ac.post("/auth/two-step/challenge/setup", json={"challenge": challenge})).json()
            secret = setup["manual_key"].replace(" ", "")
            r = await ac.post("/auth/two-step/challenge/setup/confirm", json={"challenge": challenge, "code": totp.code_at_step(secret, clock["step"])})
            assert r.status_code == 200, r.text
            assert len(r.json()["recovery_codes"]) == 10
            member_s = r.json()["session"]
            assert (await ac.get("/protected", headers=_cookie(member_s))).status_code == 200
            # The member can't turn it off while the org requires it.
            clock["step"] += 1
            r = await ac.post("/auth/two-step/disable", headers=_cookie(member_s), json={"code": totp.code_at_step(secret, clock["step"])})
            assert r.status_code == 409 and r.json()["detail"]["code"] == "two_step_required_by_org"
            # Next time, a code.
            r = await ac.post("/auth/login", json={"email": member_email, "password": PASSWORD})
            assert r.json()["two_step"] == "verify"
            # Step-up leaves a session alone once two-step is on.
            r = await ac.post("/auth/two-step/step-up", headers=_cookie(member_s))
            assert r.json() == {"two_step": None}

            # Someone who joins the org later (sign-up from an invite) is stepped up
            # before reaching its data: their fresh session ends, a setup challenge comes back.
            late_email = w.email("late")
            late, late_s = await _signup(ac, late_email)
            assert (await ac.post("/auth/two-step/step-up", headers=_cookie(late_s))).json() == {"two_step": None}
            async with eng.get_session_factory()() as s:
                await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role) VALUES (:i, :o, :u, 'viewer')"), {"i": uuid.uuid4().hex, "o": org, "u": late})
                await s.commit()
            r = await ac.post("/auth/two-step/step-up", headers=_cookie(late_s))
            assert r.status_code == 200 and r.json()["two_step"] == "setup"
            assert ts.read_challenge(r.json()["challenge"]).purpose == "setup"
            assert (await ac.get("/protected", headers=_cookie(late_s))).status_code == 401
    finally:
        await _cleanup(w)


@requires_pg
@pytest.mark.asyncio
async def test_email_link_and_google_ask_for_the_code(env, clock, monkeypatch):
    import src.auth.magic_link as m
    from fastapi.testclient import TestClient

    w = World()
    try:
        async with _client() as ac:
            email = w.email("link")
            uid, first = await _signup(ac, email)
            await _enrol(ac, first, clock)
        fake_redis = AsyncMock()
        fake_redis.ttl = AsyncMock(return_value=900)
        fake_redis.getdel = AsyncMock(return_value="1")
        fake_redis.eval = AsyncMock(return_value=1)
        monkeypatch.setattr(m, "_r", lambda: fake_redis)
        provision = AsyncMock()
        monkeypatch.setattr(m, "provision_authenticated_login", provision)
        token = m._mint(email)
        async with _client() as ac:
            r = await ac.post("/auth/magic/exchange", json={"token": token})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["two_step"] == "verify" and body["redirect"] == "/login/two-step"
            assert "session" not in body and body.get("mint_once") is None
            provision.assert_not_awaited()  # no key minted, nothing provisioned before the code
            assert ts.read_challenge(body["challenge"]).method == "email_link"
            # The legacy GET link doesn't spend itself or set a cookie: it goes to the code flow.
            fake_redis.getdel.reset_mock()
            r = await ac.get("/auth/magic/verify", params={"token": token}, follow_redirects=False)
            assert r.status_code == 303 and "/magic/verify#token=" in r.headers["location"]
            assert "dash_session" not in r.headers.get("set-cookie", "")
            fake_redis.getdel.assert_not_awaited()

        from src.auth.oauth import router as oauth_router

        gapp = FastAPI()
        gapp.include_router(oauth_router, prefix="/auth")
        with patch("src.auth.oauth.oauth") as mock_oauth, patch("src.auth.oauth.create_api_key", new_callable=AsyncMock) as mint:
            mock_oauth.google.authorize_access_token = AsyncMock(
                return_value={"userinfo": {"email": email, "sub": f"g-{w.tag}", "email_verified": True}}
            )
            resp = TestClient(gapp, follow_redirects=False).get("/auth/google/callback")
        assert resp.status_code == 303 and resp.headers["location"].endswith("/login/two-step")
        cookies = resp.headers.get("set-cookie", "")
        assert "cv_two_step=" in cookies and "dash_session" not in cookies and "HttpOnly" in cookies
        mint.assert_not_awaited()
    finally:
        await _cleanup(w)


@requires_pg
def test_organization_sso_is_exempt(oidc_env, monkeypatch):
    """OIDC through the org's identity provider issues a session with no code."""
    import asyncio

    import src.auth.oidc as oidc
    import src.db.engine as eng
    from fastapi.testclient import TestClient
    from tests.test_oidc import OKTA_CLAIMS, MockIdP, _login_result, _start_login, _wire_idp
    import respx

    from src.auth.dashboard_session import unsign_payload

    tag = uuid.uuid4().hex[:10]
    email = f"ts-{tag}-sso@example.com"

    async def seed() -> int:
        async with eng.get_session_factory()() as s:
            uid = (await s.execute(text("INSERT INTO users (email, email_lower, auth_provider) VALUES (:e, :e, 'oidc') RETURNING id"), {"e": email})).scalar_one()
            await s.execute(text("INSERT INTO user_two_step (user_id, secret_sealed, enabled_at) VALUES (:u, :s, now())"), {"u": uid, "s": ts.seal(totp.new_secret())})
            await s.commit()
        await eng.dispose_engine()
        return int(uid)

    async def drop() -> None:
        async with eng.get_session_factory()() as s:
            await s.execute(text("DELETE FROM users WHERE email_lower = :e"), {"e": email})
            await s.commit()
        await eng.dispose_engine()

    uid = asyncio.run(seed())
    try:
        assert asyncio.run(ts.sign_in_requirement_for(uid)) == "verify"
        from starlette.middleware.sessions import SessionMiddleware

        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="oidc-test-secret")
        app.include_router(oidc.router, prefix="/auth")
        monkeypatch.setattr(oidc, "_oidc_provision_login", AsyncMock(return_value=_login_result(uid)))
        idp = MockIdP()
        holder: dict = {}
        with respx.mock(assert_all_called=False) as router:
            _wire_idp(router, idp, id_token_holder=holder)
            client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
            state, nonce = _start_login(client)
            holder["id_token"] = idp.mint(nonce=nonce, claims=OKTA_CLAIMS)
            resp = client.get(f"/auth/oidc/callback?code=authz-code-1&state={state}")
        assert resp.status_code == 303, resp.text
        cookie = resp.headers.get("set-cookie", "")
        assert "dash_session=" in cookie and "cv_two_step" not in cookie
        token = cookie.split("dash_session=", 1)[1].split(";", 1)[0].strip('"')
        assert unsign_payload(token).user_id == uid
    finally:
        asyncio.run(drop())


from tests.test_oidc import oidc_env  # noqa: E402,F401  (fixture)
