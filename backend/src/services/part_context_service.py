"""Declared part-context service (W3.5 rung-1).

Gives every catalog part an optional, USER-DECLARED business context — which
program it belongs to, its parent assembly, units-per-parent, and the annual
build volume — so the portfolio roll-up can state an honest ``$/year`` instead
of only a per-unit price. One row per ``(org_id, mesh_hash)``.

Design mirrors the repo's convention (see ``rate_library_service``): the real
logic lives in PURE functions (``validate_context``, ``annualized_cost``,
``serialize_context``) that are unit-tested without a DB; the SQLAlchemy
adapters below are thin and org-scoped.

HONESTY (non-negotiable): every field is DECLARED by the user — provenance is
always ``"user"``, never inferred or guessed from the mesh. An annualized figure
is only ever produced when the user has actually declared an ``annual_volume``:
``annualized_cost`` returns ``None`` (never a fabricated demand quantity) when
volume is absent. A part with no context row behaves exactly as before — nothing
here flips a cost band to ``validated``.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import PartContext

logger = logging.getLogger("cadverify.part_context_service")

# The user-declarable fields (all optional). Kept as a tuple so validators,
# adapters, and serialization never drift on the field set.
DECLARED_FIELDS = (
    "program",
    "parent_assembly",
    "units_per_parent",
    "annual_volume",
)
_POSITIVE_INT_FIELDS = ("units_per_parent", "annual_volume")


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested without a DB)
# ---------------------------------------------------------------------------


def validate_context(fields: dict) -> None:
    """Raise ``ValueError`` if a declared quantity is present and non-positive.

    ``units_per_parent`` and ``annual_volume`` are physical counts — a value
    ``<= 0`` is nonsense (you cannot build 0 or -5 of a part per year), so we
    reject it rather than silently store a figure that would poison the honest
    ``$/year`` math. Strings (``program``, ``parent_assembly``) and absent /
    ``None`` values pass through untouched — the context is entirely optional.
    """
    for key in _POSITIVE_INT_FIELDS:
        val = fields.get(key)
        if val is None:
            continue
        if not isinstance(val, int) or isinstance(val, bool):
            raise ValueError(f"{key} must be an integer, got {val!r}")
        if val <= 0:
            raise ValueError(f"{key} must be positive (> 0), got {val}")


def annualized_cost(
    unit_cost: Optional[float], annual_volume: Optional[int]
) -> Optional[float]:
    """Honest annualized cost: ``unit_cost * annual_volume``, or ``None``.

    Returns ``None`` whenever ``annual_volume`` is not declared — we NEVER
    fabricate a demand quantity to manufacture a $/year figure. Also ``None``
    when there is no unit cost to annualize (e.g. a DFM-withheld price). Only
    when BOTH are real does this return a number.
    """
    if annual_volume is None or unit_cost is None:
        return None
    return float(unit_cost) * annual_volume


# ---------------------------------------------------------------------------
# DB adapters (thin; org-scoped; the router owns auth)
# ---------------------------------------------------------------------------


async def get_context(
    session: AsyncSession, org_id: str, mesh_hash: str
) -> Optional[PartContext]:
    """The single declared context for a part in an org, or ``None``."""
    return (
        await session.execute(
            select(PartContext).where(
                PartContext.org_id == org_id,
                PartContext.mesh_hash == mesh_hash,
            )
        )
    ).scalars().first()


async def list_contexts(session: AsyncSession, org_id: str) -> list:
    """Every declared context for the caller's org (used by the portfolio join)."""
    return list(
        (
            await session.execute(
                select(PartContext).where(PartContext.org_id == org_id)
            )
        )
        .scalars()
        .all()
    )


async def upsert_context(
    session: AsyncSession,
    org_id: str,
    mesh_hash: str,
    fields: dict,
    created_by: Optional[int] = None,
) -> PartContext:
    """Insert or update THE single ``(org_id, mesh_hash)`` context row.

    Org-scoped: only ever touches the caller-org's row for this mesh. Validates
    the declared quantities first (``ValueError`` on a non-positive count). Only
    the four declared fields are written; ``created_by`` is stamped on insert.
    """
    validate_context(fields)
    row = await get_context(session, org_id, mesh_hash)
    if row is None:
        row = PartContext(
            org_id=org_id,
            mesh_hash=mesh_hash,
            created_by=created_by,
        )
        for key in DECLARED_FIELDS:
            setattr(row, key, fields.get(key))
        session.add(row)
    else:
        for key in DECLARED_FIELDS:
            setattr(row, key, fields.get(key))
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_context(row: Any) -> dict:
    """Serialize a context row. ``provenance`` is always ``"user"`` — a declared
    context is a user assertion, never an inferred/measured fact."""
    return {
        "mesh_hash": row.mesh_hash,
        "program": row.program,
        "parent_assembly": row.parent_assembly,
        "units_per_parent": row.units_per_parent,
        "annual_volume": row.annual_volume,
        # Honesty: this context is DECLARED by a user, never inferred.
        "provenance": "user",
    }
