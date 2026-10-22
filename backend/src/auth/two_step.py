"""Two-step sign-in: an authenticator-app code after a password, email-link or
Google sign-in.

What it stores (migration 0062):

- ``user_two_step``: one row per account that has started or finished setting
  it up. The TOTP secret is sealed with the connector-credential Fernet key
  (CONNECTOR_SECRET_KEY, the same helper as sealed webhook secrets), never
  stored in plain text. ``last_used_step`` makes each 30-second code work once.
  ``failed_attempts`` and ``locked_until`` limit guessing per account.
- ``user_two_step_recovery_codes``: ten single-use codes per account, stored
  as HMAC-SHA256 under the server pepper (API_KEY_PEPPER), shown once.
- ``organizations.require_two_step``: an admin's rule that every member signs
  in with a code. Organization single sign-on (SAML/OIDC) is exempt: the
  identity provider owns that step.

Sign-in never issues a session to a person who still owes a code. The
password, email-link and Google paths call :func:`sign_in_requirement`; when it
answers "verify" or "setup" they hand back a short-lived signed challenge
instead of a session, and only :mod:`src.auth.two_step_routes` turns a
challenge plus a correct code into a session.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import qr, totp
from src.config.public_urls import error_doc_url

SEALED_PREFIX = "fernet:v1:"
RECOVERY_CODE_COUNT = 10
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i
RECOVERY_CODE_LEN = 10  # 10 of 31 symbols: about 49 bits each
LOCK_AFTER = 5  # wrong codes in a row before the account's code entry locks
LOCK_FIRST = timedelta(minutes=15)  # then 30, 60, ... up to LOCK_MAX
LOCK_MAX = timedelta(hours=24)
CHALLENGE_TTL = 10 * 60
ENROL_TTL = timedelta(minutes=30)

Purpose = Literal["verify", "setup"]
Method = Literal["password", "email_link", "google"]
_METHODS = ("password", "email_link", "google")


def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"code": code, "message": message, "doc_url": error_doc_url(code), **extra},
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def wait_words(seconds: float) -> str:
    """'Try again in 9 minutes' style wording for a real wait (never vague)."""
    secs = max(1, int(round(seconds)))
    if secs < 60:
        return f"{secs} second{'s' if secs != 1 else ''}"
    minutes = -(-secs // 60)
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours} hour{'s' if hours != 1 else ''} {rest} minute{'s' if rest != 1 else ''}"


# ── sealing ───────────────────────────────────────────────────────────────────
def seal(secret_b32: str) -> str:
    from src.services.connector_credentials_service import _fernet

    try:
        token = _fernet().encrypt(secret_b32.encode("ascii")).decode("ascii")
    except RuntimeError as exc:
        raise _err(
            503,
            "two_step_storage_unavailable",
            "Two-step sign-in storage is not configured on this deployment.",
        ) from exc
    return SEALED_PREFIX + token


def unseal(stored: str) -> str:
    from cryptography.fernet import InvalidToken

    from src.services.connector_credentials_service import _fernet

    if not stored or not stored.startswith(SEALED_PREFIX):
        raise _err(500, "two_step_secret_unreadable", "This account's two-step key can't be read.")
    try:
        return _fernet().decrypt(stored[len(SEALED_PREFIX):].encode("ascii")).decode("ascii")
    except (InvalidToken, RuntimeError, UnicodeError, ValueError) as exc:
        raise _err(
            500,
            "two_step_secret_unreadable",
            "This account's two-step key can't be read. Use a recovery code.",
        ) from exc


# ── recovery codes ────────────────────────────────────────────────────────────
def new_recovery_codes() -> list[str]:
    codes: set[str] = set()
    while len(codes) < RECOVERY_CODE_COUNT:
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_CODE_LEN))
        codes.add(f"{raw[:5]}-{raw[5:]}")
    return sorted(codes)


def clean_recovery_code(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    flat = "".join(ch for ch in raw.lower() if ch.isalnum())
    if len(flat) != RECOVERY_CODE_LEN or any(ch not in RECOVERY_ALPHABET for ch in flat):
        return None
    return flat


def recovery_hash(user_id: int, flat_code: str) -> str:
    from src.auth.hashing import _pepper

    msg = f"two-step-recovery:{int(user_id)}:{flat_code}".encode()
    return hmac.new(_pepper(), msg, hashlib.sha256).hexdigest()


# ── challenge tokens ──────────────────────────────────────────────────────────
def _challenge_key() -> bytes:
    raw = base64.b64decode(os.environ["DASHBOARD_SESSION_SECRET"])
    # Domain-separated from session signatures: a challenge is never a session.
    return hmac.new(raw, b"cadverify two-step challenge v1", hashlib.sha256).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


@dataclass(frozen=True)
class Challenge:
    user_id: int
    session_version: int
    purpose: Purpose
    method: Method
    issued_at: int


def make_challenge(user_id: int, session_version: int, purpose: Purpose, method: Method) -> str:
    body = json.dumps(
        {
            "u": int(user_id),
            "v": int(session_version),
            "p": purpose,
            "m": method,
            "t": int(time.time()),
            "n": secrets.token_urlsafe(9),
        },
        separators=(",", ":"),
    ).encode()
    sig = hmac.new(_challenge_key(), body, hashlib.sha256).digest()
    return f"ts1.{_b64(body)}.{_b64(sig)}"


def read_challenge(token: object) -> Challenge | None:
    if not isinstance(token, str) or len(token) > 1024:
        return None
    try:
        tag, body_s, sig_s = token.split(".")
        if tag != "ts1":
            return None
        body = _unb64(body_s)
        if not hmac.compare_digest(_unb64(sig_s), hmac.new(_challenge_key(), body, hashlib.sha256).digest()):
            return None
        data = json.loads(body)
        issued = int(data["t"])
        if not 0 <= time.time() - issued <= CHALLENGE_TTL:
            return None
        purpose, method = data["p"], data["m"]
        if purpose not in ("verify", "setup") or method not in _METHODS:
            return None
        return Challenge(int(data["u"]), int(data["v"]), purpose, method, issued)
    except Exception:
        return None


# ── state ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TwoStepRow:
    user_id: int
    secret_sealed: str | None
    enabled_at: datetime | None
    pending_secret_sealed: str | None
    pending_created_at: datetime | None
    last_used_step: int | None
    failed_attempts: int
    locked_until: datetime | None

    @property
    def enabled(self) -> bool:
        return self.enabled_at is not None and bool(self.secret_sealed)


async def load(session: AsyncSession, user_id: int, *, for_update: bool = False) -> TwoStepRow | None:
    row = (
        await session.execute(
            text(
                "SELECT user_id, secret_sealed, enabled_at, pending_secret_sealed, pending_created_at, "
                "last_used_step, failed_attempts, locked_until FROM user_two_step WHERE user_id = :u"
                + (" FOR UPDATE" if for_update else "")
            ),
            {"u": int(user_id)},
        )
    ).first()
    if row is None:
        return None
    return TwoStepRow(
        user_id=int(row[0]),
        secret_sealed=row[1],
        enabled_at=row[2],
        pending_secret_sealed=row[3],
        pending_created_at=row[4],
        last_used_step=None if row[5] is None else int(row[5]),
        failed_attempts=int(row[6] or 0),
        locked_until=row[7],
    )


async def requiring_orgs(session: AsyncSession, user_id: int) -> list[dict]:
    """The organizations this account belongs to that require two-step sign-in."""
    rows = (
        await session.execute(
            text(
                "SELECT o.id, o.name FROM memberships m JOIN organizations o ON o.id = m.org_id "
                "WHERE m.user_id = :u AND o.require_two_step ORDER BY o.name"
            ),
            {"u": int(user_id)},
        )
    ).all()
    return [{"org_id": r[0], "name": r[1]} for r in rows]


async def sign_in_requirement(session: AsyncSession, user_id: int) -> Purpose | None:
    """What a password, email-link or Google sign-in still owes before a session.

    "verify": the account has two-step on, so a code (or a recovery code).
    "setup": it hasn't, but an organization it belongs to requires it.
    None: nothing; the session is issued as before.
    """
    row = await load(session, user_id)
    if row is not None and row.enabled:
        return "verify"
    if await requiring_orgs(session, user_id):
        return "setup"
    return None


def _no_database() -> bool:
    """True only in a unit-test harness with no database configured at all.

    Same convenience as ``require_dashboard_session``: a released process never
    gets it (it answers 503), and any process with a database fails closed when
    the read fails, because the error propagates.
    """
    if os.getenv("DATABASE_URL", "").strip():
        return False
    from src.config.production import is_production

    if is_production():
        raise _err(503, "auth_dependency_unavailable", "Authentication is temporarily unavailable.")
    return True


async def sign_in_requirement_for(user_id: int) -> Purpose | None:
    """:func:`sign_in_requirement` on its own short-lived session (for auth routes)."""
    if _no_database():
        return None
    from src.auth.models import _session

    async with _session()() as s:
        return await sign_in_requirement(s, user_id)


async def requirement_for_email(email_norm: str) -> tuple[int, bool, int, Purpose | None] | None:
    """``(user_id, is_active, session_version, requirement)`` for an email, else None."""
    if _no_database():
        return None
    from src.auth.models import _session

    async with _session()() as s:
        row = (
            await s.execute(
                text("SELECT id, is_active, session_version FROM users WHERE email_lower = :e"),
                {"e": email_norm},
            )
        ).first()
        if row is None:
            return None
        purpose = await sign_in_requirement(s, int(row[0])) if row[1] is not False else None
        return int(row[0]), row[1] is not False, int(row[2] or 0), purpose


async def recovery_codes_left(session: AsyncSession, user_id: int) -> int:
    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM user_two_step_recovery_codes "
                    "WHERE user_id = :u AND used_at IS NULL"
                ),
                {"u": int(user_id)},
            )
        ).scalar_one()
    )


async def status(session: AsyncSession, user_id: int) -> dict:
    row = await load(session, user_id)
    enabled = bool(row and row.enabled)
    locked = row.locked_until if row and row.locked_until and row.locked_until > _now() else None
    return {
        "enabled": enabled,
        "enabled_at": row.enabled_at.isoformat() if enabled and row and row.enabled_at else None,
        "recovery_codes_left": await recovery_codes_left(session, user_id) if enabled else 0,
        "required_by": [o["name"] for o in await requiring_orgs(session, user_id)],
        "locked_until": locked.isoformat() if locked else None,
        "period_seconds": totp.PERIOD,
        "digits": totp.DIGITS,
    }


# ── enrolment ─────────────────────────────────────────────────────────────────
async def begin_enrolment(session: AsyncSession, user_id: int, account: str) -> dict:
    """A new secret, kept pending (sealed) until the first code confirms it."""
    row = await load(session, user_id, for_update=True)
    if row is not None and row.enabled:
        raise _err(409, "two_step_already_on", "Two-step sign-in is already on for this account.")
    secret = totp.new_secret()
    await session.execute(
        text(
            "INSERT INTO user_two_step (user_id, pending_secret_sealed, pending_created_at, updated_at) "
            "VALUES (:u, :p, now(), now()) ON CONFLICT (user_id) DO UPDATE SET "
            "pending_secret_sealed = EXCLUDED.pending_secret_sealed, "
            "pending_created_at = EXCLUDED.pending_created_at, updated_at = now()"
        ),
        {"u": int(user_id), "p": seal(secret)},
    )
    uri = totp.otpauth_uri(secret, account, max_len=qr.MAX_BYTES)
    return {
        "manual_key": totp.manual_key(secret),
        "otpauth_uri": uri,
        "qr": qr.encode(uri),
        "issuer": totp.ISSUER,
        "account": account,
        "expires_in_seconds": int(ENROL_TTL.total_seconds()),
    }


async def _store_recovery_codes(session: AsyncSession, user_id: int) -> list[str]:
    codes = new_recovery_codes()
    await session.execute(
        text("DELETE FROM user_two_step_recovery_codes WHERE user_id = :u"), {"u": int(user_id)}
    )
    for code in codes:
        await session.execute(
            text(
                "INSERT INTO user_two_step_recovery_codes (user_id, code_hash) VALUES (:u, :h)"
            ),
            {"u": int(user_id), "h": recovery_hash(user_id, code.replace("-", ""))},
        )
    return codes


async def confirm_enrolment(session: AsyncSession, user_id: int, code: object) -> list[str]:
    """Turn two-step on with the first code from the app; returns the recovery codes.

    The caller audits and commits (one transaction with the session rotation).
    """
    row = await load(session, user_id, for_update=True)
    if row is not None and row.enabled:
        raise _err(409, "two_step_already_on", "Two-step sign-in is already on for this account.")
    if row is None or not row.pending_secret_sealed or row.pending_created_at is None:
        raise _err(409, "two_step_not_started", "Start setting up two-step sign-in first.")
    if _now() - row.pending_created_at > ENROL_TTL:
        raise _err(410, "two_step_setup_expired", "This setup expired after 30 minutes. Start again.")
    if totp.clean_code(code) is None:
        raise _err(400, "two_step_code_format", "Enter the 6-digit code from your authenticator app.")
    secret = unseal(row.pending_secret_sealed)
    step = totp.matching_step(secret, str(code))
    if step is None:
        raise _err(
            400,
            "two_step_code_wrong",
            "That code didn't match. Check the app shows ScaleCAD and that your phone's clock is set automatically.",
        )
    await session.execute(
        text(
            "UPDATE user_two_step SET secret_sealed = pending_secret_sealed, enabled_at = now(), "
            "pending_secret_sealed = NULL, pending_created_at = NULL, last_used_step = :s, "
            "failed_attempts = 0, locked_until = NULL, updated_at = now() WHERE user_id = :u"
        ),
        {"u": int(user_id), "s": step},
    )
    return await _store_recovery_codes(session, user_id)


# ── proving the second step ───────────────────────────────────────────────────
def _locked_error(until: datetime) -> HTTPException:
    wait = (until - _now()).total_seconds()
    return _err(
        429,
        "two_step_locked",
        f"Too many wrong codes. Code entry for this account is paused. Try again in {wait_words(wait)}.",
        retry_after_seconds=max(1, int(wait)),
    )


async def _record_failure(session: AsyncSession, user_id: int) -> datetime | None:
    """Count one wrong code; lock code entry after every LOCK_AFTER in a row.

    Committed at once (its own statement and commit), so a guess that fails
    still counts even though the request then raises.
    """
    row = (
        await session.execute(
            text(
                "UPDATE user_two_step SET failed_attempts = failed_attempts + 1, "
                "locked_until = CASE WHEN (failed_attempts + 1) % :n = 0 "
                "THEN now() + LEAST(:first * power(2, (failed_attempts + 1) / :n - 1), :max) "
                "* interval '1 second' ELSE locked_until END, updated_at = now() "
                "WHERE user_id = :u RETURNING failed_attempts, locked_until"
            ),
            {
                "u": int(user_id),
                "n": LOCK_AFTER,
                "first": LOCK_FIRST.total_seconds(),
                "max": LOCK_MAX.total_seconds(),
            },
        )
    ).first()
    locked_now = None
    if row is not None and int(row[0]) % LOCK_AFTER == 0 and row[1] is not None:
        locked_now = row[1]
        from src.services.audit_service import append_audit_entry

        await append_audit_entry(
            session,
            int(user_id),
            "auth.two_step_locked",
            "user",
            str(user_id),
            {"failed_attempts": int(row[0]), "locked_until": row[1].isoformat()},
        )
    await session.commit()
    return locked_now


async def prove(
    session: AsyncSession,
    user_id: int,
    *,
    code: object = None,
    recovery_code: object = None,
) -> Literal["code", "recovery"]:
    """Check a code or a recovery code for an account with two-step on.

    Locked accounts are refused before anything is compared. A wrong or reused
    code counts toward the lock. A matching code is spent (its time step can't
    be used again); a recovery code is marked used. The caller commits.
    """
    row = await load(session, user_id)
    if row is None or not row.enabled or not row.secret_sealed:
        raise _err(409, "two_step_off", "Two-step sign-in isn't on for this account.")
    if row.locked_until is not None and row.locked_until > _now():
        raise _locked_error(row.locked_until)

    if recovery_code not in (None, ""):
        flat = clean_recovery_code(recovery_code)
        used = None
        if flat is not None:
            used = (
                await session.execute(
                    text(
                        "UPDATE user_two_step_recovery_codes SET used_at = now() "
                        "WHERE user_id = :u AND code_hash = :h AND used_at IS NULL RETURNING id"
                    ),
                    {"u": int(user_id), "h": recovery_hash(user_id, flat)},
                )
            ).first()
        if used is None:
            await session.rollback()
            locked = await _record_failure(session, user_id)
            if locked is not None:
                raise _locked_error(locked)
            raise _err(400, "two_step_recovery_wrong", "That recovery code isn't valid or was already used.")
        await session.execute(
            text("UPDATE user_two_step SET failed_attempts = 0, updated_at = now() WHERE user_id = :u"),
            {"u": int(user_id)},
        )
        return "recovery"

    if totp.clean_code(code) is None:
        raise _err(400, "two_step_code_format", "Enter the 6-digit code from your authenticator app.")
    secret = unseal(row.secret_sealed)
    # The step this code belongs to, if any. Whether it was already spent is
    # decided by the compare-and-set below, so two requests racing with the
    # same code can't both pass.
    step = totp.matching_step(secret, str(code))
    spent = None
    if step is not None:
        spent = (
            await session.execute(
                text(
                    "UPDATE user_two_step SET last_used_step = :s, failed_attempts = 0, updated_at = now() "
                    "WHERE user_id = :u AND (last_used_step IS NULL OR last_used_step < :s) RETURNING user_id"
                ),
                {"u": int(user_id), "s": step},
            )
        ).first()
    if spent is None:
        reused = step is not None
        await session.rollback()
        locked = await _record_failure(session, user_id)
        if locked is not None:
            raise _locked_error(locked)
        if reused:
            raise _err(400, "two_step_code_used", "That code was already used. Wait for the next one in the app.")
        raise _err(
            400,
            "two_step_code_wrong",
            "That code didn't match. Use the newest code in your authenticator app.",
        )
    return "code"


async def disable(session: AsyncSession, user_id: int) -> None:
    """Remove the secret and recovery codes (after :func:`prove`). Caller commits."""
    orgs = await requiring_orgs(session, user_id)
    if orgs:
        names = ", ".join(o["name"] for o in orgs)
        raise _err(
            409,
            "two_step_required_by_org",
            f"{names} requires two-step sign-in, so it stays on. An admin of {names} can change that in Members.",
        )
    await session.execute(text("DELETE FROM user_two_step_recovery_codes WHERE user_id = :u"), {"u": int(user_id)})
    await session.execute(text("DELETE FROM user_two_step WHERE user_id = :u"), {"u": int(user_id)})


async def replace_recovery_codes(session: AsyncSession, user_id: int) -> list[str]:
    """Ten new recovery codes (after :func:`prove`); the old ones stop working."""
    return await _store_recovery_codes(session, user_id)


# ── organization rule ─────────────────────────────────────────────────────────
async def org_policy(session: AsyncSession, org_id: str) -> bool:
    row = (
        await session.execute(
            text("SELECT require_two_step FROM organizations WHERE id = :o"), {"o": org_id}
        )
    ).first()
    return bool(row and row[0])


async def member_status(session: AsyncSession, org_id: str) -> list[dict]:
    """Who in the org has two-step on (for admins)."""
    rows = (
        await session.execute(
            text(
                "SELECT u.id, u.email, m.org_role, (t.enabled_at IS NOT NULL AND t.secret_sealed IS NOT NULL), "
                "u.auth_provider "
                "FROM memberships m JOIN users u ON u.id = m.user_id "
                "LEFT JOIN user_two_step t ON t.user_id = u.id "
                "WHERE m.org_id = :o ORDER BY u.email"
            ),
            {"o": org_id},
        )
    ).all()
    return [
        {
            "user_id": int(r[0]),
            "email": r[1],
            "org_role": r[2],
            "two_step_on": bool(r[3]),
            "single_sign_on": (r[4] or "") in ("saml", "oidc"),
        }
        for r in rows
    ]


async def set_org_policy(session: AsyncSession, org_id: str, actor_id: int, required: bool) -> dict:
    """Turn the org's rule on or off. Caller audits and commits.

    Turning it on needs the admin's own two-step first, and signs out every
    member without it (their next password, email-link or Google sign-in asks
    them to set it up before they reach anything). Returns who was signed out.
    """
    signed_out: list[int] = []
    if required:
        mine = await load(session, actor_id)
        if mine is None or not mine.enabled:
            raise _err(
                409,
                "two_step_admin_first",
                "Turn on two-step sign-in for your own account first, in Account › Security.",
            )
        rows = (
            await session.execute(
                text(
                    "UPDATE users SET session_version = session_version + 1 WHERE id IN ("
                    "SELECT m.user_id FROM memberships m LEFT JOIN user_two_step t ON t.user_id = m.user_id "
                    "WHERE m.org_id = :o AND m.user_id <> :a "
                    "AND (t.enabled_at IS NULL OR t.secret_sealed IS NULL)) RETURNING id"
                ),
                {"o": org_id, "a": int(actor_id)},
            )
        ).all()
        signed_out = [int(r[0]) for r in rows]
    await session.execute(
        text("UPDATE organizations SET require_two_step = :r WHERE id = :o"),
        {"r": bool(required), "o": org_id},
    )
    return {"required": bool(required), "signed_out_user_ids": signed_out}
