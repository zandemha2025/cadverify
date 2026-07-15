"""W5 ground-truth flywheel — persistence + orchestration (NOT new math).

Wraps the tested costing ground-truth loop (``src/costing/groundtruth.py``) in
an ORG-SCOPED durable store so a Zoox-style validation session PERSISTS beyond
the meeting:

  * **ingest** — real quotes land as ``ground_truth_records`` rows (org-stamped);
  * **recalibrate** — ``run_loop()`` over ONE org's rows -> a
    ``CalibrationBundle`` on local disk (per-process factors + held-out
    residuals);
  * **serve** — load that bundle at ``/validate/cost`` time -> a MEASURED
    ``ResidualModel``, so estimates carry a validated empirical band.

Cross-tenant honesty: every read is ``WHERE org_id = caller-org``, so one org's
ground truth can never enter another org's calibration. The costing math is
imported and used unchanged — this module only persists, filters, and
orchestrates.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.models import ProcessType
from src.costing import calibration_store as cstore
from src.costing.groundtruth import MIN_RESIDUALS, GroundTruthRecord, run_loop
from src.db.models import GroundTruthRecordRow

logger = logging.getLogger("cadverify.groundtruth")

# Hard ceiling on best-effort geometry extraction during ingest so a pathological
# or oversized mesh can never hang the request; on timeout the record stores with
# NULL geometry (the analogy k-NN simply skips it).
_GEOM_EXTRACT_TIMEOUT_S = float(os.getenv("GT_GEOM_EXTRACT_TIMEOUT_S", "20"))

# ── CSV bulk-import contract (W5 flywheel mass-ingest) ───────────────────────
# Known engine process ids and material classes the importer validates against —
# the SAME vocabularies the single-ingest / costing layer accepts, so a bulk
# import can never smuggle in a value the ground-truth loop would later reject.
KNOWN_PROCESSES = frozenset(p.value for p in ProcessType)
# Material classes recognised by the cost engine (rates.MRR keys). "polymer" is
# the documented default when the column is omitted/blank.
KNOWN_MATERIAL_CLASSES = frozenset(
    {"polymer", "aluminum", "steel", "stainless", "titanium"}
)
KNOWN_SOURCE_TYPES = frozenset(
    {"actual", "quote", "invoice", "pilot", "synthetic", "seed", "demo", "stand_in"}
)
SYNTHETIC_SOURCE_TYPES = frozenset({"synthetic", "seed", "demo", "stand_in"})
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

# Exact CSV columns. Required first, then optional (all lower-case, header row
# order-independent). Imported rows default to real historical costs, but an
# explicit synthetic/seed/demo source_type is forced to stand_in=True so it can
# exercise dashboards without ever counting toward validated accuracy.
CSV_REQUIRED_COLUMNS = ("part_id", "process", "quantity", "actual_unit_cost_usd")
CSV_OPTIONAL_COLUMNS = (
    "material_class", "shop", "region", "currency", "source", "source_type",
    "vendor_quote_id", "invoice_date", "actual_machine_hours",
    "actual_setup_hours", "actual_labor_hours", "actual_inspection_hours",
    "actual_cycle_seconds", "evidence_sha256", "evidence_uri", "part_path",
    "notes",
)
CSV_HEADER = ",".join(CSV_REQUIRED_COLUMNS + CSV_OPTIONAL_COLUMNS)

# Documented honest floor: a served calibration is emitted ONLY from at least
# this many REAL (non-stand-in) records. Below it recalibration REFUSES rather
# than fit a factor from insufficient / synthetic data. Mirrors the sibling eval
# honesty rails — ``eval.run.MIN_HUMAN_LABELS`` (30),
# ``eval.backtest_ensemble.MIN_BACKTEST_REAL`` (8), and
# ``costing.groundtruth.MIN_RESIDUALS`` (3, the per-process CI floor). We pin to
# the backtest floor (8): enough real records that a 30% by-part held-out split
# can still surface >= MIN_RESIDUALS real residuals to MEASURE against.
MIN_REAL_RECORDS = 8


class InsufficientGroundTruth(Exception):
    """Recalibration was requested below the ``MIN_REAL_RECORDS`` real-record floor.

    Carries the counts so the API can answer with an honest 422 that names
    exactly why accuracy is refused. Stand-in / synthetic records never count
    toward this floor — they can shape a band's spread but can NEVER earn a
    served, validated calibration.
    """

    def __init__(self, n_real: int, n_records: int, min_real: int = MIN_REAL_RECORDS):
        self.n_real = int(n_real)
        self.n_records = int(n_records)
        self.min_real = int(min_real)
        super().__init__(
            f"Recalibration refused: {self.n_real} REAL ground-truth record(s) "
            f"(< {self.min_real} required). Stand-in / synthetic records never "
            f"count toward a served calibration. Ingest more real quotes "
            f"(stand_in=false) and retry."
        )


# ── network-supplied part_path safety ────────────────────────────────────────
# A network caller (API ingest / CSV import) may supply an optional ``part_path``
# geometry hint. It is later handed to the mesh parsers (gmsh/trimesh) by
# ``resolve_part_path`` -> ``_extract_geometry_features``. An UNTRUSTED absolute
# path or a ``..`` traversal would let an authenticated caller point the server
# at any local file (``/etc/passwd``, ``/proc/...``, a FIFO/device that hangs a
# worker) — bypassing every HTTP upload guard. So we confine network-supplied
# part_path to a SAFE RELATIVE path (resolved under the trusted parts_dir).
# The trusted eval harness builds ``GroundTruthRecord`` dataclasses directly and
# is unaffected — this guard is only on the two network ingress points.
class UnsafePartPath(ValueError):
    """A network-supplied part_path is absolute or escapes the corpus dir."""


def sanitize_part_path(value):
    """Return a safe relative part_path, or None if blank; raise UnsafePartPath.

    Rejects absolute paths, ``..`` traversal, home expansion, and NUL bytes — a
    network client has no business naming an absolute server path. A safe value
    is a plain relative path that ``resolve_part_path`` joins under parts_dir.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if "\x00" in s:
        raise UnsafePartPath("part_path contains a NUL byte")
    if s.startswith("~"):
        raise UnsafePartPath("part_path may not use ~ home expansion")
    if os.path.isabs(s) or (len(s) > 1 and s[1] == ":"):  # POSIX abs or Windows drive
        raise UnsafePartPath("part_path must be a relative path within the corpus, not absolute")
    parts = s.replace("\\", "/").split("/")
    if ".." in parts:
        raise UnsafePartPath("part_path may not contain '..' path traversal")
    return s


# ── CSV parser (pure — no DB, no I/O) ────────────────────────────────────────
def _clean(v) -> str:
    return (v or "").strip()


def _parse_optional_float(raw: str, name: str, row_errs: list) -> Optional[float]:
    if not raw:
        return None
    try:
        val = float(raw)
    except ValueError:
        row_errs.append(f"{name} not a number ('{raw}')")
        return None
    if val < 0:
        row_errs.append(f"{name} must be >= 0 (got {val})")
        return None
    return val


def _parse_optional_date(raw: str, name: str, row_errs: list) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        row_errs.append(f"{name} must be YYYY-MM-DD (got '{raw}')")
        return None


def _normal_source_type(raw: str) -> str:
    return (raw or "actual").strip().lower()


def _is_synthetic_source_type(source_type: str) -> bool:
    return _normal_source_type(source_type) in SYNTHETIC_SOURCE_TYPES


def _normal_payload_source_type(payload: dict) -> str:
    source_type = _normal_source_type(payload.get("source_type") or "actual")
    if source_type not in KNOWN_SOURCE_TYPES:
        raise ValueError(
            f"source_type must be one of {', '.join(sorted(KNOWN_SOURCE_TYPES))} "
            f"(got '{source_type}')"
        )
    return source_type


def _normal_invoice_date(value) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"invoice_date must be YYYY-MM-DD (got '{value}')") from exc


def _normal_evidence_sha256(value) -> Optional[str]:
    if value is None or value == "":
        return None
    digest = str(value).strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError("evidence_sha256 must be a 64-character hex digest")
    return digest


def parse_ground_truth_csv(text: str):
    """Parse a historical-cost CSV into (rows, errors) — STRICT and HONEST.

    ``rows`` is a list of ``ingest_record`` payloads (each with
    ``stand_in=False`` — imported historical costs are REAL). ``errors`` is a
    list of ``{"line": <1-based file line>, "reason": <str>}``.

    Contract (see ``CSV_HEADER``): required columns are ``part_id``, ``process``,
    ``quantity``, ``actual_unit_cost_usd``; optional columns are
    ``material_class`` (default ``polymer``), ``shop``, ``region``, ``currency``
    (default ``USD``), ``source``, source/evidence/hour metadata, ``part_path``,
    ``notes``. There is no ``stand_in`` column: use ``source_type=synthetic``,
    ``seed``, ``demo``, or ``stand_in`` to deliberately ingest a stand-in row.

    Honesty rails:
      * A malformed ROW is reported (unknown process, unknown material class,
        non-positive quantity/cost, missing required value, bad currency) and
        SKIPPED — never silently coerced or dropped without a report. One bad row
        never aborts the file: valid rows still come back.
      * A malformed HEADER (missing a required column, empty file) yields
        ``([], errors)`` with a single header-level error rather than guessing.
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

    missing = [c for c in CSV_REQUIRED_COLUMNS if c not in col_index]
    if missing:
        return rows, [{
            "line": 1,
            "reason": (
                f"header missing required column(s): {', '.join(missing)}. "
                f"Expected header: {CSV_HEADER}"
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
        process = cell(record, "process")
        quantity_raw = cell(record, "quantity")
        cost_raw = cell(record, "actual_unit_cost_usd")

        row_errs: list = []
        if not part_id:
            row_errs.append("missing part_id")
        if not process:
            row_errs.append("missing process")
        elif process not in KNOWN_PROCESSES:
            row_errs.append(f"unknown process '{process}'")

        quantity = None
        if not quantity_raw:
            row_errs.append("missing quantity")
        else:
            try:
                quantity = int(quantity_raw)
                if quantity < 1:
                    row_errs.append(f"quantity must be >= 1 (got {quantity})")
            except ValueError:
                row_errs.append(f"quantity not an integer ('{quantity_raw}')")

        cost = None
        if not cost_raw:
            row_errs.append("missing actual_unit_cost_usd")
        else:
            try:
                cost = float(cost_raw)
                if not (cost > 0):
                    row_errs.append(
                        f"actual_unit_cost_usd must be > 0 (got {cost})"
                    )
            except ValueError:
                row_errs.append(
                    f"actual_unit_cost_usd not a number ('{cost_raw}')"
                )

        material_class = cell(record, "material_class") or "polymer"
        if material_class not in KNOWN_MATERIAL_CLASSES:
            row_errs.append(f"unknown material_class '{material_class}'")

        # network-supplied part_path must be a safe relative corpus path
        safe_part_path = None
        try:
            safe_part_path = sanitize_part_path(cell(record, "part_path") or None)
        except UnsafePartPath as exc:
            row_errs.append(str(exc))

        currency = (cell(record, "currency") or "USD").upper()
        if not (currency.isalpha() and len(currency) == 3):
            row_errs.append(
                f"currency must be a 3-letter code (got '{currency}')"
            )

        source_type = _normal_source_type(cell(record, "source_type") or "actual")
        if source_type not in KNOWN_SOURCE_TYPES:
            row_errs.append(
                f"source_type must be one of {', '.join(sorted(KNOWN_SOURCE_TYPES))} "
                f"(got '{source_type}')"
            )

        invoice_date = _parse_optional_date(cell(record, "invoice_date"), "invoice_date", row_errs)
        actual_machine_hours = _parse_optional_float(
            cell(record, "actual_machine_hours"), "actual_machine_hours", row_errs
        )
        actual_setup_hours = _parse_optional_float(
            cell(record, "actual_setup_hours"), "actual_setup_hours", row_errs
        )
        actual_labor_hours = _parse_optional_float(
            cell(record, "actual_labor_hours"), "actual_labor_hours", row_errs
        )
        actual_inspection_hours = _parse_optional_float(
            cell(record, "actual_inspection_hours"), "actual_inspection_hours", row_errs
        )
        actual_cycle_seconds = _parse_optional_float(
            cell(record, "actual_cycle_seconds"), "actual_cycle_seconds", row_errs
        )
        evidence_sha256 = cell(record, "evidence_sha256") or None
        if evidence_sha256 and not _SHA256_RE.fullmatch(evidence_sha256):
            row_errs.append("evidence_sha256 must be a 64-character hex digest")

        if row_errs:
            errors.append({"line": line, "reason": "; ".join(row_errs)})
            continue

        rows.append({
            "part_id": part_id,
            "process": process,
            "quantity": quantity,
            "actual_unit_cost_usd": cost,
            "material_class": material_class,
            "shop": cell(record, "shop") or None,
            "region": cell(record, "region") or None,
            "currency": currency,
            "source": cell(record, "source"),
            "source_type": source_type,
            "vendor_quote_id": cell(record, "vendor_quote_id") or None,
            "invoice_date": invoice_date.isoformat() if invoice_date else None,
            "actual_machine_hours": actual_machine_hours,
            "actual_setup_hours": actual_setup_hours,
            "actual_labor_hours": actual_labor_hours,
            "actual_inspection_hours": actual_inspection_hours,
            "actual_cycle_seconds": actual_cycle_seconds,
            "evidence_sha256": evidence_sha256.lower() if evidence_sha256 else None,
            "evidence_uri": cell(record, "evidence_uri") or None,
            "part_path": safe_part_path,
            "notes": cell(record, "notes"),
            "stand_in": _is_synthetic_source_type(source_type),
        })

    return rows, errors


async def import_records(
    session: AsyncSession, org_id: str, user_id: Optional[int], rows: list
):
    """Persist parsed CSV rows through the SINGLE-record create path.

    Funnels every row through ``ingest_record`` so bulk import shares the exact
    org-scoping, dedup, validation and ``stand_in`` honesty of the single
    endpoint. Per-row failures (a value the costing dataclass rejects) are
    collected, not fatal — returns ``(imported_count, errors)``; the caller owns
    the commit.
    """
    imported = 0
    errors: list = []
    for idx, payload in enumerate(rows):
        try:
            await ingest_record(session, org_id, user_id, payload)
            imported += 1
        except (ValueError, KeyError) as exc:
            errors.append({"line": None, "index": idx, "reason": str(exc)})
    return imported, errors


# ── serialization ──────────────────────────────────────────────────────────
def row_to_public(r: GroundTruthRecordRow) -> dict:
    """The API view of a stored record (ULID as the opaque public id)."""
    return {
        "id": r.ulid,
        "part_id": r.part_id,
        "process": r.process,
        "quantity": r.quantity,
        "actual_unit_cost_usd": r.actual_unit_cost_usd,
        "material_class": r.material_class,
        "shop": r.shop,
        "region": r.region,
        "currency": r.currency,
        "source": r.source,
        "source_type": r.source_type,
        "vendor_quote_id": r.vendor_quote_id,
        "invoice_date": r.invoice_date.isoformat() if r.invoice_date else None,
        "actual_machine_hours": r.actual_machine_hours,
        "actual_setup_hours": r.actual_setup_hours,
        "actual_labor_hours": r.actual_labor_hours,
        "actual_inspection_hours": r.actual_inspection_hours,
        "actual_cycle_seconds": r.actual_cycle_seconds,
        "evidence_sha256": r.evidence_sha256,
        "evidence_uri": r.evidence_uri,
        "stand_in": r.stand_in,
        "part_path": r.part_path,
        "notes": r.notes,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _row_to_gt(r: GroundTruthRecordRow) -> GroundTruthRecord:
    """DB row -> the dataclass the costing loop consumes (validates on build).

    Threads the (nullable) MEASURED geometry through so a record that carries it
    can activate the analogy-to-quote k-NN member (``geometry_features`` property);
    a row with NULL geometry stays skippable by the analogy exactly as before.
    """
    return GroundTruthRecord(
        part_id=r.part_id,
        process=r.process,
        quantity=int(r.quantity),
        actual_unit_cost_usd=float(r.actual_unit_cost_usd),
        material_class=r.material_class or "polymer",
        shop=r.shop,
        region=r.region,
        currency=r.currency or "USD",
        source=r.source or "",
        source_type=r.source_type or "actual",
        vendor_quote_id=r.vendor_quote_id,
        invoice_date=(r.invoice_date.isoformat() if r.invoice_date else None),
        actual_machine_hours=r.actual_machine_hours,
        actual_setup_hours=r.actual_setup_hours,
        actual_labor_hours=r.actual_labor_hours,
        actual_inspection_hours=r.actual_inspection_hours,
        actual_cycle_seconds=r.actual_cycle_seconds,
        evidence_sha256=r.evidence_sha256,
        evidence_uri=r.evidence_uri,
        stand_in=bool(r.stand_in),
        part_path=r.part_path,
        notes=r.notes or "",
        volume_cm3=(float(r.volume_cm3) if r.volume_cm3 is not None else None),
        surface_area_cm2=(float(r.surface_area_cm2)
                          if r.surface_area_cm2 is not None else None),
        max_bbox_mm=(float(r.max_bbox_mm) if r.max_bbox_mm is not None else None),
        face_count=(int(r.face_count) if r.face_count is not None else None),
    )


def _extract_geometry_features(gt: GroundTruthRecord,
                               parts_dir: Optional[str] = None) -> Optional[dict]:
    """Best-effort MEASURED geometry for a record — reuse the engine's extraction.

    Resolves the record's ``part_path``/``part_id`` to a mesh via the SAME
    parts-dir resolution the eval/recalibrate paths use (``resolve_part_path``),
    runs the canonical engine sequence, and returns the analogy k-NN feature
    mapping (``analogy_estimator.FEATURE_KEYS``) extracted from ``GeoDrivers`` —
    or None when the mesh does not resolve or extraction fails. NEVER fabricates
    and NEVER raises: a geometry failure must not fail the ingest (caller stores
    None). CPU-bound (loads + analyses the mesh); async callers run it in an
    executor.
    """
    from src.costing.groundtruth import resolve_part_path

    if parts_dir is None:
        # Read the trusted-corpus dir FRESH from the env (not an import-time
        # constant) so the resolution honours the deployed configuration. This
        # is the ONLY dir a network record's mesh is looked up under (its
        # part_path was already confined to a safe relative name at ingest).
        parts_dir = os.environ.get("CADVERIFY_PARTS_DIR")
    path = resolve_part_path(gt, parts_dir)
    if path is None:
        return None
    try:
        from src.costing.cli import _run_engine
        from src.costing.drivers import extract_drivers

        result, mesh, feats = _run_engine(path)
        dr = extract_drivers(result.geometry, mesh, feats)
        vol = float(dr.volume_cm3)
        area = float(dr.surface_area_cm2)
        bbox = float(dr.max_bbox_mm)
        faces = int(dr.face_count)
        # The analogy vector needs every driver positive (analogy_estimator._vector);
        # an unmeasurable part stays None so the k-NN honestly skips it.
        if vol <= 0.0 or area <= 0.0 or bbox <= 0.0 or faces <= 0:
            return None
        return {
            "volume_cm3": vol,
            "surface_area_cm2": area,
            "max_bbox_mm": bbox,
            "face_count": faces,
        }
    except Exception as exc:  # best-effort — never fail an ingest on geometry
        logger.warning(
            "ground-truth geometry extraction failed for part_id=%s: %s",
            gt.part_id, exc,
        )
        return None


# ── ingest / read (org-scoped) ───────────────────────────────────────────────
async def ingest_record(
    session: AsyncSession, org_id: str, user_id: Optional[int], payload: dict,
    *, parts_dir: Optional[str] = None,
) -> GroundTruthRecordRow:
    """Insert ONE org-scoped ground-truth record.

    Validates through the ``GroundTruthRecord`` dataclass first, so the API can
    never persist a record the costing layer would reject (positive cost,
    non-empty part_id, ...). Dedup: last write wins on
    ``(org_id, part_id, process, quantity, shop)`` — mirrors
    ``groundtruth.add_record``. Does NOT commit; the caller owns the txn.

    P1 analogy feed: when the record's ``part_path``/``part_id`` resolves to a
    mesh, the MEASURED geometry (``analogy_estimator.FEATURE_KEYS``) is extracted
    from it and stored so the record can activate the analogy-to-quote k-NN
    member. Best-effort and NON-FATAL: no resolvable mesh / extraction failure
    leaves the geometry NULL (the analogy simply skips the record) — the ingest
    still succeeds. Geometry is never fabricated. The CSV bulk path
    (``import_records``) funnels through here, so it inherits this unchanged.
    """
    source_type = _normal_payload_source_type(payload)
    stand_in = bool(payload.get("stand_in", False)) or _is_synthetic_source_type(source_type)
    invoice_date = _normal_invoice_date(payload.get("invoice_date"))
    evidence_sha256 = _normal_evidence_sha256(payload.get("evidence_sha256"))

    gt = GroundTruthRecord(
        part_id=payload["part_id"],
        process=payload["process"],
        quantity=int(payload["quantity"]),
        actual_unit_cost_usd=float(payload["actual_unit_cost_usd"]),
        material_class=payload.get("material_class") or "polymer",
        shop=payload.get("shop"),
        region=payload.get("region"),
        currency=payload.get("currency") or "USD",
        source=payload.get("source") or "",
        source_type=source_type,
        vendor_quote_id=payload.get("vendor_quote_id"),
        invoice_date=invoice_date.isoformat() if invoice_date else None,
        actual_machine_hours=payload.get("actual_machine_hours"),
        actual_setup_hours=payload.get("actual_setup_hours"),
        actual_labor_hours=payload.get("actual_labor_hours"),
        actual_inspection_hours=payload.get("actual_inspection_hours"),
        actual_cycle_seconds=payload.get("actual_cycle_seconds"),
        evidence_sha256=evidence_sha256,
        evidence_uri=payload.get("evidence_uri"),
        stand_in=stand_in,
        # network-supplied path is confined to a safe relative corpus path
        # (raises UnsafePartPath -> ValueError -> the API maps it to 400).
        part_path=sanitize_part_path(payload.get("part_path")),
        notes=payload.get("notes") or "",
    )

    # Best-effort MEASURED geometry (off the event loop — CPU-bound mesh analysis).
    # None when the mesh does not resolve or extraction fails => geometry stays
    # NULL and the analogy k-NN skips this record; the ingest is never failed.
    # Bounded by a timeout so a pathological/slow mesh can never hang a worker
    # thread indefinitely (defense-in-depth alongside the part_path confinement).
    try:
        geom = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None, _extract_geometry_features, gt, parts_dir
            ),
            timeout=_GEOM_EXTRACT_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "ground-truth geometry extraction timed out for part_id=%.60s — "
            "storing record with NULL geometry (analogy skips it)",
            gt.part_id,
        )
        geom = None

    # last-wins dedup within the org
    await session.execute(
        delete(GroundTruthRecordRow).where(
            GroundTruthRecordRow.org_id == org_id,
            GroundTruthRecordRow.part_id == gt.part_id,
            GroundTruthRecordRow.process == gt.process,
            GroundTruthRecordRow.quantity == int(gt.quantity),
            func.coalesce(GroundTruthRecordRow.shop, "") == (gt.shop or ""),
        )
    )
    row = GroundTruthRecordRow(
        org_id=org_id,
        user_id=user_id,
        part_id=gt.part_id,
        process=gt.process,
        quantity=int(gt.quantity),
        actual_unit_cost_usd=float(gt.actual_unit_cost_usd),
        material_class=gt.material_class,
        shop=gt.shop,
        region=gt.region,
        currency=gt.currency,
        source=gt.source,
        source_type=gt.source_type,
        vendor_quote_id=gt.vendor_quote_id,
        invoice_date=invoice_date,
        actual_machine_hours=gt.actual_machine_hours,
        actual_setup_hours=gt.actual_setup_hours,
        actual_labor_hours=gt.actual_labor_hours,
        actual_inspection_hours=gt.actual_inspection_hours,
        actual_cycle_seconds=gt.actual_cycle_seconds,
        evidence_sha256=evidence_sha256,
        evidence_uri=gt.evidence_uri,
        stand_in=gt.stand_in,
        part_path=gt.part_path,
        notes=gt.notes,
        volume_cm3=(geom or {}).get("volume_cm3"),
        surface_area_cm2=(geom or {}).get("surface_area_cm2"),
        max_bbox_mm=(geom or {}).get("max_bbox_mm"),
        face_count=(geom or {}).get("face_count"),
    )
    session.add(row)
    await session.flush()
    return row


async def list_records(session: AsyncSession, org_id: str) -> list:
    stmt = (
        select(GroundTruthRecordRow)
        .where(GroundTruthRecordRow.org_id == org_id)
        .order_by(
            GroundTruthRecordRow.created_at.desc(),
            GroundTruthRecordRow.id.desc(),
        )
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_record(
    session: AsyncSession, org_id: str, ulid: str
) -> Optional[GroundTruthRecordRow]:
    stmt = select(GroundTruthRecordRow).where(
        GroundTruthRecordRow.org_id == org_id,
        GroundTruthRecordRow.ulid == ulid,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def load_org_ground_truth(session: AsyncSession, org_id: str) -> list:
    """All of ONE org's records as costing dataclasses (the recalibration feed)."""
    return [_row_to_gt(r) for r in await list_records(session, org_id)]


# ── recalibration trigger (item 4) ───────────────────────────────────────────
def recalibrate_from_records(
    org_id: str,
    records: list,
    *,
    parts_dir: Optional[str] = None,
    store_dir: Optional[str] = None,
    test_fraction: float = 0.30,
    seed: int = 1337,
    cache=None,
) -> dict:
    """Re-run the ground-truth loop over an org's records and REFRESH the served
    calibration bundle on disk. Pure orchestration around ``run_loop`` — no new
    math. Returns a summary; the persisted bundle is what ``/validate/cost``
    loads. CPU-bound (drives the engine); callers on the event loop should run
    this in an executor (see ``recalibrate_org``).

    ``parts_dir`` defaults to the configured engine parts dir so a record that
    carries only a ``part_id`` (STL filename) resolves against it; a record that
    carries an explicit ``part_path`` resolves regardless.

    HONESTY GATE (item 3): refuses with ``InsufficientGroundTruth`` — BEFORE the
    engine ever runs — when fewer than ``MIN_REAL_RECORDS`` real (non-stand-in)
    records are present. A calibration is emitted ONLY from sufficient REAL data;
    stand-in records never count toward the floor and can never earn a served,
    validated calibration.
    """
    real = [r for r in records if not getattr(r, "stand_in", True)]
    if len(real) < MIN_REAL_RECORDS:
        raise InsufficientGroundTruth(
            n_real=len(real), n_records=len(records), min_real=MIN_REAL_RECORDS
        )
    if parts_dir is None:
        # Fresh env read (deployed-config honouring), same as ingest extraction.
        parts_dir = os.environ.get("CADVERIFY_PARTS_DIR")
    loop = run_loop(
        records,
        parts_dir=parts_dir,
        test_fraction=test_fraction,
        seed=seed,
        cache=cache,
    )
    he = loop.heldout_eval
    # A real row is not enough by itself: the served empirical interval needs
    # MIN_RESIDUALS costable REAL rows on the held-out side.  Bind this same
    # threshold to both the API's validated flag and the durable bundle so the
    # UI can never report success while /validate/cost silently falls back to
    # an assumption band.
    validated = (
        he.metrics_real is not None
        and he.n_real >= MIN_RESIDUALS
        and loop.residual_model.from_real
    )
    bundle = cstore.CalibrationBundle(
        org_id=org_id,
        calibration=loop.calibration,
        residuals=he.residuals,
        from_real=bool(validated),
        n_records=loop.n_records,
        n_real=he.n_real,
        n_standin=he.n_standin,
        heldout_metrics_real=he.metrics_real,
        claim=he.claim,
        fitted_on=loop.calibration.fitted_on,
    )
    path = cstore.save_bundle(bundle, store_dir=store_dir)
    return {
        "org_id": org_id,
        "n_records": loop.n_records,
        "n_real": he.n_real,
        "n_standin": he.n_standin,
        "n_skipped": len(loop.skipped),
        "skipped": [
            {
                "part_id": item.part_id,
                "process": item.process,
                "quantity": int(item.quantity),
                "reason": reason,
            }
            for item, reason in loop.skipped[:25]
        ],
        "from_real": bool(validated),
        "validated": bool(validated),
        "claim": he.claim,
        "calibration": loop.calibration.to_dict(),
        "heldout_metrics_real": he.metrics_real,
        "saved_path": path,
    }


async def recalibrate_org(
    session: AsyncSession,
    org_id: str,
    *,
    parts_dir: Optional[str] = None,
    store_dir: Optional[str] = None,
) -> dict:
    """Load an org's records (async) then run the CPU-bound loop off the event
    loop, refreshing the served bundle. The manual/callable recalibration
    trigger (an async cron wrapper is a separate concern)."""
    records = await load_org_ground_truth(session, org_id)
    ev = asyncio.get_event_loop()

    # Historical actuals can bind to source CAD by ``evidence_sha256``. The
    # source bytes were durably captured by a successful Verify/Should-cost run
    # and remain tenant-scoped in object storage. Materialize only for the
    # bounded calibration call because the costing engine consumes file paths;
    # no provider locator or cross-tenant key enters the record/API response.
    evidence_records = [r for r in records if r.evidence_sha256]
    if not evidence_records:
        return await ev.run_in_executor(
            None,
            lambda: recalibrate_from_records(
                org_id, records, parts_dir=parts_dir, store_dir=store_dir
            ),
        )

    from src.costing.groundtruth import resolve_part_path
    from src.services.source_artifact_service import read_costable_mesh_artifact
    from src.storage import ObjectNotFoundError

    with TemporaryDirectory(prefix="proofshape-calibration-") as temp_root:
        materialized: dict[str, tuple[str, str] | None] = {}
        resolved_records: list[GroundTruthRecord] = []
        for record in records:
            digest = (record.evidence_sha256 or "").lower()
            if digest:
                if digest not in materialized:
                    try:
                        payload = await read_costable_mesh_artifact(org_id, digest)
                    except ObjectNotFoundError:
                        materialized[digest] = None
                    else:
                        name = f"source-{digest}.stl"
                        Path(temp_root, name).write_bytes(payload)
                        materialized[digest] = (name, ".stl")
                source = materialized[digest]
                if source is not None:
                    resolved_records.append(replace(record, part_path=source[0]))
                    continue

            # Preserve an explicitly configured operator corpus for records not
            # bound to a durable source artifact (or for a missing legacy blob).
            existing = resolve_part_path(record, parts_dir)
            resolved_records.append(
                replace(record, part_path=existing) if existing else record
            )

        return await ev.run_in_executor(
            None,
            lambda: recalibrate_from_records(
                org_id,
                resolved_records,
                parts_dir=temp_root,
                store_dir=store_dir,
            ),
        )


# ── serve (item 2/3) ─────────────────────────────────────────────────────────
def load_served_calibration(org_id: str, store_dir: Optional[str] = None):
    """Load the org's persisted served CI binding: ``(ResidualModel, Calibration)``.

    Called at ``/validate/cost`` time. Pure local disk read — no DB, no network.
    ``(None, None)`` => never calibrated => the caller leaves both unset => the CI
    is the assumption band (byte-identical to pre-W5 behaviour).

    Honesty seam / coherence rail — the ``Calibration`` is returned ONLY when the
    bundle carries REAL held-out residuals (``from_real``). The served point is
    corrected by ``calibration.factor_for(process)`` BEFORE it enters
    ``confidence_interval`` — mirroring how ``run_loop`` measures residuals on the
    CORRECTED prediction (``corrected = baseline × factor``; ``groundtruth.py``
    ``_residuals``). Without real ground truth the calibration stays ``None`` so
    the point is UNCORRECTED and the band is byte-identical to today's assumption
    band / stand-in spread — a stand-in bundle cannot move the served number.
    """
    bundle = cstore.load_bundle(org_id, store_dir=store_dir)
    if bundle is None:
        return None, None
    model = bundle.residual_model()
    # ``bundle.from_real`` is the durable release gate, not merely a redundant
    # copy of ResidualModel.from_real.  It is false for under-powered real
    # recalibrations (< 3 held-out residuals), which must not tune the served
    # point or masquerade as an empirical band after a restart.
    if not bundle.from_real and model.from_real:
        return None, None
    # Only a REAL (measured) residual model earns a corrected point; a stand-in
    # spread stays centred on the uncorrected baseline exactly as before.
    calibration = bundle.calibration if model.from_real else None
    return model, calibration


def load_served_residual_model(org_id: str, store_dir: Optional[str] = None):
    """Back-compat shim: the served ``ResidualModel`` alone (None if uncalibrated).

    Prefer ``load_served_calibration`` at the served path — it also returns the
    Calibration needed to correct the point so the MEASURED band stays coherent
    with its centre.
    """
    return load_served_calibration(org_id, store_dir=store_dir)[0]
