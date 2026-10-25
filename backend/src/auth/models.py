"""Auth-table helpers using raw text() queries.

Engine and session factory are now centralised in src.db.engine (Phase 3).
This module retains its raw-SQL query functions for backward compatibility.
"""
from __future__ import annotations

from src.config.public_urls import error_doc_url

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.engine import get_engine as _engine, get_session_factory

if TYPE_CHECKING:
    from fastapi import HTTPException


def _session() -> async_sessionmaker[AsyncSession]:
    return get_session_factory()


@dataclass
class ApiKeyRow:
    id: int
    user_id: int
    prefix: str
    hmac_index: str
    secret_hash: str
    revoked_at: object
    # Org-membership beat: the owner's platform role + account-active flag,
    # JOINed in ``lookup_api_key`` so the API-key auth path can enforce
    # deactivation and read the role in a SINGLE query (no extra round trip).
    # Defaulted so any legacy positional constructor still works.
    role: str = "analyst"
    is_active: bool = True
    # API keys are tenant-bound credentials.  ``org_id`` is the organization
    # that issued the key; ``active_org_id`` is the owner's currently selected
    # live membership at authentication time.  The auth dependency requires
    # these to match before admitting the request.
    org_id: str | None = None
    active_org_id: str | None = None
    # 0061: the key's own scope ('read', 'read_write', or None = read and
    # write for keys made before 0061), when it stops working, whether that
    # moment has passed on the database clock, and the owner's org role in the
    # key's issuing org (a viewer's key is read only whatever its scope says).
    scope: str | None = None
    expires_at: object = None
    expired: bool = False
    key_org_role: str | None = None
    # The key's org requires two-step sign-in and its owner has none (and
    # doesn't sign in through single sign-on): the key is refused until they
    # set it up, then works again (``require_api_key``).
    two_step_owed: bool = False


@dataclass
class SessionUserRow:
    user_id: int
    role: str
    is_active: bool
    session_version: int


async def upsert_user(
    email: str,
    google_sub: str | None,
    email_lower: str,
    disposable_flag: bool = False,
    auth_provider: str = "google",
) -> int:
    """Get or create the account for a Google (or other) sign-in; returns its id.

    ``email_lower`` is the stored form (``normalize_email``: no "+tag", Gmail
    dots dropped), so it can name an account whose own address differs. A
    Google subject therefore reaches an existing account only when that
    account is already linked to the same subject, or is linked to none and its
    stored address is this exact address (:func:`_same_mailbox`: case aside, and
    dots aside on Gmail). "dana+x@corp.example" never opens "dana@corp.example",
    and a different Google account never opens one already linked: both get a
    409 and the account is left untouched.
    """
    provider = (auth_provider or "google").strip().lower()
    async with _session()() as s:
        row = (
            await s.execute(
                text(
                    "INSERT INTO users (email, email_lower, google_sub, auth_provider, disposable_flag) "
                    "VALUES (:e, :el, :g, :ap, :d) "
                    "ON CONFLICT (email_lower) DO NOTHING "
                    "RETURNING id"
                ),
                {
                    "e": email,
                    "el": email_lower,
                    "g": google_sub,
                    "ap": provider,
                    "d": disposable_flag,
                },
            )
        ).first()
        if row is None:
            # An account already holds this address's stored form.
            existing = (
                await s.execute(
                    text(
                        "SELECT id, email, google_sub FROM users "
                        "WHERE email_lower = :el FOR UPDATE"
                    ),
                    {"el": email_lower},
                )
            ).first()
            if existing is None:  # pragma: no cover - the conflicting row just existed
                raise RuntimeError("users row vanished during sign-in")
            if google_sub is not None:
                if existing[2] is not None and existing[2] != google_sub:
                    raise _google_link_refused("other_google_account")
                if existing[2] is None:
                    if not _same_mailbox(existing[1] or "", email or ""):
                        raise _google_link_refused("other_address_form")
                    await s.execute(
                        text("UPDATE users SET google_sub = :g WHERE id = :u"),
                        {"g": google_sub, "u": int(existing[0])},
                    )
            else:
                # A sign-in without a Google subject replaces only the original
                # Google default provider of an account Google never linked.
                await s.execute(
                    text(
                        "UPDATE users SET auth_provider = :ap WHERE id = :u "
                        "AND google_sub IS NULL AND auth_provider = 'google'"
                    ),
                    {"ap": provider, "u": int(existing[0])},
                )
            row = existing
        # W1: guarantee the (possibly brand-new) user has a personal org +
        # admin membership before any of their rows are written. Idempotent:
        # a returning/existing user already has one, so this is a no-op read.
        from src.auth.org_context import ensure_personal_org

        uid = int(row[0])
        # §39 SSO re-provision hole: a returning account that an admin has
        # DEACTIVATED must NOT be resurrected by an SSO/magic re-login. The
        # ON CONFLICT above only backfills google_sub — it never clears
        # is_active — but the login flow must still refuse to hand back a
        # session/key. Raise a clean 403 BEFORE provisioning/committing (the
        # `async with` block exits without commit). A brand-new user is active
        # by server-default, so this only ever blocks an offboarded account.
        active = (
            await s.execute(
                text("SELECT is_active FROM users WHERE id = :u"),
                {"u": uid},
            )
        ).first()
        if active is not None and active[0] is False:
            raise _account_deactivated()
        await ensure_personal_org(s, uid, email)
        await s.commit()
        return uid


# Domains where Google guarantees dots in the local part never matter:
# "d.ana@gmail.com" and "dana@gmail.com" are one mailbox.
_DOTLESS_LOCAL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


def _same_mailbox(stored: str, signed_in: str) -> bool:
    """Whether two addresses are the same mailbox, so a Google sign-in may link.

    Case never matters, and on gmail.com/googlemail.com neither do dots in the
    local part. Nothing else is set aside: a "+tag" or a dot on any other domain
    can be someone else's mailbox.
    """
    def canonical(address: str) -> str:
        local, _, domain = address.strip().lower().partition("@")
        if domain in _DOTLESS_LOCAL_DOMAINS:
            local = local.replace(".", "")
        return f"{local}@{domain}"

    return canonical(stored) == canonical(signed_in)


def _google_link_refused(reason: str) -> "HTTPException":
    """409 for a Google sign-in that may not open the account its address names."""
    from fastapi import HTTPException

    if reason == "other_google_account":
        message = (
            "The ScaleCAD account for this address is linked to a different Google "
            "account. Sign in with that Google account, or with an email link or password."
        )
    else:
        message = (
            "A ScaleCAD account already uses a different form of this address, so "
            "this Google account can't open it. Sign in to that account with its own "
            "address, by email link or password."
        )
    return HTTPException(
        status_code=409,
        detail={
            "code": "google_link_refused",
            "message": message,
            "doc_url": error_doc_url("google_link_refused"),
        },
    )


def _account_deactivated() -> "HTTPException":
    """403 for a deactivated account attempting any auth path (shared shape)."""
    from fastapi import HTTPException

    return HTTPException(
        status_code=403,
        detail={
            "code": "account_deactivated",
            "message": "This account has been deactivated.",
            "doc_url": error_doc_url("account_deactivated"),
        },
    )


async def user_is_active(user_id: int) -> bool:
    """True unless the user row exists AND is explicitly deactivated.

    The account-level deactivation read (§39) shared by the login and
    session-validation paths. A missing user is treated as active (existence is
    not this check's concern — it preserves the pre-beat behaviour for a valid
    session whose user row was hard-deleted); only an explicit ``is_active =
    false`` blocks. Opens its own session like the other auth helpers here.
    """
    async with _session()() as s:
        r = (
            await s.execute(
                text("SELECT is_active FROM users WHERE id = :u"),
                {"u": user_id},
            )
        ).first()
    return True if r is None else bool(r[0])


async def lookup_session_user(user_id: int) -> SessionUserRow | None:
    """Return the current session-validation state for a dashboard user."""
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    "SELECT id, role, is_active, session_version "
                    "FROM users WHERE id = :u"
                ),
                {"u": user_id},
            )
        ).first()
    if r is None:
        return None
    return SessionUserRow(
        user_id=int(r[0]),
        role=r[1] or "analyst",
        is_active=bool(r[2]),
        session_version=int(r[3] or 0),
    )


async def get_user_session_version(user_id: int) -> int:
    """Current dashboard-session version, defaulting to 0 for absent rows."""
    row = await lookup_session_user(user_id)
    return 0 if row is None else row.session_version


async def bump_session_version(user_id: int) -> int | None:
    """Invalidate all existing dashboard sessions for a user.

    Stateless HMAC sessions remain cheap, but the signed payload carries this
    monotonically increasing user-row version. Incrementing it revokes every
    older cookie without storing per-session rows.
    """
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    "UPDATE users "
                    "SET session_version = session_version + 1 "
                    "WHERE id = :u "
                    "RETURNING session_version"
                ),
                {"u": user_id},
            )
        ).first()
        if r is not None:
            from src.services.audit_service import append_audit_entry

            await append_audit_entry(
                s,
                user_id,
                "user.sessions_revoked",
                "user",
                str(user_id),
                {"revoked_by": user_id, "scope": "self"},
            )
        await s.commit()
    return None if r is None else int(r[0])


async def create_password_user(
    email: str,
    email_lower: str,
    password_hash: str,
    disposable_flag: bool = False,
    full_name: str | None = None,
    phone: str | None = None,
    signup_metadata: dict | None = None,
) -> int | None:
    """INSERT a new email+password user.

    Returns the new user id, or None if email_lower already exists (caller maps
    None -> 409 email_taken). Does NOT attach a password to an existing OAuth/
    SAML row — ON CONFLICT DO NOTHING leaves any existing account untouched.
    """
    async with _session()() as s:
        row = (
            await s.execute(
                text(
                    "INSERT INTO users (email, email_lower, password_hash, auth_provider, disposable_flag, full_name, phone, signup_metadata) "
                    "VALUES (:e, :el, :ph, 'password', :d, :name, :phone, CAST(:metadata AS jsonb)) "
                    "ON CONFLICT (email_lower) DO NOTHING RETURNING id"
                ),
                {"e": email, "el": email_lower, "ph": password_hash, "d": disposable_flag,
                 "name": full_name, "phone": phone, "metadata": json.dumps(signup_metadata or {})},
            )
        ).first()
        if row is None:
            # email_lower already existed -> no new user, nothing to provision.
            await s.commit()
            return None
        # W1: provision the new user's personal org before returning (see
        # upsert_user). Idempotent get-or-create.
        from src.auth.org_context import ensure_personal_org

        uid = int(row[0])
        # Named after the work email's company, or "<name>'s workspace" (renamable).
        await ensure_personal_org(s, uid, email, full_name)
        from src.services.audit_service import append_audit_entry

        await append_audit_entry(
            s,
            uid,
            "auth.signup",
            "user",
            str(uid),
            user_email=email,
        )
        await s.commit()
        return uid


async def get_login_credentials(
    email_lower: str,
) -> tuple[int, str | None, str] | None:
    """Return (user_id, password_hash, role) for a normalized email, else None.

    password_hash is None for accounts created via OAuth/SAML/magic-link.
    """
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    "SELECT id, password_hash, role FROM users WHERE email_lower = :el"
                ),
                {"el": email_lower},
            )
        ).first()
        return (int(r[0]), r[1], r[2]) if r else None


async def get_user_public(user_id: int) -> tuple[str, str, str, bool] | None:
    """Return public account state; never return the password hash."""
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    "SELECT email, role, auth_provider, password_hash IS NOT NULL "
                    "FROM users WHERE id = :u"
                ),
                {"u": user_id},
            )
        ).first()
        return (r[0], r[1], r[2], bool(r[3])) if r else None


async def update_password_hash(user_id: int, password_hash: str) -> None:
    """Persist a re-hashed password (Argon2 parameter upgrade on login)."""
    async with _session()() as s:
        await s.execute(
            text("UPDATE users SET password_hash = :ph WHERE id = :u"),
            {"ph": password_hash, "u": user_id},
        )
        await s.commit()


async def set_password_hash(
    user_id: int, password_hash: str, *, expected_hash: str | None = None,
) -> int | None:
    """Atomically set a password, append its audit event and rotate sessions.

    Magic-link registration proves control of the email first. This compare-
    and-set defaults to initial setup only. A change requires the caller to
    verify the current password and pass that exact hash. Updating the
    password and session version in one statement prevents a committed password
    from being paired with an unrotated session if a second DB call fails.
    """
    async with _session()() as s:
        row = (
            await s.execute(
                text(
                    "UPDATE users SET password_hash = :ph, "
                    "session_version = session_version + 1 "
                    "WHERE id = :u AND password_hash IS NOT DISTINCT FROM :expected "
                    "AND is_active = TRUE "
                    "RETURNING session_version"
                ),
                {"ph": password_hash, "u": user_id, "expected": expected_hash},
            )
        ).first()
        if row is not None:
            from src.services.audit_service import append_audit_entry

            await append_audit_entry(
                s,
                user_id,
                "auth.password_changed" if expected_hash is not None else "auth.password_initialized",
                "user",
                str(user_id),
            )
        await s.commit()
    return None if row is None else int(row[0])


async def create_api_key(
    user_id: int, name: str, prefix: str, hmac_idx: str, secret_hash: str
) -> int:
    """The key made at Google sign-in, in the account's active org.

    It follows the branch's rules for every key made at sign-in
    (``provisioning.insert_login_key``): read only, expiring in 90 days.
    """
    from src.auth.org_context import resolve_org
    from src.auth.provisioning import insert_login_key

    async with _session()() as s:
        # api_keys.org_id is NOT NULL (W1). The caller always holds a provisioned
        # org by now (signup provisions one; the 0009 backfill covers existing
        # users), so resolve_org returns it.
        org_id = await resolve_org(s, user_id)
        if org_id is None:
            # The NOT NULL column would refuse the insert; say why instead.
            raise RuntimeError(f"user {user_id} has no organization to hold a sign-in key")
        key_id = await insert_login_key(
            s,
            user_id=user_id,
            org_id=org_id,
            key_name=name,
            prefix=prefix,
            hmac_idx=hmac_idx,
            secret_hash=secret_hash,
        )
        await s.commit()
        return key_id


async def user_has_active_api_key(user_id: int) -> bool:
    """True if the user already holds at least one non-revoked API key.

    Used by the SSO login paths (SAML ACS, Google callback, magic-link verify)
    to avoid minting a fresh key on every single login — a new key should be
    issued only when the account has none active.
    """
    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    "SELECT 1 FROM api_keys "
                    "WHERE user_id = :u AND revoked_at IS NULL LIMIT 1"
                ),
                {"u": user_id},
            )
        ).first()
        return r is not None


async def lookup_api_key(hmac_idx: str) -> ApiKeyRow | None:
    from src.auth.two_step import SINGLE_SIGN_ON_ACCOUNT_SQL

    async with _session()() as s:
        r = (
            await s.execute(
                text(
                    "SELECT k.id, k.user_id, k.prefix, k.hmac_index, k.secret_hash, "
                    "k.revoked_at, u.role, u.is_active, k.org_id, "
                    "COALESCE("
                    "(SELECT current_m.org_id FROM memberships current_m "
                    " WHERE current_m.user_id = k.user_id "
                    " AND current_m.org_id = u.current_org_id LIMIT 1), "
                    "(SELECT oldest_m.org_id FROM memberships oldest_m "
                    " WHERE oldest_m.user_id = k.user_id "
                    " ORDER BY oldest_m.created_at ASC, oldest_m.id ASC LIMIT 1)"
                    ") AS active_org_id, "
                    "k.scope, k.expires_at, "
                    "(k.expires_at IS NOT NULL AND k.expires_at <= now()) AS expired, "
                    "key_m.org_role AS key_org_role, "
                    "(COALESCE(key_o.require_two_step, false) "
                    " AND NOT COALESCE(t.enabled_at IS NOT NULL AND t.secret_sealed IS NOT NULL, false) "
                    f" AND NOT {SINGLE_SIGN_ON_ACCOUNT_SQL}) AS two_step_owed "
                    "FROM api_keys k JOIN users u ON u.id = k.user_id "
                    "JOIN memberships key_m ON key_m.user_id = k.user_id "
                    "AND key_m.org_id = k.org_id "
                    "LEFT JOIN organizations key_o ON key_o.id = k.org_id "
                    "LEFT JOIN user_two_step t ON t.user_id = k.user_id "
                    "WHERE k.hmac_index = :h"
                ),
                {"h": hmac_idx},
            )
        ).first()
        return ApiKeyRow(*r) if r else None


async def lookup_user_role(user_id: int) -> str:
    """Return the PLATFORM role column for a user, defaulting to 'analyst'."""
    async with _session()() as s:
        r = (
            await s.execute(
                text("SELECT role FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
        ).first()
        return r[0] if r else "analyst"


async def lookup_org_membership(user_id: int) -> tuple[str, str] | None:
    """Return ``(org_id, org_role)`` for the user's primary membership, else None.

    W1 step 2 — the org-scoped *authorization* read that ``require_org_role``
    resolves against. Single-org in v1; if a user (defensively) holds more than
    one membership the oldest wins, matching ``org_context.resolve_org``'s
    tie-break so the org boundary a route enforces is deterministic and stable
    across the two resolution paths. Opens its own session like the other auth
    helpers here, so it composes with ``require_api_key`` without a request DB
    dependency. Returns None for a user with no membership (a mocked test
    session, or a superadmin provisioned without one).

    Once a role gate in this request checked an org (``auth.org_binding``, R2
    F1), this answers the caller's role in THAT org (None if they left it), so
    every later check in the request (another gate, admission, org limits)
    reads the org the request writes to.
    """
    from src.auth.org_binding import gate_org

    bound = gate_org(user_id)
    async with _session()() as s:
        if bound is not None:
            r = (
                await s.execute(
                    text(
                        "SELECT m.org_id, m.org_role FROM memberships m "
                        "WHERE m.user_id = :uid AND m.org_id = :org LIMIT 1"
                    ),
                    {"uid": user_id, "org": bound},
                )
            ).first()
            return (r[0], r[1]) if r else None
        r = (
            await s.execute(
                text(
                    "SELECT m.org_id, m.org_role FROM memberships m "
                    "WHERE m.user_id = :uid "
                    # Org-membership beat: resolve the ACTIVE org — the user's
                    # current_org_id when it names a live membership (put first
                    # via IS NOT DISTINCT FROM so NULL/stale falls through), else
                    # the oldest membership. Single-membership users have one row,
                    # so this is byte-identical to the pre-beat oldest rule.
                    "ORDER BY (m.org_id IS NOT DISTINCT FROM "
                    "(SELECT current_org_id FROM users WHERE id = :uid)) DESC, "
                    "m.created_at ASC, m.id ASC LIMIT 1"
                ),
                {"uid": user_id},
            )
        ).first()
        return (r[0], r[1]) if r else None


async def touch_last_used(api_key_id: int) -> None:
    async with _session()() as s:
        await s.execute(
            text("UPDATE api_keys SET last_used_at = now() WHERE id = :i"),
            {"i": api_key_id},
        )
        await s.commit()
