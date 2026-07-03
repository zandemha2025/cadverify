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
import logging
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.costing import calibration_store as cstore
from src.costing.groundtruth import GroundTruthRecord, run_loop
from src.db.models import GroundTruthRecordRow

logger = logging.getLogger("cadverify.groundtruth")


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
        "stand_in": r.stand_in,
        "part_path": r.part_path,
        "notes": r.notes,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _row_to_gt(r: GroundTruthRecordRow) -> GroundTruthRecord:
    """DB row -> the dataclass the costing loop consumes (validates on build)."""
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
        stand_in=bool(r.stand_in),
        part_path=r.part_path,
        notes=r.notes or "",
    )


# ── ingest / read (org-scoped) ───────────────────────────────────────────────
async def ingest_record(
    session: AsyncSession, org_id: str, user_id: Optional[int], payload: dict
) -> GroundTruthRecordRow:
    """Insert ONE org-scoped ground-truth record.

    Validates through the ``GroundTruthRecord`` dataclass first, so the API can
    never persist a record the costing layer would reject (positive cost,
    non-empty part_id, ...). Dedup: last write wins on
    ``(org_id, part_id, process, quantity, shop)`` — mirrors
    ``groundtruth.add_record``. Does NOT commit; the caller owns the txn.
    """
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
        stand_in=bool(payload.get("stand_in", False)),
        part_path=payload.get("part_path"),
        notes=payload.get("notes") or "",
    )
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
        stand_in=gt.stand_in,
        part_path=gt.part_path,
        notes=gt.notes,
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
    """
    if parts_dir is None:
        from src.costing.harness import PARTS_DIR_DEFAULT
        parts_dir = PARTS_DIR_DEFAULT
    loop = run_loop(
        records,
        parts_dir=parts_dir,
        test_fraction=test_fraction,
        seed=seed,
        cache=cache,
    )
    he = loop.heldout_eval
    bundle = cstore.CalibrationBundle(
        org_id=org_id,
        calibration=loop.calibration,
        residuals=he.residuals,
        from_real=loop.residual_model.from_real,
        n_records=loop.n_records,
        n_real=he.n_real,
        n_standin=he.n_standin,
        heldout_metrics_real=he.metrics_real,
        claim=he.claim,
        fitted_on=loop.calibration.fitted_on,
    )
    path = cstore.save_bundle(bundle, store_dir=store_dir)
    # validated ONLY when there are REAL held-out residuals to measure against.
    validated = he.metrics_real is not None and loop.residual_model.from_real
    return {
        "org_id": org_id,
        "n_records": loop.n_records,
        "n_real": he.n_real,
        "n_standin": he.n_standin,
        "n_skipped": len(loop.skipped),
        "from_real": loop.residual_model.from_real,
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
    return await ev.run_in_executor(
        None,
        lambda: recalibrate_from_records(
            org_id, records, parts_dir=parts_dir, store_dir=store_dir
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
