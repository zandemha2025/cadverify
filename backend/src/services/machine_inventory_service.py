"""Machine-inventory service — org-owned machine capability registry (spec §3–§4).

The data/CRUD half of the verification-thesis crux: an org declares the machines
it OWNS with real capability fields, so a later pure matcher (Phase B,
``src.costing.makeability``) can answer "can this part be made, on WHICH of THEIR
machines, or exactly what machine spec would close the gap." This module is the
deliberate sibling of the shipped governed-library services
(``manifest_service`` for the CSV/keyset/error discipline, ``rate_library_service``
for the pure-validation-then-thin-adapter shape).

HONESTY RAILS (non-negotiable, spec §2):
  * Capabilities are USER-declared → provenance ``"user"``, NEVER measured. A
    machine's envelope/rate/material qualification is the org's declaration.
  * Malformed inputs are REPORTED (per-field / per-line), never coerced. A bad
    process, a negative scalar, a non-integer IT grade, an unknown material, or a
    ``capital_frac`` outside [0,1] is a reported error, not a silently-fixed value.
  * No inventory declared → the platform is byte-identical (this is purely
    additive). ``load_org_inventory`` returns ``[]`` for an empty/absent org.
  * Org-scoped throughout: every query filters by ``org_id`` — one org's machines
    never leak into another's list, hydration, or shop-capabilities.

The pure ``MachineCap`` / ``ShopCaps`` capability types are the LOCKED Phase-B
contract; the real definitions live in ``src.costing.makeability`` (written in
parallel). Until that module lands here we fall back to local dataclasses of the
EXACT same shape so this phase is self-contained and testable; the orchestrator
reconciles the two at integration.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.analysis.models import ProcessType
from src.db.models import MachineInstance, ShopCapabilities
from src.profiles.database import MACHINES, get_material_by_name
# Reuse the EXACT material-class vocabulary the ground-truth / manifest importers
# validate against — a machine can never smuggle in a material the cost engine
# would later reject.
from src.services.groundtruth_service import KNOWN_MATERIAL_CLASSES

logger = logging.getLogger("cadverify.machine_inventory")


# ── LOCKED Phase-B capability types (real import is src.costing.makeability) ──
try:  # pragma: no cover - exercised at integration when makeability.py lands
    from src.costing.makeability import MachineCap, ShopCaps  # type: ignore
except Exception:  # noqa: BLE001 - module not written yet in this worktree

    @dataclass(frozen=True)
    class MachineCap:  # type: ignore[no-redef]
        """DB-free capability view of one owned machine (Phase-B contract).

        Field set + order is the LOCKED contract shared with
        ``src.costing.makeability``. Keep in exact sync.
        """

        process: str
        name: Optional[str]
        count: int
        max_workpiece_kg: Optional[float]
        hourly_rate_usd: Optional[float]
        capital_frac: Optional[float]
        materials: tuple = ()
        material_thickness_map: dict = field(default_factory=dict)
        capabilities: dict = field(default_factory=dict)

    @dataclass(frozen=True)
    class ShopCaps:  # type: ignore[no-redef]
        """DB-free view of an org's shop-level secondary-op set (Phase-B contract)."""

        ops: dict = field(default_factory=dict)


# ── valid process set (ProcessType.value) ────────────────────────────────────
_VALID_PROCESSES = frozenset(p.value for p in ProcessType)

# ── capability-field schema (per gate type; all USER-declared) ────────────────
# scalar kinds
_POS = "pos"        # a number strictly > 0
_NONNEG = "nonneg"  # a number >= 0
_BOOL = "bool"
_STR = "str"        # a non-empty string

# key -> scalar kind. Special-cased keys (IT grade / axes / enums) are handled
# separately in ``_validate_capabilities`` so their precise messages are clean.
_CAP_SPEC: dict[str, str] = {
    # Envelope (mm, > 0) — mill/AM/EDM travels, sheet bed, turning swing/length,
    # casting flask, molding platen.
    "x": _POS, "y": _POS, "z": _POS,
    "bed_x": _POS, "bed_y": _POS,
    "swing_dia": _POS, "between_centers": _POS, "spindle_bore": _POS,
    "flask_x": _POS, "flask_y": _POS, "flask_z": _POS,
    "platen_x": _POS, "platen_y": _POS, "tie_bar_gap": _POS, "daylight": _POS,
    # Force / energy.
    "spindle_power_kw": _POS, "spindle_taper": _STR, "max_rpm": _POS,
    "laser_power_kw": _POS, "tonnage_t": _POS, "max_bend_length_mm": _POS,
    "clamp_tonnage_t": _POS, "shot_capacity_g": _POS, "max_injection_bar": _POS,
    "press_tonnage_t": _POS, "furnace_capacity_kg": _POS, "max_pour_kg": _POS,
    "max_cut_thickness_mm": _POS,
    # Reach / access.
    "min_tool_dia_mm": _POS, "max_tool_reach_ratio": _POS,
    "live_tooling": _BOOL, "y_axis": _BOOL, "sub_spindle": _BOOL, "bar_feed": _BOOL,
    # Resolution / precision.
    "positioning_accuracy_um": _POS, "repeatability_um": _POS,
    "surface_finish_ra_um": _POS, "min_layer_um": _POS, "min_wall_mm": _POS,
    "min_feature_mm": _POS, "max_taper_deg": _POS,
    # Material special gates.
    "conductive_required": _BOOL,
}
_MOTION_MODES = frozenset({"positional_3plus2", "simultaneous_5"})
_CHAMBER_TYPES = frozenset({"hot", "cold"})


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate_capabilities(caps: Any, errors: list[str]) -> None:
    """Validate the per-family ``capabilities`` dict; append precise errors.

    Every recognised key is type/sign-checked; an UNKNOWN key is a reported error
    (never silently ignored — a typo'd capability must not vanish). An empty dict
    is valid: a machine may legitimately declare only some gates (the missing
    ones read ``unknown`` downstream, never a fabricated pass).
    """
    if caps is None:
        return
    if not isinstance(caps, dict):
        errors.append("capabilities must be a JSON object")
        return
    for key, val in caps.items():
        if key == "achievable_it_grade":
            if isinstance(val, bool) or not isinstance(val, int):
                errors.append("achievable_it_grade must be an integer IT grade")
            elif not (0 <= val <= 18):
                errors.append("achievable_it_grade must be an IT grade in 0–18")
            continue
        if key == "axes":
            if isinstance(val, bool) or val not in (3, 4, 5):
                errors.append("axes must be one of 3, 4, 5")
            continue
        if key == "motion_mode":
            if val not in _MOTION_MODES:
                errors.append(
                    f"motion_mode must be one of {sorted(_MOTION_MODES)}"
                )
            continue
        if key == "chamber_type":
            if val not in _CHAMBER_TYPES:
                errors.append(
                    f"chamber_type must be one of {sorted(_CHAMBER_TYPES)}"
                )
            continue
        kind = _CAP_SPEC.get(key)
        if kind is None:
            errors.append(f"unknown capability '{key}'")
            continue
        if kind in (_POS, _NONNEG):
            if not _is_number(val):
                errors.append(f"capability '{key}' must be a number")
            elif kind == _POS and val <= 0:
                errors.append(f"capability '{key}' must be > 0 (got {val})")
            elif kind == _NONNEG and val < 0:
                errors.append(f"capability '{key}' must be >= 0 (got {val})")
        elif kind == _BOOL:
            if not isinstance(val, bool):
                errors.append(f"capability '{key}' must be a boolean")
        elif kind == _STR:
            if not isinstance(val, str) or not val.strip():
                errors.append(f"capability '{key}' must be a non-empty string")


def _validate_materials(materials: Any, errors: list[str]) -> None:
    """Each declared material must be a known material NAME or material CLASS."""
    if materials is None:
        return
    if not isinstance(materials, (list, tuple)):
        errors.append("materials must be a list")
        return
    for m in materials:
        if not isinstance(m, str) or not m.strip():
            errors.append(f"material entries must be non-empty strings (got {m!r})")
            continue
        name = m.strip()
        if name.lower() in KNOWN_MATERIAL_CLASSES:
            continue
        if get_material_by_name(name) is not None:
            continue
        errors.append(f"unknown material '{name}' (not a known material or class)")


def _validate_thickness_map(tmap: Any, errors: list[str]) -> None:
    if tmap is None:
        return
    if not isinstance(tmap, dict):
        errors.append("material_thickness_map must be a JSON object")
        return
    for k, v in tmap.items():
        if not isinstance(k, str) or not k.strip():
            errors.append("material_thickness_map keys must be material names")
        if not _is_number(v) or v <= 0:
            errors.append(
                f"material_thickness_map['{k}'] must be a positive number"
            )


def validate_machine(fields: dict) -> None:
    """Raise ``ValueError`` (message = all problems, ``; ``-joined) unless
    ``fields`` is a structurally-valid, engine-consumable machine declaration.

    Validates: ``process`` ∈ ProcessType; ``count`` a positive int;
    ``max_workpiece_kg`` > 0; ``hourly_rate_usd`` >= 0; ``capital_frac`` ∈ [0,1];
    each ``capabilities`` scalar positive / typed per gate; ``achievable_it_grade``
    an int IT grade; ``materials`` against the material DB / class vocabulary;
    ``material_thickness_map`` a {name: positive} map. Nothing is coerced — every
    violation is reported.
    """
    errors: list[str] = []

    process = fields.get("process")
    if not process or not isinstance(process, str):
        errors.append("process is required")
    elif process not in _VALID_PROCESSES:
        errors.append(f"unknown process '{process}'")

    count = fields.get("count")
    if count is not None:
        if isinstance(count, bool) or not isinstance(count, int):
            errors.append("count must be an integer")
        elif count <= 0:
            errors.append("count must be > 0")

    mwk = fields.get("max_workpiece_kg")
    if mwk is not None:
        if not _is_number(mwk) or mwk <= 0:
            errors.append("max_workpiece_kg must be a positive number")

    rate = fields.get("hourly_rate_usd")
    if rate is not None:
        if not _is_number(rate) or rate < 0:
            errors.append("hourly_rate_usd must be >= 0")

    cf = fields.get("capital_frac")
    if cf is not None:
        if not _is_number(cf) or not (0.0 <= cf <= 1.0):
            errors.append("capital_frac must be in [0,1]")

    _validate_capabilities(fields.get("capabilities"), errors)
    _validate_materials(fields.get("materials"), errors)
    _validate_thickness_map(fields.get("material_thickness_map"), errors)

    if errors:
        raise ValueError("; ".join(errors))


# ── mutable field set (write/serialize never drift) ──────────────────────────
_MUTABLE_FIELDS = (
    "name",
    "process",
    "count",
    "max_workpiece_kg",
    "hourly_rate_usd",
    "capital_frac",
    "capabilities",
    "materials",
    "material_thickness_map",
    "notes",
)


def _normalize(fields: dict) -> dict:
    """Apply the non-fabricating defaults: ``count`` → 1, ``capabilities`` → {}.

    Nothing else is invented; absent optional fields stay ``None``.
    """
    out = {k: fields.get(k) for k in _MUTABLE_FIELDS}
    if out.get("count") is None:
        out["count"] = 1
    if out.get("capabilities") is None:
        out["capabilities"] = {}
    return out


# ── CSV bulk-import contract (mirrors manifest_service.parse_manifest_csv) ────
MACHINE_REQUIRED_COLUMNS = ("process",)
MACHINE_OPTIONAL_COLUMNS = (
    "name",
    "count",
    "max_workpiece_kg",
    "hourly_rate_usd",
    "capital_frac",
    "materials",  # pipe-separated list, e.g. "Ti6Al4V|Inconel 718|steel"
    "material_thickness_map",  # JSON object
    "capabilities",  # JSON object of the per-family scalars
    "notes",
)
MACHINE_HEADER = ",".join(MACHINE_REQUIRED_COLUMNS + MACHINE_OPTIONAL_COLUMNS)
_FLOAT_COLUMNS = ("max_workpiece_kg", "hourly_rate_usd", "capital_frac")


def _example_row() -> str:
    """One illustrative data row for the /import/template body."""
    caps = json.dumps({"x": 762, "y": 406, "z": 508, "axes": 3,
                       "achievable_it_grade": 9})
    return (
        f'Haas VF-2 #1,cnc_3axis,1,200,75,0.4,304 Stainless|steel,,"{caps}",'
        "shop floor A"
    )


def _clean(v) -> str:
    return (v or "").strip()


def parse_machine_csv(text: str):
    """Parse a machine-inventory CSV into ``(rows, errors)`` — STRICT and HONEST.

    ``rows`` are validated machine payloads (ready for ``import_machines``);
    ``errors`` is a list of ``{"line", "reason"}``. Mirrors
    ``manifest_service.parse_manifest_csv``: BOM-tolerant header, blank line
    skipped (never reported), a malformed HEADER yields ``([], [one error])``
    (empty file → ``line: 0``; missing ``process`` → ``line: 1``), and a malformed
    ROW is reported and SKIPPED — never coerced, never aborts the file.

    Per-line error classes: missing/invalid ``process``; non-numeric
    ``count``/float columns; invalid ``capabilities``/``material_thickness_map``
    JSON; and every ``validate_machine`` violation (negative scalar, bad IT grade,
    unknown material, ``capital_frac`` out of range, unknown capability, …).
    """
    rows: list = []
    errors: list = []

    if not text or not text.strip():
        return rows, [{"line": 0, "reason": "empty CSV (no header, no rows)"}]

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return rows, [{"line": 0, "reason": "empty CSV (no header, no rows)"}]

    if header and header[0].startswith("﻿"):
        header[0] = header[0][1:]
    cols = [_clean(h).lower() for h in header]
    col_index = {name: i for i, name in enumerate(cols)}

    missing = [c for c in MACHINE_REQUIRED_COLUMNS if c not in col_index]
    if missing:
        return rows, [{
            "line": 1,
            "reason": (
                f"header missing required column(s): {', '.join(missing)}. "
                f"Expected header: {MACHINE_HEADER}"
            ),
        }]

    def cell(record: list, name: str) -> str:
        i = col_index.get(name)
        if i is None or i >= len(record):
            return ""
        return _clean(record[i])

    for offset, record in enumerate(reader):
        line = offset + 2  # header is line 1; first data row is line 2
        if not any(_clean(c) for c in record):
            continue

        row_errs: list[str] = []
        payload: dict[str, Any] = {
            "name": cell(record, "name") or None,
            "process": cell(record, "process") or None,
            "notes": cell(record, "notes") or None,
        }

        raw_count = cell(record, "count")
        if raw_count:
            try:
                payload["count"] = int(raw_count)
            except ValueError:
                row_errs.append(f"count not an integer ('{raw_count}')")
        else:
            payload["count"] = None

        for name in _FLOAT_COLUMNS:
            raw = cell(record, name)
            if not raw:
                payload[name] = None
                continue
            try:
                payload[name] = float(raw)
            except ValueError:
                row_errs.append(f"{name} not a number ('{raw}')")

        raw_mats = cell(record, "materials")
        payload["materials"] = (
            [m.strip() for m in raw_mats.split("|") if m.strip()]
            if raw_mats
            else None
        )

        for jname in ("capabilities", "material_thickness_map"):
            raw = cell(record, jname)
            if not raw:
                payload[jname] = None if jname == "material_thickness_map" else {}
                continue
            try:
                payload[jname] = json.loads(raw)
            except (ValueError, TypeError):
                row_errs.append(f"{jname} is not valid JSON")

        if not row_errs:
            try:
                validate_machine(payload)
            except ValueError as exc:
                row_errs.append(str(exc))

        if row_errs:
            errors.append({"line": line, "reason": "; ".join(row_errs)})
            continue
        rows.append(_normalize(payload))

    return rows, errors


# ── import (bulk INSERT; machines have no natural business key → append) ──────
async def import_machines(
    session: AsyncSession,
    org_id: str,
    created_by: Optional[int],
    rows: list,
) -> dict:
    """Persist parsed machine rows (bulk INSERT — append, not upsert).

    Unlike a manifest (keyed by ``part_id``), a machine has no natural business
    key (two "Haas VF-2 #3" are two machines), so each parsed row is a NEW
    instance. Per-row failures are captured as errors, never crash the batch.
    Org-scoped; does NOT commit — the caller owns the txn.

    Returns ``{"imported", "skipped", "total", "errors"}``.
    """
    imported = 0
    errors: list = []
    for idx, payload in enumerate(rows):
        try:
            row = MachineInstance(
                org_id=org_id,
                created_by=created_by,
                **_normalize(payload),
            )
            session.add(row)
            await session.flush()
            imported += 1
        except Exception as exc:  # per-row failure — report, never crash batch
            errors.append({"line": None, "index": idx, "reason": str(exc)})

    return {
        "imported": imported,
        "skipped": len(rows) - imported,
        "total": len(rows),
        "errors": errors,
    }


# ── CRUD (org-scoped) ─────────────────────────────────────────────────────────
async def get_machine(
    session: AsyncSession, org_id: str, ulid: str
) -> Optional[MachineInstance]:
    """A single owned machine by its public ULID, scoped to the org (or None)."""
    if not org_id:
        return None
    return (
        await session.execute(
            select(MachineInstance).where(
                MachineInstance.org_id == org_id,
                MachineInstance.ulid == ulid,
            )
        )
    ).scalars().first()


async def create_machine(
    session: AsyncSession,
    org_id: str,
    fields: dict,
    created_by: Optional[int] = None,
) -> MachineInstance:
    """Validate + insert one owned machine. ``ValueError`` on a malformed field."""
    validate_machine(fields)
    row = MachineInstance(
        org_id=org_id,
        created_by=created_by,
        **_normalize(fields),
    )
    session.add(row)
    await session.flush()
    return row


async def update_machine(
    session: AsyncSession,
    org_id: str,
    ulid: str,
    fields: dict,
) -> Optional[MachineInstance]:
    """Patch a machine's mutable fields (org-scoped). Only supplied keys change;
    the merged result is re-validated so a partial edit can't create an invalid
    machine. Returns ``None`` when no such machine exists in the org.
    """
    row = await get_machine(session, org_id, ulid)
    if row is None:
        return None
    merged = {k: getattr(row, k) for k in _MUTABLE_FIELDS}
    for k in _MUTABLE_FIELDS:
        if k in fields:
            merged[k] = fields[k]
    validate_machine(merged)
    merged = _normalize(merged)
    for k in _MUTABLE_FIELDS:
        setattr(row, k, merged[k])
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return row


async def delete_machine(session: AsyncSession, org_id: str, ulid: str) -> bool:
    """Delete one owned machine (org-scoped). Returns True iff a row was removed."""
    row = await get_machine(session, org_id, ulid)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


# ── keyset-paginated list (order ulid ASC — unique, monotonic per org) ────────
MACHINE_LIST_MAX = 500


def _encode_cursor(ulid: str) -> str:
    return base64.urlsafe_b64encode(ulid.encode()).decode()


def _decode_cursor(cursor: str) -> str:
    return base64.urlsafe_b64decode(cursor.encode()).decode()


async def list_machines(
    session: AsyncSession,
    org_id: str,
    *,
    cursor: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """One keyset-paginated page of the org's owned machines, ``ulid`` ASC.

    Returns ``{"machines": [...], "next_cursor": str | None}``. ``org_id`` falsy →
    an empty page (never a cross-org read). ``limit`` bounded at ``MACHINE_LIST_MAX``.
    """
    if not org_id:
        return {"machines": [], "next_cursor": None}
    limit = max(1, min(int(limit), MACHINE_LIST_MAX))

    q = select(MachineInstance).where(MachineInstance.org_id == org_id)
    if cursor:
        q = q.where(MachineInstance.ulid > _decode_cursor(cursor))
    q = q.order_by(MachineInstance.ulid.asc()).limit(limit + 1)

    fetched = list((await session.execute(q)).scalars().all())
    has_more = len(fetched) > limit
    page = fetched[:limit]
    next_cursor = _encode_cursor(page[-1].ulid) if (has_more and page) else None
    return {
        "machines": [machine_to_public(r) for r in page],
        "next_cursor": next_cursor,
    }


# ── hydration to the pure Phase-B capability types (LOCKED contract) ──────────
async def load_org_inventory(session: AsyncSession, org_id: str) -> list:
    """Hydrate the org's machines to ``list[MachineCap]`` for the pure matcher.

    Mirrors ``load_org_ground_truth``: a DB-free snapshot the Phase-B engine
    consumes. Empty / absent org → ``[]`` (byte-identical when the feature is
    unused). Every ``MachineCap`` is built to the EXACT locked field set/order.
    """
    if not org_id:
        return []
    machines = (
        await session.execute(
            select(MachineInstance).where(MachineInstance.org_id == org_id)
        )
    ).scalars().all()
    return [
        MachineCap(
            process=m.process,
            name=m.name,
            count=int(m.count) if m.count is not None else 1,
            max_workpiece_kg=m.max_workpiece_kg,
            hourly_rate_usd=m.hourly_rate_usd,
            capital_frac=m.capital_frac,
            materials=tuple(m.materials or ()),
            material_thickness_map=dict(m.material_thickness_map or {}),
            capabilities=dict(m.capabilities or {}),
        )
        for m in machines
    ]


async def load_shop_caps(session: AsyncSession, org_id: str):
    """Hydrate the org's shop-level secondary ops to ``ShopCaps`` (or empty)."""
    row = await get_shop_capabilities(session, org_id) if org_id else None
    return ShopCaps(ops=dict(row.ops or {}) if row is not None else {})


# ── shop-level secondary-op capabilities (org-scoped, one row per org) ────────
async def get_shop_capabilities(
    session: AsyncSession, org_id: str
) -> Optional[ShopCapabilities]:
    if not org_id:
        return None
    return (
        await session.execute(
            select(ShopCapabilities).where(ShopCapabilities.org_id == org_id)
        )
    ).scalars().first()


def validate_shop_ops(ops: Any) -> None:
    """Raise ``ValueError`` unless ``ops`` is a valid secondary-op map.

    ``{op: True | {size/temp limits}}``: each key a non-empty string; each value a
    bool OR a dict of numeric size/temp limits. Malformed → reported, never coerced.
    """
    if ops is None:
        return
    if not isinstance(ops, dict):
        raise ValueError("shop capabilities 'ops' must be a JSON object")
    errors: list[str] = []
    for key, val in ops.items():
        if not isinstance(key, str) or not key.strip():
            errors.append("op names must be non-empty strings")
            continue
        if isinstance(val, bool):
            continue
        if isinstance(val, dict):
            for lk, lv in val.items():
                if not _is_number(lv) or lv <= 0:
                    errors.append(
                        f"op '{key}' limit '{lk}' must be a positive number"
                    )
            continue
        errors.append(f"op '{key}' must be a boolean or a limits object")
    if errors:
        raise ValueError("; ".join(errors))


async def upsert_shop_capabilities(
    session: AsyncSession,
    org_id: str,
    ops: dict,
    created_by: Optional[int] = None,
) -> ShopCapabilities:
    """Insert or update the org's single shop-capabilities row (validated)."""
    validate_shop_ops(ops)
    row = await get_shop_capabilities(session, org_id)
    if row is None:
        row = ShopCapabilities(org_id=org_id, ops=ops or {}, created_by=created_by)
        session.add(row)
    else:
        row.ops = ops or {}
        row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return row


# ── "add from catalog" template pre-fill (static MachineProfile reference) ────
def add_from_catalog(profile_name: str) -> dict:
    """Return an editable machine payload pre-filled from the static
    ``MachineProfile`` reference DB (spec §3.1 seed convenience).

    The catalog is the TEMPLATE; the org instance is the DECLARATION — the caller
    edits then submits. ``ValueError`` if no such profile. Envelope/resolution/axes
    are seeded from the profile; ``provenance`` marks it a catalog template so the
    UI never badges an unedited prefill as a real declaration.
    """
    prof = next(
        (m for m in MACHINES if m.name.lower() == (profile_name or "").lower()),
        None,
    )
    if prof is None:
        raise ValueError(f"no catalog machine profile named '{profile_name}'")
    return _profile_to_payload(prof)


def _profile_to_payload(prof) -> dict:
    caps: dict[str, Any] = {}
    bv = prof.build_volume
    if bv and len(bv) == 3:
        caps["x"], caps["y"], caps["z"] = float(bv[0]), float(bv[1]), float(bv[2])
    if prof.min_layer_height:
        caps["min_layer_um"] = round(prof.min_layer_height * 1000.0, 3)
    if prof.resolution_xy:
        caps["min_feature_mm"] = float(prof.resolution_xy)
    proc = prof.process_type.value
    if proc == ProcessType.CNC_5AXIS.value:
        caps["axes"] = 5
        caps["motion_mode"] = "simultaneous_5"
    elif proc == ProcessType.CNC_3AXIS.value:
        caps["axes"] = 3
    return {
        "name": prof.name,
        "process": proc,
        "count": 1,
        "max_workpiece_kg": None,
        "hourly_rate_usd": None,
        "capital_frac": None,
        "capabilities": caps,
        "materials": list(prof.materials) if prof.materials else None,
        "material_thickness_map": None,
        "notes": (
            f"Prefilled from catalog '{prof.name}' ({prof.manufacturer}). "
            "EDIT to your machine's real specs before saving."
        ),
        # Honesty: an unedited catalog prefill is a TEMPLATE, not a declaration.
        "provenance": "catalog_template",
    }


def catalog_options() -> list[dict]:
    """Every static ``MachineProfile`` as an editable prefill payload (GET /catalog)."""
    return [_profile_to_payload(m) for m in MACHINES]


# ── serialization ─────────────────────────────────────────────────────────────
def machine_to_public(r: MachineInstance) -> dict:
    """The API view of a stored owned machine (ULID as the opaque public id).

    ``provenance`` is always ``"user"`` — a declared capability is a USER assertion,
    never a measurement of the machine.
    """
    return {
        "id": r.ulid,
        "name": r.name,
        "process": r.process,
        "count": r.count,
        "max_workpiece_kg": r.max_workpiece_kg,
        "hourly_rate_usd": r.hourly_rate_usd,
        "capital_frac": r.capital_frac,
        "capabilities": r.capabilities or {},
        "materials": r.materials,
        "material_thickness_map": r.material_thickness_map,
        "notes": r.notes,
        "provenance": "user",
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def serialize_shop_capabilities(row: Optional[ShopCapabilities]) -> dict:
    """The API view of an org's shop-level secondary ops (empty when unset)."""
    return {
        "ops": (row.ops or {}) if row is not None else {},
        "provenance": "user",
        "updated_at": (
            row.updated_at.isoformat() if (row and row.updated_at) else None
        ),
    }
