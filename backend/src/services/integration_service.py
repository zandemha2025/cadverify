"""Offline connector registry and run ledger.

P6 starts with apparatus, not fake live SAP/PLM credentials. Connectors here are
file-fed contracts that reuse the production CSV importers, record a durable run
ledger, and deliberately do not store raw CSV by default.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.db.models import IntegrationRun
from src.services import groundtruth_service, manifest_service

MODE_DRY_RUN = "dry_run"
MODE_IMPORT = "import"
VALID_MODES = {MODE_DRY_RUN, MODE_IMPORT}

CONNECTOR_MODE_OFFLINE_CSV = "offline_csv"
CONNECTOR_MODE_SANDBOX_API = "sandbox_api"
CONNECTOR_MODE_LIVE_READONLY = "live_readonly"
CONNECTOR_MODE_LIVE_WRITE_DRAFT = "live_write_draft"
CONNECTOR_MODE_LIVE_SEND = "live_send"
VALID_CONNECTOR_MODES = {
    CONNECTOR_MODE_OFFLINE_CSV,
    CONNECTOR_MODE_SANDBOX_API,
    CONNECTOR_MODE_LIVE_READONLY,
    CONNECTOR_MODE_LIVE_WRITE_DRAFT,
    CONNECTOR_MODE_LIVE_SEND,
}

BOUNDARY_SIMULATION = "simulation"
BOUNDARY_EXPORTED_FIXTURE = "exported_fixture"
BOUNDARY_SANDBOX = "sandbox"
BOUNDARY_LIVE_READONLY = "live_readonly"
BOUNDARY_DRAFT_WRITE = "draft_write"
BOUNDARY_LIVE_SEND = "live_send"
VALID_BOUNDARY_LABELS = {
    BOUNDARY_SIMULATION,
    BOUNDARY_EXPORTED_FIXTURE,
    BOUNDARY_SANDBOX,
    BOUNDARY_LIVE_READONLY,
    BOUNDARY_DRAFT_WRITE,
    BOUNDARY_LIVE_SEND,
}

STATUS_PASSED = "passed"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
VALID_STATUSES = {STATUS_PASSED, STATUS_PARTIAL, STATUS_FAILED}

SOURCE_MANIFEST = "manifest"
SOURCE_GROUND_TRUTH = "ground_truth"


@dataclass(frozen=True)
class Connector:
    id: str
    label: str
    source_system: str
    source_kind: str
    file_format: str
    mode: str
    boundary_label: str
    description: str
    template_endpoint: str
    raw_payload_stored: bool = False
    configured: bool = True
    live_credentials_required: bool = False
    api_name: str | None = None
    api_version: str | None = None


CONNECTORS: tuple[Connector, ...] = (
    Connector(
        id="sap_manifest_csv",
        label="SAP manifest CSV",
        source_system="SAP ERP",
        source_kind=SOURCE_MANIFEST,
        file_format="csv",
        mode=CONNECTOR_MODE_OFFLINE_CSV,
        boundary_label=BOUNDARY_EXPORTED_FIXTURE,
        description="Declared part, demand, program, and material export.",
        template_endpoint="/api/v1/manifest/import/template",
    ),
    Connector(
        id="plm_manifest_csv",
        label="PLM manifest CSV",
        source_system="PLM",
        source_kind=SOURCE_MANIFEST,
        file_format="csv",
        mode=CONNECTOR_MODE_OFFLINE_CSV,
        boundary_label=BOUNDARY_EXPORTED_FIXTURE,
        description="Declared part registry export from a PLM/BOM system.",
        template_endpoint="/api/v1/manifest/import/template",
    ),
    Connector(
        id="ground_truth_csv",
        label="Quote/actuals CSV",
        source_system="Supplier quotes / ERP actuals",
        source_kind=SOURCE_GROUND_TRUTH,
        file_format="csv",
        mode=CONNECTOR_MODE_OFFLINE_CSV,
        boundary_label=BOUNDARY_EXPORTED_FIXTURE,
        description="Historical quote, invoice, or actual-cost export.",
        template_endpoint="/api/v1/ground-truth/import/template",
    ),
    Connector(
        id="sap_s4hana_product_bom_readonly",
        label="SAP S/4HANA Product/BOM read-only",
        source_system="SAP S/4HANA",
        source_kind=SOURCE_MANIFEST,
        file_format="odata",
        mode=CONNECTOR_MODE_SANDBOX_API,
        boundary_label=BOUNDARY_SANDBOX,
        description="Read-only product/material and BOM adapter for vendor or customer sandbox tenants.",
        template_endpoint="",
        configured=False,
        live_credentials_required=True,
        api_name="SAP S/4HANA Product/BOM OData",
        api_version="sandbox-readonly",
    ),
    Connector(
        id="windchill_part_bom_readonly",
        label="PTC Windchill Part/BOM read-only",
        source_system="PTC Windchill",
        source_kind=SOURCE_MANIFEST,
        file_format="odata",
        mode=CONNECTOR_MODE_SANDBOX_API,
        boundary_label=BOUNDARY_SANDBOX,
        description="Read-only part, revision, and BOM adapter for Windchill sandbox tenants.",
        template_endpoint="",
        configured=False,
        live_credentials_required=True,
        api_name="PTC Windchill REST Product Management",
        api_version="sandbox-readonly",
    ),
)

CONNECTOR_BY_ID = {c.id: c for c in CONNECTORS}


def list_connectors() -> list[dict[str, Any]]:
    return [asdict(c) for c in CONNECTORS]


def get_connector(connector_id: str) -> Connector:
    connector = CONNECTOR_BY_ID.get((connector_id or "").strip())
    if connector is None:
        raise HTTPException(status_code=404, detail="integration connector not found")
    return connector


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _status(rows_valid: int, errors: list[dict[str, Any]]) -> str:
    if rows_valid > 0 and not errors:
        return STATUS_PASSED
    if rows_valid > 0:
        return STATUS_PARTIAL
    return STATUS_FAILED


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded text.") from exc


def _safe_errors(errors: list[dict[str, Any]], *, limit: int = 200) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for err in errors[:limit]:
        safe.append({
            "line": err.get("line"),
            "index": err.get("index"),
            "reason": str(err.get("reason", ""))[:1000],
        })
    if len(errors) > limit:
        safe.append({
            "line": None,
            "index": None,
            "reason": f"{len(errors) - limit} additional error(s) truncated",
        })
    return safe


async def run_connector_csv(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: Optional[int],
    connector_id: str,
    raw: bytes,
    filename: Optional[str] = None,
    mode: str = MODE_DRY_RUN,
) -> IntegrationRun:
    """Parse an offline CSV feed and optionally execute the matching import.

    The run row is always persisted. The raw CSV bytes are hashed/counts-only and
    never stored. ``mode=import`` delegates to the existing production importer;
    ``mode=dry_run`` only parses and records what would happen.
    """
    connector = get_connector(connector_id)
    if mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail="mode must be dry_run or import")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty CSV upload")

    text = _decode(raw)
    file_hash = hashlib.sha256(raw).hexdigest()

    imported = 0
    updated = 0
    import_errors: list[dict[str, Any]] = []

    if connector.source_kind == SOURCE_MANIFEST:
        rows, parse_errors = manifest_service.parse_manifest_csv(text)
        if mode == MODE_IMPORT and rows:
            summary = await manifest_service.import_manifest(
                session, org_id, user_id, rows
            )
            imported = int(summary["imported"])
            updated = int(summary["updated"])
            import_errors = list(summary["errors"])
    elif connector.source_kind == SOURCE_GROUND_TRUTH:
        rows, parse_errors = groundtruth_service.parse_ground_truth_csv(text)
        if mode == MODE_IMPORT and rows:
            imported, import_errors = await groundtruth_service.import_records(
                session, org_id, user_id, rows
            )
    else:  # pragma: no cover - registry construction keeps this unreachable.
        raise HTTPException(status_code=400, detail="unsupported connector source kind")

    all_errors = _safe_errors(list(parse_errors) + list(import_errors))
    rows_total = len(rows) + len(parse_errors)
    rows_valid = len(rows)
    rows_invalid = len(parse_errors) + len(import_errors)
    skipped = rows_total - rows_valid + len(import_errors)
    status = _status(rows_valid, all_errors)

    run = IntegrationRun(
        ulid=str(ULID()),
        org_id=org_id,
        user_id=user_id,
        connector_id=connector.id,
        connector_mode=connector.mode,
        boundary_label=connector.boundary_label,
        source_system=connector.source_system,
        source_kind=connector.source_kind,
        api_name=connector.api_name,
        api_version=connector.api_version,
        mode=mode,
        status=status,
        filename=(filename or None),
        file_sha256=file_hash,
        file_size_bytes=len(raw),
        source_record_count=rows_total,
        normalized_record_count=rows_valid,
        rows_total=rows_total,
        rows_valid=rows_valid,
        rows_invalid=rows_invalid,
        imported_count=imported if mode == MODE_IMPORT else 0,
        updated_count=updated if mode == MODE_IMPORT else 0,
        skipped_count=max(0, skipped),
        raw_stored=False,
        errors_json=all_errors or None,
        metadata_json={
            "connector_label": connector.label,
            "template_endpoint": connector.template_endpoint,
            "file_format": connector.file_format,
            "live_credentials_required": connector.live_credentials_required,
            "proof_boundary": connector.boundary_label,
            "promotion_rule": "simulation -> exported_fixture -> sandbox -> live_readonly -> draft_write -> live_send",
        },
        completed_at=_now(),
    )
    session.add(run)
    await session.flush()
    return run


async def list_runs(
    session: AsyncSession,
    *,
    org_id: str,
    limit: int = 50,
    cursor: Optional[int] = None,
    connector_id: Optional[str] = None,
    status: Optional[str] = None,
) -> tuple[list[IntegrationRun], bool]:
    limit = max(1, min(int(limit), 100))
    stmt = select(IntegrationRun).where(IntegrationRun.org_id == org_id)
    if cursor is not None:
        stmt = stmt.where(IntegrationRun.id < cursor)
    if connector_id:
        stmt = stmt.where(IntegrationRun.connector_id == connector_id)
    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="invalid integration run status")
        stmt = stmt.where(IntegrationRun.status == status)
    stmt = stmt.order_by(IntegrationRun.id.desc()).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    return rows[:limit], len(rows) > limit


async def get_run(
    session: AsyncSession,
    *,
    org_id: str,
    run_id: str,
) -> IntegrationRun:
    row = (
        await session.execute(
            select(IntegrationRun).where(
                IntegrationRun.org_id == org_id,
                IntegrationRun.ulid == run_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="integration run not found")
    return row


def serialize_run(row: IntegrationRun) -> dict[str, Any]:
    return {
        "id": row.ulid,
        "connector_id": row.connector_id,
        "connector_mode": row.connector_mode,
        "boundary_label": row.boundary_label,
        "source_system": row.source_system,
        "source_kind": row.source_kind,
        "api_name": row.api_name,
        "api_version": row.api_version,
        "external_tenant_hash": row.external_tenant_hash,
        "correlation_ids": row.correlation_ids_json or [],
        "watermark": row.watermark,
        "idempotency_key": row.idempotency_key,
        "mode": row.mode,
        "status": row.status,
        "filename": row.filename,
        "file_sha256": row.file_sha256,
        "file_size_bytes": row.file_size_bytes,
        "source_record_count": row.source_record_count,
        "normalized_record_count": row.normalized_record_count,
        "rows_total": row.rows_total,
        "rows_valid": row.rows_valid,
        "rows_invalid": row.rows_invalid,
        "imported_count": row.imported_count,
        "updated_count": row.updated_count,
        "skipped_count": row.skipped_count,
        "raw_stored": row.raw_stored,
        "errors": row.errors_json or [],
        "metadata": row.metadata_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }
