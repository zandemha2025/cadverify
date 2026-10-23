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
    "service_environment",
    # BOM-rollup linkage (Slice 3): ties this part to a persisted bom_edges tree so
    # its annual volume rolls up from the real hierarchy instead of the flat
    # ``annual_volume``. All optional — unset → the flat declared path, byte-identical.
    "bom_assembly_key",
    "bom_child_ref",
    "bom_roots_per_year",
    # Declared part specs (migration 0056; ``src.costing.part_specs``): surface
    # finish + Ra, heat treatment, inspection, required certifications. Stored
    # normalized; NULL / absent → nothing declared, the engine is a no-op.
    "part_specs",
    # What the org pays today to buy the part (migration 0059;
    # ``normalize_buy_price``). Not an engine input: it moves the part between
    # make and buy and sets the saving, never the engine's figures.
    "buy_price",
)
_POSITIVE_INT_FIELDS = ("units_per_parent", "annual_volume", "bom_roots_per_year")

# Declared service-environment schema (machine-inventory §6). Every key is
# USER-declared, never inferred from the mesh. Numeric temps/pressure, boolean
# corrosive/sour flags, free-text medium/standard. Unknown keys are REJECTED so a
# typo'd field can't silently vanish.
_ENV_NUMBER_FIELDS = ("max_temp_c", "min_temp_c", "pressure_bar")
_ENV_BOOL_FIELDS = ("corrosive", "sour_service")
_ENV_STR_FIELDS = ("medium", "standard")
_ENV_FIELDS = frozenset(_ENV_NUMBER_FIELDS + _ENV_BOOL_FIELDS + _ENV_STR_FIELDS)


def validate_service_environment(env) -> None:
    """Raise ``ValueError`` unless ``env`` is a valid declared service environment.

    ``{max_temp_c, min_temp_c, pressure_bar}`` numeric; ``{corrosive,
    sour_service}`` bool; ``{medium, standard}`` string. ``pressure_bar`` must be
    >= 0. Unknown keys are rejected (never silently ignored). ``None`` / absent is
    allowed — the environment is entirely optional (gate is a no-op when unset).
    """
    if env is None:
        return
    if not isinstance(env, dict):
        raise ValueError("service_environment must be a JSON object")
    errors: list[str] = []
    for key, val in env.items():
        if key not in _ENV_FIELDS:
            errors.append(f"unknown service_environment field '{key}'")
            continue
        if val is None:
            continue
        if key in _ENV_NUMBER_FIELDS:
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                errors.append(f"{key} must be a number")
            elif key == "pressure_bar" and val < 0:
                errors.append("pressure_bar must be >= 0")
        elif key in _ENV_BOOL_FIELDS:
            if not isinstance(val, bool):
                errors.append(f"{key} must be a boolean")
        elif key in _ENV_STR_FIELDS:
            if not isinstance(val, str):
                errors.append(f"{key} must be a string")
    if errors:
        raise ValueError("; ".join(errors))


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
        if val > 2_147_483_647:
            raise ValueError(f"{key} must be at most 2147483647")
    # The declared service environment (machine-inventory §6) — USER-declared,
    # never inferred. Validated when present; absent → the gate is a no-op.
    validate_service_environment(fields.get("service_environment"))
    # Declared part specs: unknown fields/values are rejected (never dropped).
    from src.costing.part_specs import validate_part_specs

    validate_part_specs(fields.get("part_specs"))
    if fields.get("buy_price") is not None:
        normalize_buy_price(fields["buy_price"], source="you")


BUY_PRICE_SOURCES = ("you", "parts_list")
MAX_BUY_PRICE_USD = 10_000_000


def normalize_buy_price(value, *, source: str, run_id: Optional[str] = None) -> Optional[dict]:
    """A current buy price as stored: ``{usd_each, per, price_usd, source, run_id, updated_at}``.

    ``value``: ``{"usd_each": 12.4}`` or ``{"price_usd": 1250, "per": 100}``
    (what it costs per ``per`` parts). ``source`` says who gave it: "you" (typed
    on the part's Decision view) or "parts_list" (a catalog run's list). None or
    ``{}`` clears it. Raises ``ValueError`` for anything else.
    """
    from datetime import datetime, timezone

    if value is None or value == {}:
        return None
    if not isinstance(value, dict):
        raise ValueError("buy_price must be an object like {\"usd_each\": 12.4}")
    unknown = set(value) - {"usd_each", "price_usd", "per", "source", "run_id", "updated_at"}
    if unknown:
        raise ValueError(f"buy_price has unknown fields: {', '.join(sorted(unknown))}")
    per = value.get("per", 1)
    if per is None:
        per = 1
    if not isinstance(per, int) or isinstance(per, bool) or not (1 <= per <= 10_000_000):
        raise ValueError("buy_price.per must be a whole number of parts from 1 to 10,000,000")
    price = value.get("price_usd")
    each = value.get("usd_each")
    for name, v in (("price_usd", price), ("usd_each", each)):
        if v is not None and (not isinstance(v, (int, float)) or isinstance(v, bool)
                              or not (0 < float(v) <= MAX_BUY_PRICE_USD)):
            raise ValueError(f"buy_price.{name} must be more than $0 and at most ${MAX_BUY_PRICE_USD:,}")
    if price is None:
        if each is None:
            raise ValueError("buy_price needs usd_each or price_usd")
        price = float(each) * per
    usd_each = round(float(price) / per, 6)
    if source not in BUY_PRICE_SOURCES:
        raise ValueError(f"buy_price source must be one of {BUY_PRICE_SOURCES}")
    return {"usd_each": usd_each, "price_usd": round(float(price), 4), "per": per, "source": source,
            "run_id": run_id, "updated_at": datetime.now(timezone.utc).isoformat()}


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
    On insert, all declared fields are written from the body. On update, only
    fields actually present in the request are changed, so a Verify-world refresh
    cannot erase separately declared lineage/demand context by omission.
    An empty ``service_environment`` (``{}``) declares nothing, so it never
    overwrites a stored non-empty environment; clearing one takes an explicit
    ``null``, like every other declared field.
    ``created_by`` is stamped on insert.
    """
    validate_context(fields)
    if "buy_price" in fields and not (isinstance(fields["buy_price"], dict) and fields["buy_price"].get("source")
                                      in BUY_PRICE_SOURCES and fields["buy_price"].get("updated_at")):
        # A price typed through the API is "you"; the catalog run stores its own, already normalized.
        fields = {**fields, "buy_price": normalize_buy_price(fields.get("buy_price"), source="you")}
    if "part_specs" in fields:
        from src.costing.part_specs import normalize_part_specs

        fields = {**fields, "part_specs": normalize_part_specs(fields.get("part_specs"))}
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
            if key not in fields:
                continue
            if (
                key == "service_environment"
                and fields[key] == {}
                and row.service_environment
            ):
                continue
            setattr(row, key, fields.get(key))
    await session.flush()
    return row


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def serialize_context(row: Any) -> dict:
    """Serialize a context row. ``provenance`` is always ``"user"`` — a declared
    context is a user assertion, never an inferred/measured fact."""
    out = {
        "mesh_hash": row.mesh_hash,
        "program": row.program,
        "parent_assembly": row.parent_assembly,
        "units_per_parent": row.units_per_parent,
        "annual_volume": row.annual_volume,
        # Honesty: this context is DECLARED by a user, never inferred.
        "provenance": "user",
    }
    # The declared service environment (machine-inventory §6) is surfaced ONLY
    # when actually declared — a context with no environment stays byte-identical
    # to the pre-feature shape (honesty invariant: no declaration → no-op).
    env = getattr(row, "service_environment", None)
    if env is not None:
        out["service_environment"] = env
    # The BOM-rollup linkage (Slice 3) is surfaced ONLY when actually declared — a
    # context with no linkage stays byte-identical to the pre-Slice-3 shape.
    for key in ("bom_assembly_key", "bom_child_ref", "bom_roots_per_year"):
        val = getattr(row, key, None)
        if val is not None:
            out[key] = val
    # Declared part specs: surfaced ONLY when declared (byte-identical otherwise).
    specs = getattr(row, "part_specs", None)
    if specs:
        out["part_specs"] = specs
    # The current buy price: surfaced ONLY when declared (typed or from a parts list).
    price = getattr(row, "buy_price", None)
    if price:
        out["buy_price"] = price
    return out


# What a check's verdict depends on, from the declared context: a change to
# either makes earlier saved decisions for the part out of date.
ENGINE_INPUT_FIELDS = (("part_specs", "part_specs_changed"),
                       ("service_environment", "conditions_changed"))


def engine_inputs(row: Any) -> dict:
    """The declared values the cost engine reads, for a before/after comparison.
    A spec the price doesn't use (the general tolerance) isn't one of them."""
    from src.costing.part_specs import NOT_PRICED_FIELDS

    if row is None:
        return {k: None for k, _ in ENGINE_INPUT_FIELDS}
    out = {k: (getattr(row, k, None) or None) for k, _ in ENGINE_INPUT_FIELDS}
    specs = out.get("part_specs")
    if isinstance(specs, dict):
        out["part_specs"] = {k: v for k, v in specs.items() if k not in NOT_PRICED_FIELDS} or None
    return out


def changed_input_reasons(before: dict, after: dict) -> list:
    """Stale reasons for the engine inputs that changed (in a stable order)."""
    return [reason for key, reason in ENGINE_INPUT_FIELDS if (before or {}).get(key) != (after or {}).get(key)]


async def search_index(session: AsyncSession, org_id: str, limit: int = 300) -> dict:
    """The organization's parts with what they are found by (buyer-06, buyer-16): the file
    name, the program and the declared specs in words ("Finish: Anodize, Type II, Ra 1.6 µm",
    "Supplier must hold: AS9100", "General tolerance: ±0.1 mm"). Newest parts first; every
    part with declared specs is in it. Read-only, org-scoped."""
    from sqlalchemy import desc

    from src.costing.part_specs import normalize_part_specs, spec_summary
    from src.db.models import PartSummary

    rows = (await session.execute(
        select(PartSummary.mesh_hash, PartSummary.row_json)
        .where(PartSummary.org_id == org_id)
        .order_by(desc(PartSummary.updated_at)).limit(limit + 1)
    )).all()
    truncated = len(rows) > limit
    names = {mh: (rj or {}).get("filename") for mh, rj in rows[:limit]}
    contexts = {c.mesh_hash: c for c in await list_contexts(session, org_id)}
    with_specs = [mh for mh, c in contexts.items() if getattr(c, "part_specs", None) and mh not in names]
    if with_specs:
        extra = (await session.execute(
            select(PartSummary.mesh_hash, PartSummary.row_json)
            .where(PartSummary.org_id == org_id, PartSummary.mesh_hash.in_(with_specs))
        )).all()
        found = {mh: (rj or {}).get("filename") for mh, rj in extra}
        for mh in with_specs:
            names[mh] = found.get(mh)
    parts = []
    for mh, filename in names.items():
        ctx = contexts.get(mh)
        try:
            specs = normalize_part_specs(getattr(ctx, "part_specs", None)) if ctx is not None else None
        except ValueError:
            specs = None
        parts.append({
            "mesh_hash": mh,
            "filename": filename,
            "program": getattr(ctx, "program", None) if ctx is not None else None,
            "specs": spec_summary(specs) if specs else [],
        })
    return {"parts": parts, "truncated": truncated}
