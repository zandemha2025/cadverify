"""Free allowance a deleted account had used, so signing up again doesn't reissue it.

Product decision (2026-10-22): deleting an account keeps only what billing law
needs, plus this: a one-way fingerprint of the account's normalised email and
how many free checks and free catalog parts it had used
(``deleted_account_allowances``). A new account whose normalised email has the
same fingerprint starts from those counts.

* The fingerprint is ``hmac_index`` (HMAC-SHA256 under ``API_KEY_PEPPER``, the
  API-key index helper) of a domain-separated string, so it can't be matched
  against API-key indexes and the email can't be read back from it.
* Carrying over writes placeholder ledger rows on the new account, the first
  time its allowance is read: completed ``trial_checks`` rows with the file
  hash ``carried-check:<n>`` and counted ``catalog_parts`` rows with
  ``carried-catalog:<n>``, dated at the deletion. Every existing count then
  includes them unchanged (a Pro period counts only checks made in it, so they
  never use Pro checks). The ledger row is removed in the same transaction.
* It runs in a savepoint and never blocks a check: if the ledger can't be
  read (no pepper configured, table missing), the allowance is read as before.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import CatalogPart, DeletedAccountAllowance, TrialCheck

logger = logging.getLogger("cadverify.deleted_account_allowance")

_DOMAIN = "deleted-account-allowance:v1:"
# More than any free allowance; a larger count still uses up every free slot.
MAX_CARRIED_ROWS = 1000
CHECK_PREFIX = "carried-check:"
CATALOG_PREFIX = "carried-catalog:"


def email_fingerprint(email: str) -> str:
    """One-way fingerprint of the normalised email (never stored as the email)."""
    from src.auth.disposable import normalize_email
    from src.auth.hashing import hmac_index

    return hmac_index(_DOMAIN + normalize_email((email or "").strip()))


async def used_counts(session: AsyncSession, user_id: int) -> tuple[int, int]:
    """(free checks used, free catalog parts counted) by the account, lifetime."""
    from src.auth import catalog_allowance, validation_caps

    checks, _reserved = await validation_caps._counts(session, user_id, datetime.now(timezone.utc))
    counted, _reserved_parts = await catalog_allowance._used(session, user_id)
    return int(checks), int(counted)


async def remember(session: AsyncSession, email: str, checks_used: int, catalog_parts_used: int) -> None:
    """Record a deleted account's use; a repeat keeps the larger counts."""
    stmt = pg_insert(DeletedAccountAllowance).values(
        email_hmac=email_fingerprint(email),
        checks_used=max(0, int(checks_used)),
        catalog_parts_used=max(0, int(catalog_parts_used)),
    )
    from sqlalchemy import func

    stmt = stmt.on_conflict_do_update(
        index_elements=[DeletedAccountAllowance.email_hmac],
        set_={
            "checks_used": func.greatest(DeletedAccountAllowance.checks_used, stmt.excluded.checks_used),
            "catalog_parts_used": func.greatest(
                DeletedAccountAllowance.catalog_parts_used, stmt.excluded.catalog_parts_used
            ),
            "deleted_at": func.now(),
        },
    )
    await session.execute(stmt)


async def carry_over(session: AsyncSession, user_id: int, email: str | None) -> bool:
    """Start a new account from a deleted account's use, once. True when applied.

    Runs in a savepoint of the caller's transaction: it persists when the
    caller commits (a check reservation does), and is simply applied again on
    the next read when the caller doesn't.
    """
    if not email:
        return False
    try:
        fingerprint = email_fingerprint(email)
    except Exception:  # noqa: BLE001 - no pepper: nothing to match against
        logger.warning("allowance carry-over skipped: no fingerprint key")
        return False
    try:
        async with session.begin_nested():
            row = (
                await session.execute(
                    select(DeletedAccountAllowance)
                    .where(DeletedAccountAllowance.email_hmac == fingerprint)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                return False
            when = row.deleted_at or datetime.now(timezone.utc)
            checks = min(MAX_CARRIED_ROWS, int(row.checks_used or 0))
            parts = min(MAX_CARRIED_ROWS, int(row.catalog_parts_used or 0))
            if checks:
                await session.execute(
                    pg_insert(TrialCheck)
                    .values([
                        {"user_id": user_id, "check_id": f"{CHECK_PREFIX}{i}", "file_hash": f"{CHECK_PREFIX}{i}",
                         "completed": True, "operations": {}, "created_at": when}
                        for i in range(1, checks + 1)
                    ])
                    .on_conflict_do_nothing()
                )
            if parts:
                await session.execute(
                    pg_insert(CatalogPart)
                    .values([
                        {"user_id": user_id, "file_hash": f"{CATALOG_PREFIX}{i}", "state": "counted",
                         "created_at": when, "updated_at": when}
                        for i in range(1, parts + 1)
                    ])
                    .on_conflict_do_nothing()
                )
            await session.execute(
                delete(DeletedAccountAllowance).where(DeletedAccountAllowance.email_hmac == fingerprint)
            )
        logger.info("account %d starts from a deleted account's allowance (%d checks, %d parts)", user_id, checks, parts)
        return True
    except Exception:  # noqa: BLE001 - never block a check on this ledger
        logger.warning("allowance carry-over for account %d could not be read", user_id, exc_info=True)
        return False
