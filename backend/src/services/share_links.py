"""Share-link lifecycle: how long a link lasts, whether it is on, who may end it.

A share link is a public, read-only view of one check (``analyses``), one
cost record (``cost_decisions``) or one RFQ package (``rfq_packages``),
addressed by a random short id on the row. Product decisions (2026-10-21,
2026-10-22):

* A link ends 7 days after it is made unless the sharer picks 1, 30 or 90
  days or a date of their own (``expires_on``, at most a year ahead). The API
  still takes a year (365) and an explicit ``null`` (no end date) from callers
  made before; the Share dialog offers neither.
* A record's link is what a buyer sends a supplier: it shows the part, its
  specs, the buyer's note and quantity, the CAD only when the sharer ticks
  it, and our cost estimate only when the sharer turns it on
  (``share_options``; ``src.services.supplier_links``).
* The person who made the link, or an org admin, can switch it off at any time.
  A link made before ``share_created_by`` existed falls back to the record's
  owner (plus admins).
* Links that existed before end dates were added were given one 30 days after
  the release (migration 0053); ``share_created_at IS NULL`` marks them so the
  product can say so.

A switched-off or ended link keeps its short id, so the public page can say
"switched off" or "expired" (HTTP 410, no record data) instead of "not found".
Making a new link for the same record mints a new short id; the old one is
then simply unknown (404).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal, Optional, Union

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Analysis, CostDecision, Membership, RfqPackage

DEFAULT_DAYS = 7
# 1, 7, 30 and 90 days are the Share dialog's; a year stays for API callers made before.
EXPIRY_CHOICES = (1, 7, 30, 90, 365)
DIALOG_CHOICES = (1, 7, 30, 90)
MAX_DAYS_AHEAD = 366

ShareRow = Union[Analysis, CostDecision, RfqPackage]
Status = Literal["active", "expired", "off"]


class ShareOptions(BaseModel):
    """Body of ``POST .../share``. Omitted body or field: 7 days, no cost, no CAD.

    ``expires_on`` (a date, the link works through that day, UTC) wins over
    ``expires_in_days``. ``expires_in_days: null`` is the explicit "no end
    date" choice, kept for API callers made before the Share dialog.
    ``include_cost`` / ``include_cad`` / ``note`` / ``quantity`` are what a
    record's link shows its supplier (``src.services.supplier_links``).
    """

    expires_in_days: Optional[int] = DEFAULT_DAYS
    expires_on: Optional[date] = None
    include_cost: bool = False
    include_cad: bool = False
    note: Optional[str] = Field(default=None, max_length=2000)
    quantity: Optional[int] = Field(default=None, ge=1, le=10_000_000)

    @field_validator("expires_in_days")
    @classmethod
    def _allowed(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value not in EXPIRY_CHOICES:
            raise ValueError("expires_in_days must be 1, 7, 30, 90 or 365 (or a date in expires_on)")
        return value

    @model_validator(mode="after")
    def _date_ahead(self) -> "ShareOptions":
        if self.expires_on is not None:
            today = now_utc().date()
            if self.expires_on < today:
                raise ValueError("The end date has passed. Pick today or a later day.")
            if self.expires_on > today + timedelta(days=MAX_DAYS_AHEAD - 1):
                raise ValueError("A link lasts a year at most. Pick an earlier day.")
        return self

    def ends_at(self, now: Optional[datetime] = None) -> Optional[datetime]:
        """When the link stops working; None is no end date."""
        if self.expires_on is not None:
            return datetime.combine(self.expires_on, time(23, 59, 59), tzinfo=timezone.utc)
        if self.expires_in_days is None:
            return None
        return (now or now_utc()) + timedelta(days=self.expires_in_days)

    def shown(self) -> dict[str, Any]:
        """What the link shows, as it is saved on the row (``share_options``)."""
        note = (self.note or "").strip() or None
        return {"include_cost": bool(self.include_cost), "include_cad": bool(self.include_cad),
                "note": note, "quantity": self.quantity}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    value = _aware(value)
    return value.isoformat() if value else None


def status(row: ShareRow, now: Optional[datetime] = None) -> Optional[Status]:
    """``active`` / ``expired`` / ``off``, or None when the record has no link."""
    if not row.share_short_id:
        return None
    if row.share_revoked_at is not None or not row.is_public:
        return "off"
    expires = _aware(row.share_expires_at)
    if expires is not None and expires <= (now or now_utc()):
        return "expired"
    return "active"


def ended_at(row: ShareRow) -> Optional[datetime]:
    st = status(row)
    if st == "off":
        return _aware(row.share_revoked_at)
    if st == "expired":
        return _aware(row.share_expires_at)
    return None


def url_for(row: ShareRow) -> Optional[str]:
    if not row.share_short_id:
        return None
    prefix = "/s/cost/" if isinstance(row, CostDecision) else "/s/pkg/" if isinstance(row, RfqPackage) else "/s/"
    return f"{prefix}{row.share_short_id}"


def fields(row: ShareRow) -> dict[str, Any]:
    """The link fields every record serialization carries.

    ``is_public`` means "the link works right now" (an ended link is not
    public any more even though its row still says so).
    """
    st = status(row)
    return {
        "is_public": st == "active",
        "share_url": url_for(row) if st == "active" else None,
        "share_status": st,
        "share_expires_at": _iso(row.share_expires_at) if row.share_short_id else None,
        "share_created_at": _iso(row.share_created_at) if row.share_short_id else None,
        "share_ended_at": _iso(ended_at(row)),
        # Made before links had an end date; it was given one at the release.
        "share_end_date_added": bool(row.share_short_id) and row.share_created_at is None,
        # What the link shows (a record's or a package's link); None for a check's.
        **({"share_shows": getattr(row, "share_options", None) if row.share_short_id else None}
           if hasattr(row, "share_options") else {}),
    }


def open_link(row: ShareRow, user_id: int, days: Optional[int], short_id: str, *,
              ends_at: Optional[datetime] = None, shows: Optional[dict] = None) -> None:
    """Start a new link on ``row`` (a new short id; any old one stops resolving).

    ``ends_at`` (a chosen date) wins over ``days``; ``shows`` is what a record's
    or package's link shows (``ShareOptions.shown``).
    """
    now = now_utc()
    row.share_short_id = short_id
    row.is_public = True
    row.share_created_at = now
    row.share_created_by = user_id
    row.share_expires_at = ends_at if ends_at is not None else (
        now + timedelta(days=days) if days is not None else None)
    row.share_revoked_at = None
    if hasattr(row, "share_options"):
        row.share_options = shows


def close_link(row: ShareRow) -> None:
    """Switch the link off. The short id stays so the public page can say so."""
    row.is_public = False
    row.share_revoked_at = now_utc()


async def org_role(session: AsyncSession, org_id: str, user_id: int) -> Optional[str]:
    return (
        await session.execute(
            select(Membership.org_role).where(
                Membership.org_id == org_id, Membership.user_id == user_id
            )
        )
    ).scalar_one_or_none()


def made_by(row: ShareRow) -> Optional[int]:
    """Who made the link: the recorded sharer, else (older links) the record's owner."""
    return row.share_created_by if row.share_created_by is not None else row.user_id


async def can_switch_off(session: AsyncSession, row: ShareRow, user_id: int) -> bool:
    if made_by(row) == user_id:
        return True
    return await org_role(session, row.org_id, user_id) == "admin"


async def require_can_switch_off(session: AsyncSession, row: ShareRow, user_id: int) -> None:
    if not await can_switch_off(session, row, user_id):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "share_not_yours",
                "message": "Only the person who made this link, or an admin, can switch it off.",
            },
        )


def public_or_raise(row: Optional[ShareRow], not_found: str) -> ShareRow:
    """The row behind a public link, or 404 (unknown) / 410 (ended or switched off).

    The 410 bodies carry no record data: only which way the link ended and when.
    """
    if row is None or not row.share_short_id:
        raise HTTPException(status_code=404, detail=not_found)
    st = status(row)
    if st == "active":
        return row
    when = _iso(ended_at(row))
    if st == "expired":
        raise HTTPException(
            status_code=410,
            detail={"code": "share_expired", "message": "This link has expired.", "ended_at": when},
        )
    raise HTTPException(
        status_code=410,
        detail={"code": "share_switched_off", "message": "This link was switched off.", "ended_at": when},
    )


def public_meta(row: ShareRow) -> dict[str, Any]:
    """What a visitor of a working link is told about the link itself."""
    return {"link_expires_at": _iso(row.share_expires_at)}


async def list_links(
    session: AsyncSession,
    org_id: str,
    user_id: int,
    *,
    everyone: bool,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """The links in ``org_id``: the caller's own, or (``everyone``) all of them.

    Newest first; links made before end dates (no ``share_created_at``) last.
    """
    from src.db.models import User

    out: list[dict[str, Any]] = []
    admin = await org_role(session, org_id, user_id) == "admin"
    for model, kind in ((Analysis, "check"), (CostDecision, "record"), (RfqPackage, "package")):
        stmt = select(model).where(model.org_id == org_id, model.share_short_id.is_not(None))
        if not everyone:
            stmt = stmt.where(
                (model.share_created_by == user_id)
                | (model.share_created_by.is_(None) & (model.user_id == user_id))
            )
        rows = (
            await session.execute(
                stmt.order_by(model.share_created_at.desc().nulls_last(), model.id.desc()).limit(limit)
            )
        ).scalars().all()
        for row in rows:
            name = row.title if isinstance(row, RfqPackage) else row.filename
            if isinstance(row, CostDecision) and row.label:
                name = row.label
            out.append(
                {
                    "kind": kind,
                    "id": row.ulid,
                    "part_key": getattr(row, "mesh_hash", None),
                    "shows": getattr(row, "share_options", None),
                    "name": name,
                    "url": url_for(row),
                    "status": status(row),
                    "created_at": _iso(row.share_created_at),
                    "expires_at": _iso(row.share_expires_at),
                    "ended_at": _iso(ended_at(row)),
                    "end_date_added": row.share_created_at is None,
                    "made_by_user_id": made_by(row),
                    "mine": made_by(row) == user_id,
                    "can_switch_off": status(row) == "active" and (made_by(row) == user_id or admin),
                }
            )
    ids = {item["made_by_user_id"] for item in out if item["made_by_user_id"] is not None}
    names: dict[int, str] = {}
    if ids:
        from src.services.person_label import person_label

        for uid, full_name, email in (
            await session.execute(select(User.id, User.full_name, User.email).where(User.id.in_(ids)))
        ).all():
            names[int(uid)] = person_label(full_name, email) or email
    for item in out:
        uid = item.pop("made_by_user_id")
        item["made_by"] = names.get(uid) if uid is not None else None
    far = "9999"
    out.sort(key=lambda item: (item["created_at"] is not None, item["created_at"] or far), reverse=True)
    return out[: limit * 2]
