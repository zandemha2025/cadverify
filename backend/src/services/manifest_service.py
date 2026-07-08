"""Parts-manifest bulk onboarding — declared inventory registry (Aramco GAP 3).

A pilot-grade bridge for a customer whose parts live in SAP/PLM with no connector:
they upload their inventory list (a CSV exported from SAP/Excel) — part numbers +
demand/program/material metadata, usually WITHOUT geometry — and immediately see
their inventory ORGANIZED, plus an honest "how much of it can we even assess (has
geometry)" coverage number.

A ``manifest_parts`` row is a THIRD kind of part identity: NOT a ``mesh_hash``-keyed
catalog part (geometry-derived) and NOT a ``ground_truth_records`` cost datum — a
DECLARED inventory line keyed by the customer's own ``part_id``.

This module is the deliberate sibling of ``groundtruth_service`` (the shipped
historical-cost CSV import): it mirrors that module's CSV contract, error
discipline (per-line ``{"line", "reason"}``, BOM tolerance, blank-line skip,
all-bad → 0 rows + errors), streaming caps (in the API layer), and org-scoping.

HONESTY RAILS (non-negotiable):
  * Declared rows are USER-declared inventory FACTS — never inferred, never a
    makeability/cost claim, and they NEVER flip a band to validated.
  * A declared row does NOT create an analysis / cost decision / part summary and
    does NOT alter the catalog or triage numbers (those stay geometry-derived).
  * Coverage ``with_geometry`` counts ONLY exact normalized-stem matches against
    uploaded analyses in the SAME org; everything else is honestly
    ``without_geometry``. No fuzzy / fabricated matching.
  * ``material_class`` blank → None (allowed); unknown → a reported per-line error
    (never silently coerced). It is validated against the SAME known-class set the
    ground-truth importer uses — a manifest can never smuggle in a material the
    cost engine would later reject.
  * An empty org / absent manifest → zeroed/empty responses, byte-identical to the
    feature being unused; never a cross-org read.
"""
from __future__ import annotations

import base64
import csv
import io
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Analysis, ManifestPart
# Reuse the EXACT material-class vocabulary the ground-truth importer validates
# against — a manifest must never accept a material the cost engine would reject.
from src.services.groundtruth_service import KNOWN_MATERIAL_CLASSES

logger = logging.getLogger("cadverify.manifest")

# ── CSV bulk-import contract (mirrors groundtruth_service.CSV_* ) ────────────
# Required first, then optional (all lower-case, header row order-independent).
# ``part_id`` is the ONLY required column — a manifest is fundamentally a list of
# declared part numbers; every other column is optional declared metadata.
MANIFEST_REQUIRED_COLUMNS = ("part_id",)
MANIFEST_OPTIONAL_COLUMNS = (
    "description",
    "material_class",
    "program",
    "parent_assembly",
    "units_per_parent",
    "annual_volume",
    "quantity",
    "region",
    "source",
    "notes",
)
MANIFEST_HEADER = ",".join(MANIFEST_REQUIRED_COLUMNS + MANIFEST_OPTIONAL_COLUMNS)

# Integer columns that, when present, must parse as an integer AND be > 0. Blank
# is always allowed (→ None); a non-integer or non-positive value is a reported
# per-line error, never a silent coercion.
_POSITIVE_INT_COLUMNS = ("units_per_parent", "annual_volume", "quantity")

# Geometry file extensions the coverage normalized-stem match strips. A declared
# ``part_id`` and an uploaded analysis ``filename`` are considered the same part
# when their lower-cased, extension-stripped stems are exactly equal.
GEOMETRY_EXTS = ("stl", "step", "stp", "iges", "igs")
_STEM_RE = r"\.(stl|step|stp|iges|igs)$"

MANIFEST_LIST_MAX = 500


def _example_row() -> str:
    """One illustrative data row for the /import/template body."""
    return (
        "AR-PMP-001,centrifugal pump impeller,steel,GreenField-Phase1,"
        "PMP-ASSY-01,2,120,240,SA,SAP-export,critical spare"
    )


# ── CSV parser (pure — no DB, no I/O) ────────────────────────────────────────
def _clean(v) -> str:
    return (v or "").strip()


def parse_manifest_csv(text: str):
    """Parse a parts-manifest CSV into ``(rows, errors)`` — STRICT and HONEST.

    ``rows`` is a list of declared-part payloads (dicts of ONLY the declared
    columns; blanks → None — nothing is fabricated). ``errors`` is a list of
    ``{"line": <1-based file line>, "reason": <str>}``.

    Mirrors ``groundtruth_service.parse_ground_truth_csv``:
      * BOM-tolerant header (a UTF-8 BOM on the first cell is stripped).
      * A wholly blank line is skipped, never reported.
      * A malformed HEADER (missing ``part_id``, empty file) yields
        ``([], errors)`` with a single header/file-level error rather than
        guessing: empty file → a single ``line: 0`` error; missing required
        column → a single ``line: 1`` error.
      * A malformed ROW is reported and SKIPPED — never silently coerced or
        dropped. One bad row never aborts the file: valid rows still come back.

    Per-line error classes:
      * missing / blank ``part_id``
      * ``units_per_parent`` / ``annual_volume`` / ``quantity``: non-integer, or
        integer but not > 0
      * unknown ``material_class`` (blank is allowed → None)
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

    # normalise header names (lower, strip); strip a UTF-8 BOM on the first cell.
    if header and header[0].startswith("﻿"):
        header[0] = header[0][1:]
    cols = [_clean(h).lower() for h in header]
    col_index = {name: i for i, name in enumerate(cols)}

    missing = [c for c in MANIFEST_REQUIRED_COLUMNS if c not in col_index]
    if missing:
        return rows, [{
            "line": 1,
            "reason": (
                f"header missing required column(s): {', '.join(missing)}. "
                f"Expected header: {MANIFEST_HEADER}"
            ),
        }]

    def cell(record: list, name: str) -> str:
        i = col_index.get(name)
        if i is None or i >= len(record):
            return ""
        return _clean(record[i])

    for offset, record in enumerate(reader):
        line = offset + 2  # header is line 1; first data row is line 2
        # skip a wholly blank line without reporting it as an error
        if not any(_clean(c) for c in record):
            continue

        part_id = cell(record, "part_id")
        row_errs: list = []
        if not part_id:
            row_errs.append("missing part_id")

        int_values: dict = {}
        for name in _POSITIVE_INT_COLUMNS:
            raw = cell(record, name)
            if not raw:
                int_values[name] = None
                continue
            try:
                val = int(raw)
            except ValueError:
                row_errs.append(f"{name} not an integer ('{raw}')")
                continue
            if val <= 0:
                row_errs.append(f"{name} must be > 0 (got {val})")
                continue
            int_values[name] = val

        material_class = cell(record, "material_class")
        # blank material_class is allowed (→ None); an unknown one is a reported
        # error, never silently coerced.
        if material_class and material_class not in KNOWN_MATERIAL_CLASSES:
            row_errs.append(f"unknown material_class '{material_class}'")

        if row_errs:
            errors.append({"line": line, "reason": "; ".join(row_errs)})
            continue

        # Declared payload — ONLY the declared columns; blanks are None. Nothing
        # is fabricated (no defaults invented for absent metadata).
        rows.append({
            "part_id": part_id,
            "description": cell(record, "description") or None,
            "material_class": material_class or None,
            "program": cell(record, "program") or None,
            "parent_assembly": cell(record, "parent_assembly") or None,
            "units_per_parent": int_values["units_per_parent"],
            "annual_volume": int_values["annual_volume"],
            "quantity": int_values["quantity"],
            "region": cell(record, "region") or None,
            "source": cell(record, "source") or None,
            "notes": cell(record, "notes") or None,
        })

    return rows, errors


_DECLARED_FIELDS = (
    "description",
    "material_class",
    "program",
    "parent_assembly",
    "units_per_parent",
    "annual_volume",
    "quantity",
    "region",
    "source",
    "notes",
)


# ── import (org-scoped UPSERT on (org_id, part_id)) ──────────────────────────
async def import_manifest(
    session: AsyncSession,
    org_id: str,
    created_by: Optional[int],
    rows: list,
) -> dict:
    """Persist parsed manifest rows, UPSERTING on ``(org_id, part_id)``.

    Last-write-wins per ``part_id`` within the org: a re-imported manifest UPDATES
    the existing declared row (every declared column is overwritten with the new
    value, including None where a column is now blank) rather than duplicating it.
    ``imported`` (freshly inserted) and ``updated`` (overwrote an existing row)
    are counted DISTINCTLY. Per-row failures are captured as errors, never crash
    the batch. Org-scoped throughout; does NOT commit — the caller owns the txn.

    Returns ``{"imported", "updated", "skipped", "total", "errors"}`` where
    ``total`` is the number of parsed rows handed in and ``skipped`` is the count
    that failed to persist.
    """
    imported = 0
    updated = 0
    errors: list = []
    now = datetime.now(timezone.utc)

    for idx, payload in enumerate(rows):
        part_id = payload["part_id"]
        try:
            existing = (
                await session.execute(
                    select(ManifestPart).where(
                        ManifestPart.org_id == org_id,
                        ManifestPart.part_id == part_id,
                    )
                )
            ).scalar_one_or_none()

            if existing is None:
                row = ManifestPart(
                    org_id=org_id,
                    part_id=part_id,
                    created_by=created_by,
                    **{f: payload[f] for f in _DECLARED_FIELDS},
                )
                session.add(row)
                await session.flush()
                imported += 1
            else:
                for f in _DECLARED_FIELDS:
                    setattr(existing, f, payload[f])
                existing.updated_at = now
                await session.flush()
                updated += 1
        except Exception as exc:  # per-row failure — report, never crash batch
            errors.append({"line": None, "index": idx, "reason": str(exc)})

    skipped = len(rows) - imported - updated
    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "total": len(rows),
        "errors": errors,
    }


# ── serialization ────────────────────────────────────────────────────────────
def part_to_public(r: ManifestPart) -> dict:
    """The API view of a stored declared part (ULID as the opaque public id)."""
    return {
        "id": r.ulid,
        "part_id": r.part_id,
        "description": r.description,
        "material_class": r.material_class,
        "program": r.program,
        "parent_assembly": r.parent_assembly,
        "units_per_parent": r.units_per_parent,
        "annual_volume": r.annual_volume,
        "quantity": r.quantity,
        "region": r.region,
        "source": r.source,
        "notes": r.notes,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# ── keyset-paginated list (order part_id ASC — deterministic, unique per org) ─
def _encode_cursor(part_id: str) -> str:
    """Opaque forward cursor = base64(part_id). ``part_id`` is unique within an
    org (the ``uq_manifest_parts_org_part`` constraint), so it is a fully
    deterministic keyset — pages never overlap or skip."""
    return base64.urlsafe_b64encode(part_id.encode()).decode()


def _decode_cursor(cursor: str) -> str:
    return base64.urlsafe_b64decode(cursor.encode()).decode()


async def list_manifest(
    session: AsyncSession,
    org_id: str,
    *,
    cursor: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """One keyset-paginated page of the org's declared manifest, ``part_id`` ASC.

    Returns ``{"parts": [...], "next_cursor": str | None}``; ``next_cursor`` is
    None only on the final page. ``limit`` is bounded at ``MANIFEST_LIST_MAX``.
    ``org_id`` falsy → an empty page (never a cross-org read).
    """
    if not org_id:
        return {"parts": [], "next_cursor": None}

    limit = max(1, min(int(limit), MANIFEST_LIST_MAX))

    q = select(ManifestPart).where(ManifestPart.org_id == org_id)
    if cursor:
        q = q.where(ManifestPart.part_id > _decode_cursor(cursor))
    # Fetch limit+1 so we know whether a further page exists without a COUNT.
    q = q.order_by(ManifestPart.part_id.asc()).limit(limit + 1)

    fetched = list((await session.execute(q)).scalars().all())
    has_more = len(fetched) > limit
    page = fetched[:limit]

    next_cursor: Optional[str] = None
    if has_more and page:
        next_cursor = _encode_cursor(page[-1].part_id)
    return {"parts": [part_to_public(r) for r in page], "next_cursor": next_cursor}


# ── coverage summary (the Aramco headline) ───────────────────────────────────
def _zeroed_coverage(org_id: Optional[str]) -> dict:
    return {
        "org_id": org_id or None,
        "total_declared": 0,
        "by_program": [],
        "geometry": {
            "with_geometry": 0,
            "without_geometry": 0,
            "match": "normalized-stem, exact",
        },
    }


async def manifest_coverage(session: AsyncSession, org_id: str) -> dict:
    """The Aramco headline: how much declared inventory can we even assess?

    Returns:
      * ``total_declared`` — COUNT of declared parts in the org.
      * ``by_program`` — a SQL ``GROUP BY program`` rollup, ``[{program, count}]``,
        sorted count-desc then name. A NULL program is reported under the explicit
        ``"(unassigned)"`` label (honest: it is stated, not dropped). FULLY
        SCALABLE — an O(programs) aggregate, not a Python fold.
      * ``geometry`` — ``{with_geometry, without_geometry, match}``.
        ``with_geometry`` = COUNT of declared parts that ALSO have an uploaded
        analysis in the SAME org, matched by NORMALIZED STEM:
        ``lower(strip_geom_ext(filename)) == lower(strip_geom_ext(part_id))``.
        This is a BEST-EFFORT convention match (``match`` = "normalized-stem,
        exact"); an unmatched declared part is honestly ``without_geometry`` —
        never a fabricated match.

    An empty / falsy ``org_id`` → a zeroed coverage (never a cross-org read).

    SCALE CAVEAT (deliberate follow-up): the normalized-stem expression
    (``regexp_replace`` + ``lower`` on both ``part_id`` and ``filename``) is NOT
    index-backed — at extreme scale a functional index on the normalized columns
    (or a materialized normalized-stem column) would be the next step. Correct and
    honest at pilot scale; a known optimisation for millions of rows.
    """
    if not org_id:
        return _zeroed_coverage(org_id)

    total_declared = (
        await session.execute(
            select(func.count()).select_from(ManifestPart).where(
                ManifestPart.org_id == org_id
            )
        )
    ).scalar_one()

    if not total_declared:
        return _zeroed_coverage(org_id)

    # by_program — scalable SQL GROUP BY (O(programs)).
    prog_rows = (
        await session.execute(
            select(ManifestPart.program, func.count())
            .where(ManifestPart.org_id == org_id)
            .group_by(ManifestPart.program)
        )
    ).all()
    # NULL program is honestly stated under an explicit label, never dropped.
    by_program = [
        {"program": (p if p is not None else "(unassigned)"), "count": int(c)}
        for p, c in prog_rows
    ]
    by_program.sort(key=lambda d: (-d["count"], d["program"]))

    # Normalized-stem geometry match. Strip a trailing geometry extension
    # (case-insensitive) and lower-case both sides, then EXISTS-join a declared
    # part to any analysis in the same org whose filename stem matches. This is a
    # correlated EXISTS so each declared part is counted at most once (DISTINCT by
    # construction) even if several analyses match the same stem.
    norm_part = func.lower(
        func.regexp_replace(ManifestPart.part_id, _STEM_RE, "", "i")
    )
    norm_file = func.lower(
        func.regexp_replace(Analysis.filename, _STEM_RE, "", "i")
    )
    has_geo = (
        select(Analysis.id)
        .where(Analysis.org_id == org_id, norm_file == norm_part)
        .exists()
    )
    with_geometry = (
        await session.execute(
            select(func.count()).select_from(ManifestPart).where(
                ManifestPart.org_id == org_id, has_geo
            )
        )
    ).scalar_one()
    with_geometry = int(with_geometry)

    return {
        "org_id": org_id,
        "total_declared": int(total_declared),
        "by_program": by_program,
        "geometry": {
            "with_geometry": with_geometry,
            "without_geometry": int(total_declared) - with_geometry,
            # Honest label: this is an exact match on the normalized stem, NOT a
            # fuzzy/semantic match.
            "match": "normalized-stem, exact",
        },
    }
