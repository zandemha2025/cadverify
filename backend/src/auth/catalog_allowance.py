"""The free catalog run: a work-email account's first catalog parts.

Product owner decision (2026-10-21): an account with a work email gets its
first FREE_CATALOG_PARTS (default 50) catalog parts free, self-serve, separate
from its single-part checks. Personal-email accounts keep single checks only.
The pilot plan is unlimited.

A part means a distinct file, by the same identity as a check (the hash of the
file name and bytes, ``file_identity``). Rules:

- A part the account already ran in a catalog run, or already checked as a
  single part, never counts again (``catalog_parts`` row, or a completed
  ``trial_checks`` row with the same hash).
- The app's sample part never counts (it is never stored as a catalog part).
- Phone verification applies as for free checks (SMS_VERIFICATION_REQUIRED).
- Admission is atomic: the account row is locked (NO KEY UPDATE, the same lock
  as ``validation_caps.reserve_check``) while the new parts are counted and
  reserved, in the same transaction that creates the batch. Two runs started
  at once can never both take the last slots.
- A reserved part holds its slot while its batch item is pending, queued or
  processing, and keeps it for good once the item completes (``counted``).
  A part whose item failed or was skipped gives the slot back without any
  write: liveness is read from the item. Deleting the batch or the part keeps a
  counted slot used (the foreign keys are SET NULL).

Every other protection stays on the route: authentication and roles, org
scoping, the kill switch, org limits, the per-user ceiling on free runs
(src.auth.free_tool_limits "catalog"), one active free run at a time, the free
run's ZIP size and concurrency limits, and the batch's own extraction limits.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

from fastapi import Depends, HTTPException
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.email_tiers import email_tier
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_session_factory
from src.db.models import Batch, BatchItem, CatalogPart, TrialCheck, User

DEFAULT_FREE_CATALOG_PARTS = 50
DEFAULT_FREE_CATALOG_MAX_ZIP_BYTES = 1024 ** 3  # 1 GiB
DEFAULT_FREE_CATALOG_CONCURRENCY = 4
# Item states that still hold (or have used) a reserved slot.
LIVE_ITEM_STATES = ("pending", "queued", "processing", "completed")
_TERMINAL_BATCH = ("completed", "failed", "cancelled")
_TRUTHY = {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(hi, max(lo, value))


def free_catalog_parts() -> int:
    return _env_int("FREE_CATALOG_PARTS", DEFAULT_FREE_CATALOG_PARTS, 0, 100_000)


def free_catalog_max_zip_bytes() -> int:
    return _env_int("FREE_CATALOG_MAX_ZIP_BYTES", DEFAULT_FREE_CATALOG_MAX_ZIP_BYTES, 1024 * 1024, 5 * 1024 ** 3)


def free_catalog_concurrency() -> int:
    return _env_int("FREE_CATALOG_CONCURRENCY", DEFAULT_FREE_CATALOG_CONCURRENCY, 1, 12)


def file_identity(filename: str, data: bytes) -> str:
    """The check identity of a file: sha256 of len(name), name and bytes.

    Byte-for-byte the digest ``validation_caps.enforce_validation_caps`` binds a
    single check to, so a part checked on its own and the same file in a
    catalog run are the same part.
    """
    name = (filename or "").encode()
    digest = hashlib.sha256(len(name).to_bytes(8, "big") + name)
    digest.update(data)
    return digest.hexdigest()


@dataclass(frozen=True)
class CatalogAccess:
    plan: str  # trial | pro | pilot (the account's plan column)
    tier: str  # work | personal | pilot
    cap: int | None  # None = unlimited (pilot)
    phone_required: bool = False

    @property
    def free(self) -> bool:
        """A run on the free allowance (anything but the pilot plan)."""
        return self.cap is not None


def _problem(status: int, code: str, message: str, **details) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **details})


def _unavailable() -> HTTPException:
    return _problem(503, "allowance_unavailable", "We couldn't confirm your catalog allowance. Please try again shortly.")


def _sms_required() -> bool:
    return os.getenv("SMS_VERIFICATION_REQUIRED", "0").strip().lower() in _TRUTHY


async def _access(session: AsyncSession, user_id: int, *, lock: bool = False) -> CatalogAccess:
    query = select(User.plan, User.email_lower, User.phone_verified_at).where(User.id == user_id)
    if lock:
        query = query.with_for_update(key_share=True)
    plan, email, phone_verified_at = (await session.execute(query)).one()
    if plan == "pilot":
        return CatalogAccess(plan="pilot", tier="pilot", cap=None)
    # An account signed up again after deleting one starts from what that one used.
    from src.services.deleted_account_allowance import carry_over

    await carry_over(session, user_id, email)
    tier = email_tier(email)
    return CatalogAccess(
        plan=plan or "trial",
        tier=tier,
        cap=free_catalog_parts() if tier == "work" else 0,
        phone_required=_sms_required() and phone_verified_at is None,
    )


def _live_part():
    """A catalog part that holds a slot: counted, or reserved by a live item."""
    return or_(
        CatalogPart.state == "counted",
        exists().where(
            BatchItem.id == CatalogPart.batch_item_id,
            BatchItem.status.in_(LIVE_ITEM_STATES),
        ),
    )


async def _used(session: AsyncSession, user_id: int) -> tuple[int, int]:
    """``(counted, reserved)`` slots held by the account."""
    rows = (await session.execute(
        select(CatalogPart.state, func.count())
        .where(CatalogPart.user_id == user_id, _live_part())
        .group_by(CatalogPart.state)
    )).all()
    by_state = {state: int(n) for state, n in rows}
    return by_state.get("counted", 0), by_state.get("reserved", 0)


def _usage_dict(access: CatalogAccess, counted: int, reserved: int) -> dict:
    if access.cap is None:
        return {"eligible": True, "unlimited": True, "cap": None, "used": None, "reserved": None, "remaining": None}
    return {
        "eligible": access.tier == "work",
        "unlimited": False,
        "cap": access.cap,
        "used": counted,
        "reserved": reserved,
        "remaining": max(0, access.cap - counted - reserved),
    }


async def catalog_usage(user_id: int, session: AsyncSession | None = None) -> dict:
    """The account's catalog allowance: ``eligible``, ``cap``, ``used``, ``reserved``, ``remaining``.

    ``used`` counts parts whose run completed; ``reserved`` the parts of runs
    still going. Pilot reads ``unlimited``.
    """
    async def _read(s: AsyncSession) -> dict:
        access = await _access(s, user_id)
        if access.cap is None:
            return _usage_dict(access, 0, 0)
        counted, reserved = await _used(s, user_id)
        return _usage_dict(access, counted, reserved)

    try:
        if session is not None:
            return await _read(session)
        async with get_session_factory()() as s:
            return await _read(s)
    except SQLAlchemyError as exc:
        raise _unavailable() from exc


def work_email_required() -> HTTPException:
    return _problem(
        403, "catalog_run_work_email",
        "Catalog runs come with work-email accounts. Sign in with your company email to run up to "
        f"{free_catalog_parts()} parts free, or talk to us about a pilot.",
        cap=0,
    )


def phone_required() -> HTTPException:
    return _problem(403, "phone_verification_required",
                    "Verify your phone number to start your free catalog run. We send one text with a code.")


async def require_catalog_access(user: AuthedUser = Depends(require_api_key)) -> CatalogAccess:
    """Who may start a catalog run: pilot (unlimited) or a work-email account (the free allowance)."""
    try:
        async with get_session_factory()() as session:
            access = await _access(session, user.user_id)
    except SQLAlchemyError as exc:
        raise _unavailable() from exc
    if access.cap is None:
        return access
    if access.tier != "work":
        raise work_email_required()
    if access.phone_required:
        raise phone_required()
    return access


async def active_free_run(session: AsyncSession, user_id: int, *, exclude_batch_id: int | None = None) -> str | None:
    """The ulid of the account's free catalog run that hasn't finished, if any."""
    q = select(Batch.ulid).where(
        Batch.user_id == user_id,
        Batch.job_type == "catalog",
        Batch.status.not_in(_TERMINAL_BATCH),
        Batch.manifest_json["catalog"]["free"].astext == "true",
    )
    if exclude_batch_id is not None:
        q = q.where(Batch.id != exclude_batch_id)
    row = (await session.execute(q.order_by(Batch.id.desc()).limit(1))).first()
    return row[0] if row else None


def run_active(batch_ulid: str) -> HTTPException:
    return _problem(
        409, "catalog_run_active",
        "Your free catalog run is still going. Open it to follow it; start the next one when it finishes.",
        batch_id=batch_ulid,
    )


@dataclass(frozen=True)
class Reservation:
    new: int  # parts that took a slot
    reruns: int  # parts already counted or checked: free
    used: int  # counted slots before this run
    reserved: int  # slots held by runs still going, this one included
    cap: int
    remaining: int


def _exceeded(cap: int, used: int, reserved: int, new: int, reruns: int) -> HTTPException:
    left = max(0, cap - used - reserved)
    if left == 0:
        message = (f"Your {cap} free catalog parts are used. Parts you've already run stay open, "
                   "and re-running them is free. Talk to us about a pilot to run more.")
    else:
        message = (f"This set has {new} parts not run before, and your free catalog run has {left} left. "
                   f"Remove {new - left} or talk to us about a pilot.")
    return _problem(
        403, "catalog_allowance_exceeded", message,
        cap=cap, used=used, reserved=reserved, remaining=left, needed=new, reruns=reruns,
    )


async def reserve_catalog_parts(
    session: AsyncSession,
    user_id: int,
    batch_id: int,
    items: Sequence[tuple[int, str]],
    *,
    access: CatalogAccess,
    exclude_batch_id: int | None = None,
) -> Reservation:
    """Reserve one slot per new distinct part, inside the caller's transaction.

    ``items`` is ``(batch_item_id, file_identity)`` for every item that will
    run. Locks the account row first, so concurrent runs serialize here; the
    caller commits (or rolls back) the reservation together with the batch.
    Raises 403 ``catalog_allowance_exceeded`` when the new parts don't fit,
    and 409 ``catalog_run_active`` while another free run of the account is
    still going (checked under the same lock, so two runs can't both start).
    """
    if access.cap is None:
        return Reservation(new=0, reruns=len(items), used=0, reserved=0, cap=0, remaining=0)
    locked = await _access(session, user_id, lock=True)
    if locked.cap is None:
        return Reservation(new=0, reruns=len(items), used=0, reserved=0, cap=0, remaining=0)
    if locked.tier != "work":
        raise work_email_required()
    other = await active_free_run(session, user_id, exclude_batch_id=exclude_batch_id)
    if other is not None:
        raise run_active(other)
    hashes = list(dict.fromkeys(h for _item, h in items))
    held = set()
    if hashes:
        held = set((await session.execute(
            select(CatalogPart.file_hash).where(
                CatalogPart.user_id == user_id,
                CatalogPart.file_hash.in_(hashes),
                _live_part(),
            )
        )).scalars().all())
        held |= set((await session.execute(
            select(TrialCheck.file_hash).where(
                TrialCheck.user_id == user_id,
                TrialCheck.completed.is_(True),
                TrialCheck.file_hash.in_(hashes),
            ).distinct()
        )).scalars().all())
    first_item: dict[str, int] = {}
    for item_id, h in items:
        first_item.setdefault(h, item_id)
    new = [h for h in hashes if h not in held]
    reruns = len(items) - len(new)
    counted, reserved = await _used(session, user_id)
    if new and locked.phone_required:
        raise phone_required()
    if counted + reserved + len(new) > locked.cap:
        raise _exceeded(locked.cap, counted, reserved, len(new), reruns)
    now = datetime.now(timezone.utc)
    for h in new:
        # A row left by a failed or skipped item is taken over; a live one was
        # excluded above, so this never moves a slot another run holds.
        stmt = pg_insert(CatalogPart).values(
            user_id=user_id, file_hash=h, batch_id=batch_id, batch_item_id=first_item[h],
            state="reserved", created_at=now, updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[CatalogPart.user_id, CatalogPart.file_hash],
            set_={"batch_id": batch_id, "batch_item_id": first_item[h], "state": "reserved",
                  "created_at": now, "updated_at": now},
            where=CatalogPart.state == "reserved",
        )
        await session.execute(stmt)
    reserved += len(new)
    return Reservation(new=len(new), reruns=reruns, used=counted, reserved=reserved,
                       cap=locked.cap, remaining=max(0, locked.cap - counted - reserved))


async def count_completed_part(
    session: AsyncSession,
    user_id: int,
    batch_id: int,
    batch_item_id: int,
    file_hash: str,
) -> None:
    """Keep the slot of a part whose item completed, in the item's own transaction.

    The part's row becomes ``counted`` (taking over a reservation another run
    still holds, so cancelling that run can't free a part that was checked
    here). A part with no row that the account already checked on its own
    stays free; any other completed part gets a counted row.
    """
    has_row = (await session.execute(
        select(CatalogPart.state).where(CatalogPart.user_id == user_id, CatalogPart.file_hash == file_hash)
    )).first()
    if has_row is None:
        single = (await session.execute(
            select(TrialCheck.check_id).where(
                TrialCheck.user_id == user_id,
                TrialCheck.completed.is_(True),
                TrialCheck.file_hash == file_hash,
            ).limit(1)
        )).first()
        if single is not None:
            return
    now = datetime.now(timezone.utc)
    stmt = pg_insert(CatalogPart).values(
        user_id=user_id, file_hash=file_hash, batch_id=batch_id, batch_item_id=batch_item_id,
        state="counted", created_at=now, updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[CatalogPart.user_id, CatalogPart.file_hash],
        set_={"batch_id": batch_id, "batch_item_id": batch_item_id, "state": "counted", "updated_at": now},
        where=CatalogPart.state == "reserved",
    )
    await session.execute(stmt)


def counted_catalog_hashes(user_id: int, hashes: Iterable[str] | None = None):
    """SELECT of the account's counted catalog-part hashes (for single-check accounting)."""
    q = select(CatalogPart.file_hash).where(
        and_(CatalogPart.user_id == user_id, CatalogPart.state == "counted")
    )
    if hashes is not None:
        q = q.where(CatalogPart.file_hash.in_(list(hashes)))
    return q
