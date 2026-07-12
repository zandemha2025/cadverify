"""Parts-master feeder — bulk-onboard a customer's part library into the org's
identity corpus (customer-context Slice 2: the flywheel's COLD START).

The retrieval engine + confirm-match card (Slice 1) only ground an identity by
RETRIEVING the org's own prior parts. A fresh org's corpus is empty, so nothing
meaningful matches on day one. This feeder fixes that: a customer uploads their
existing part library (CAD files + an identity mapping) and each part enters the
corpus WITH its DECLARED identity (part number / name / program / material). A
later upload of a similar part then surfaces a real "Looks like your <name>".

Two writes per onboarded file, both org-scoped and REUSING Slice-1 primitives:
  * ``part_signature_service.upsert_signature`` — the geometry retrieval corpus
    row (18-dim MEASURED signature + the declared identity), ``source='parts_master'``.
  * ``manifest_service.import_manifest`` — the DECLARED parts-master registry
    (``ManifestPart``), so an onboarded part lives in the declared master too, not
    only the geometry corpus. Reused verbatim (its own per-row error discipline).

HONESTY RAILS (non-negotiable — never fabricate an identity):
  * A file whose mapping has NO name onboards its geometry with ``declared_name=None``
    (still useful for a later human confirm) — never a guessed name.
  * A file with NO ``part_id`` in the mapping onboards geometry ONLY (no
    ``ManifestPart`` row — the declared master is keyed by the customer's own part
    number; we don't invent one).
  * A bad file (unparseable mesh, unknown material) is SKIPPED with an honest
    reason and NEVER aborts the batch — the summary states exactly what was skipped.
  * ``material_class`` is validated against the SAME known-class vocabulary the
    manifest/cost engine uses — an unknown class is a reported per-file skip, never
    silently coerced (a parts-master can't smuggle in a material the engine rejects).
  * The mesh_hash is the SAME ``analysis_service.compute_mesh_hash`` used across the
    app, and the mesh parse reuses the live validate/batch tessellation path — no
    reinvented CAD parsing, no second hashing scheme.

Zero egress: signature computation (``similarity.vector_for_mesh``) and hashing are
purely local. Does NOT commit — the caller owns the transaction (mirrors the sibling
services).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import PartSignature
from src.eval import similarity
from src.services import manifest_service
from src.services import part_signature_service as sigsvc
from src.services.analysis_service import compute_mesh_hash
from src.services.groundtruth_service import KNOWN_MATERIAL_CLASSES

logger = logging.getLogger("cadverify.parts_master")

# The provenance tag on a corpus row that entered via this bulk feeder — distinct
# from the analysis funnel's 'upload' and from a human 'user_confirmed'.
SOURCE_PARTS_MASTER = "parts_master"

# ── identity-mapping contract (mirrors manifest_service's CSV style) ──────────
# ``filename`` is the ONLY required column — it binds a mapping row to an uploaded
# CAD file. Every other column is OPTIONAL declared identity; a missing optional
# column is fine (the part onboards with whatever identity was given, never a guess).
MAPPING_REQUIRED_COLUMNS = ("filename",)
MAPPING_OPTIONAL_COLUMNS = ("part_id", "name", "program", "material_class")
MAPPING_HEADER = ",".join(MAPPING_REQUIRED_COLUMNS + MAPPING_OPTIONAL_COLUMNS)

# How many parts a single onboarding batch may carry (defensive cap; the ZIP path
# is additionally bounded by batch_service's own BATCH_MAX_ITEMS).
ONBOARD_MAX_FILES = 2000

# Number of most-recent corpus rows GET /identity/library returns.
LIBRARY_RECENT_LIMIT = 20


def _example_mapping_row() -> str:
    return "impeller.step,AR-PMP-001,Centrifugal pump impeller,GreenField-Phase1,steel"


def _clean(v) -> str:
    return (v or "").strip()


def _norm_key(filename: Optional[str]) -> str:
    """The join key between a mapping row and an uploaded CAD file: the lower-cased
    basename. Case-/path-insensitive so a ``parts/Impeller.STEP`` mapping still binds
    an uploaded ``impeller.step`` — an honest convention, documented, never fuzzy."""
    if not filename:
        return ""
    return os.path.basename(str(filename)).strip().lower()


# ── mapping parsers (pure — no DB, no I/O) ────────────────────────────────────
def parse_identity_csv(text: str) -> tuple[dict, list]:
    """Parse an identity-mapping CSV into ``(mapping, errors)``.

    ``mapping`` is ``{normalized_filename: {part_id, name, program, material_class}}``
    (blanks → None — nothing fabricated); ``errors`` is a list of
    ``{"line", "reason"}``. Mirrors ``manifest_service.parse_manifest_csv``:
    BOM-tolerant header, blank lines skipped, a malformed HEADER (missing
    ``filename`` / empty file) yields ``({}, [one error])`` rather than guessing, and
    a malformed ROW is reported + skipped (never coerced). A duplicate filename is
    last-write-wins with a reported note. ``material_class`` is NOT rejected here —
    it is validated per-file at onboard time so the whole file can be skipped
    together with its geometry (kept in one place, honestly).
    """
    mapping: dict = {}
    errors: list = []

    if not text or not text.strip():
        return mapping, [{"line": 0, "reason": "empty mapping CSV (no header, no rows)"}]

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return mapping, [{"line": 0, "reason": "empty mapping CSV (no header, no rows)"}]

    if header and header[0].startswith("﻿"):
        header[0] = header[0][1:]
    cols = [_clean(h).lower() for h in header]
    col_index = {name: i for i, name in enumerate(cols)}

    missing = [c for c in MAPPING_REQUIRED_COLUMNS if c not in col_index]
    if missing:
        return mapping, [{
            "line": 1,
            "reason": (
                f"header missing required column(s): {', '.join(missing)}. "
                f"Expected header: {MAPPING_HEADER}"
            ),
        }]

    def cell(record: list, name: str) -> str:
        i = col_index.get(name)
        if i is None or i >= len(record):
            return ""
        return _clean(record[i])

    for offset, record in enumerate(reader):
        line = offset + 2  # header is line 1
        if not any(_clean(c) for c in record):
            continue
        filename = cell(record, "filename")
        if not filename:
            errors.append({"line": line, "reason": "missing filename"})
            continue
        key = _norm_key(filename)
        if key in mapping:
            errors.append({
                "line": line,
                "reason": f"duplicate filename '{filename}' — last row wins",
            })
        mapping[key] = {
            "filename": filename,
            "part_id": cell(record, "part_id") or None,
            "name": cell(record, "name") or None,
            "program": cell(record, "program") or None,
            "material_class": cell(record, "material_class") or None,
        }

    return mapping, errors


def parse_identity_json(text: str) -> tuple[dict, list]:
    """Parse an identity mapping from JSON into ``(mapping, errors)``.

    Accepts either a top-level list ``[{filename, ...}]`` or an object
    ``{"parts": [...]}`` / ``{"mappings": [...]}``. Same field vocabulary and honesty
    as the CSV form. A row without a ``filename`` is a reported error, never a guess.
    """
    mapping: dict = {}
    errors: list = []
    if not text or not text.strip():
        return mapping, [{"line": 0, "reason": "empty mapping JSON"}]
    try:
        doc = json.loads(text)
    except (ValueError, TypeError) as exc:
        return mapping, [{"line": 0, "reason": f"invalid JSON: {exc}"}]

    if isinstance(doc, dict):
        rows = doc.get("parts") or doc.get("mappings") or []
    elif isinstance(doc, list):
        rows = doc
    else:
        return mapping, [{"line": 0, "reason": "JSON must be a list or {parts:[...]}"}]

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append({"line": idx, "reason": "mapping entry is not an object"})
            continue
        filename = _clean(row.get("filename"))
        if not filename:
            errors.append({"line": idx, "reason": "missing filename"})
            continue
        key = _norm_key(filename)
        if key in mapping:
            errors.append({
                "line": idx,
                "reason": f"duplicate filename '{filename}' — last entry wins",
            })
        mapping[key] = {
            "filename": filename,
            "part_id": _clean(row.get("part_id")) or None,
            "name": _clean(row.get("name")) or None,
            "program": _clean(row.get("program")) or None,
            "material_class": _clean(row.get("material_class")) or None,
        }
    return mapping, errors


def parse_identity_mapping(text: str, *, content_hint: str = "") -> tuple[dict, list]:
    """Dispatch to the JSON or CSV parser. JSON when the hint (filename/content-type)
    says so OR the payload's first non-space char is ``[`` / ``{``; else CSV."""
    hint = (content_hint or "").lower()
    stripped = (text or "").lstrip()
    is_json = (
        "json" in hint
        or hint.endswith(".json")
        or stripped[:1] in ("[", "{")
    )
    return parse_identity_json(text) if is_json else parse_identity_csv(text)


# ── the onboarding orchestrator ───────────────────────────────────────────────
def _honest_reason(exc: Exception) -> str:
    """A readable per-file skip reason. Unwraps an HTTPException detail (the parse
    path raises 400s for bad geometry) into a plain string; never a bare traceback."""
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("code") or detail)
    if detail:
        return str(detail)
    msg = str(exc).strip()
    return msg or exc.__class__.__name__


def _parse_mesh(data: bytes, filename: str):
    """Reuse the LIVE validate/batch tessellation path (no reinvented CAD parsing).

    Imported lazily so this service (and its pure parsers) load without dragging in
    the heavy trimesh/gmsh route module unless an onboard actually runs."""
    from src.api.routes import _parse_mesh as _route_parse_mesh

    mesh, _suffix = _route_parse_mesh(data, filename)
    return mesh


async def library_size(session: AsyncSession, org_id: str) -> int:
    """COUNT of corpus rows in the caller's org — the honest library size. Falsy
    org → 0 (never a cross-org read)."""
    if not org_id:
        return 0
    return int(
        (
            await session.execute(
                select(func.count()).select_from(PartSignature).where(
                    PartSignature.org_id == org_id
                )
            )
        ).scalar_one()
    )


async def recent_library(session: AsyncSession, org_id: str, limit: int = LIBRARY_RECENT_LIMIT) -> list[dict]:
    """The org's most-recently-touched corpus rows (declared identity only, never the
    raw signature vector) so the UI can show what's in the library."""
    if not org_id:
        return []
    limit = max(1, min(int(limit), 100))
    rows = (
        await session.execute(
            select(PartSignature)
            .where(PartSignature.org_id == org_id)
            .order_by(PartSignature.updated_at.desc(), PartSignature.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [sigsvc.serialize_signature(r) for r in rows]


async def onboard_library(
    session: AsyncSession,
    org_id: str,
    created_by: Optional[int],
    files: Iterable[tuple[str, bytes]],
    mapping: dict,
) -> dict:
    """Bulk-onboard a part library into the org's identity corpus (the cold start).

    ``files`` is an iterable of ``(filename, raw_bytes)``; ``mapping`` is the parsed
    identity mapping keyed by normalized filename (from ``parse_identity_mapping``).
    For each file, inside its OWN savepoint (so one bad file rolls back only itself
    and never poisons the batch txn):

      1. Look up its declared identity by normalized filename (absent → no declared
         identity; still onboarded as bare geometry — honest, useful for a later
         confirm).
      2. Validate ``material_class`` against the known-class set — unknown → skip
         this file with a stated reason (never smuggle a bad material).
      3. Compute the SAME ``mesh_hash`` used app-wide + parse the mesh via the live
         path + the 18-dim ``vector_for_mesh`` signature.
      4. ``upsert_signature(source='parts_master')`` — enter the geometry corpus WITH
         the declared identity (nullable — a missing name stays None, not a guess).
      5. If a ``part_id`` was declared, queue a ``ManifestPart`` row for the declared
         master (registered in ONE reused ``import_manifest`` call after the loop).

    Returns an HONEST summary:
      ``{onboarded, skipped:[{filename, reason}], library_size, unnamed,
         manifest_registered, mapping_errors:[...]}``
    where ``onboarded`` counts corpus rows written, ``unnamed`` is how many of those
    carry NO declared name, and ``manifest_registered`` is how many declared-master
    rows the reused importer wrote. Does NOT commit.
    """
    onboarded = 0
    unnamed = 0
    skipped: list[dict] = []
    manifest_rows: list[dict] = []
    seen_hashes: set[str] = set()

    for filename, data in files:
        try:
            identity = mapping.get(_norm_key(filename), {})
            material_class = identity.get("material_class")
            if material_class and material_class not in KNOWN_MATERIAL_CLASSES:
                skipped.append({
                    "filename": filename,
                    "reason": (
                        f"unknown material_class '{material_class}' — fix it or leave "
                        "blank (never coerced)"
                    ),
                })
                continue
            if not data:
                skipped.append({"filename": filename, "reason": "empty file"})
                continue

            part_id = identity.get("part_id")
            name = identity.get("name")
            program = identity.get("program")

            async with session.begin_nested():
                mesh_hash = compute_mesh_hash(data)
                mesh = _parse_mesh(data, filename)  # may raise 400 on bad geometry
                vector = similarity.vector_for_mesh(mesh)
                await sigsvc.upsert_signature(
                    session,
                    org_id,
                    mesh_hash,
                    vector,
                    declared_part_id=part_id,
                    declared_name=name,
                    program=program,
                    source=SOURCE_PARTS_MASTER,
                )

            # A batch that repeats the same geometry hash upserts ONE corpus row
            # (last write wins); count it once so ``onboarded`` matches the corpus.
            if mesh_hash not in seen_hashes:
                seen_hashes.add(mesh_hash)
                onboarded += 1
                if not name:
                    unnamed += 1

            if part_id:
                # 'name' is the human-readable identity; the declared master's
                # equivalent free-text column is 'description'. Only a part_id can key
                # a ManifestPart, so nameless-but-numbered parts still register.
                manifest_rows.append({
                    "part_id": part_id,
                    "description": name,
                    "material_class": material_class,
                    "program": program,
                    "parent_assembly": None,
                    "units_per_parent": None,
                    "annual_volume": None,
                    "quantity": None,
                    "region": None,
                    "source": SOURCE_PARTS_MASTER,
                    "notes": None,
                })
        except Exception as exc:  # per-file: report + skip, never abort the batch
            logger.info("parts-master onboard skipped %s: %s", filename, exc)
            skipped.append({"filename": filename, "reason": _honest_reason(exc)})

    # Register the declared master rows in ONE reused import_manifest call (its own
    # per-row error discipline). Last-write-wins per part_id, org-scoped. A manifest
    # failure never un-onboards a signature — the corpus is the cold-start value.
    manifest_registered = 0
    manifest_errors: list = []
    if manifest_rows:
        summary = await manifest_service.import_manifest(
            session, org_id, created_by, manifest_rows
        )
        manifest_registered = summary["imported"] + summary["updated"]
        manifest_errors = summary["errors"]

    size = await library_size(session, org_id)
    return {
        "onboarded": onboarded,
        "unnamed": unnamed,
        "skipped": skipped,
        "manifest_registered": manifest_registered,
        "manifest_errors": manifest_errors,
        "library_size": size,
    }
