"""Tests for the offline integration connector ledger."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services import integration_service as svc


@pytest.mark.asyncio
async def test_manifest_dry_run_records_hash_counts_and_errors():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    raw = (
        "part_id,description,material_class,program\n"
        "P-100,Valve body,steel,Train A\n"
        ",Missing part,steel,Train A\n"
    ).encode()

    run = await svc.run_connector_csv(
        session,
        org_id="org_1",
        user_id=7,
        connector_id="sap_manifest_csv",
        raw=raw,
        filename="sap.csv",
    )

    assert run.connector_id == "sap_manifest_csv"
    assert run.connector_mode == "offline_csv"
    assert run.boundary_label == "exported_fixture"
    assert run.source_system == "SAP ERP"
    assert run.source_kind == "manifest"
    assert run.mode == "dry_run"
    assert run.status == "partial"
    assert run.rows_total == 2
    assert run.rows_valid == 1
    assert run.rows_invalid == 1
    assert run.imported_count == 0
    assert run.updated_count == 0
    assert run.raw_stored is False
    assert run.source_record_count == 2
    assert run.normalized_record_count == 1
    assert len(run.file_sha256) == 64
    assert "missing part_id" in run.errors_json[0]["reason"]
    assert "connector_label" in run.metadata_json
    assert run.metadata_json["proof_boundary"] == "exported_fixture"
    session.add.assert_called_once_with(run)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_manifest_import_delegates_to_manifest_importer(monkeypatch):
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    importer = AsyncMock(
        return_value={
            "imported": 1,
            "updated": 1,
            "skipped": 0,
            "total": 2,
            "errors": [],
        }
    )
    monkeypatch.setattr(svc.manifest_service, "import_manifest", importer)
    raw = (
        "part_id,description,material_class\n"
        "P-100,Valve body,steel\n"
        "P-101,Bracket,aluminum\n"
    ).encode()

    run = await svc.run_connector_csv(
        session,
        org_id="org_1",
        user_id=7,
        connector_id="plm_manifest_csv",
        raw=raw,
        filename="plm.csv",
        mode=svc.MODE_IMPORT,
    )

    assert run.status == "passed"
    assert run.imported_count == 1
    assert run.updated_count == 1
    assert run.rows_total == 2
    assert run.rows_invalid == 0
    importer.assert_awaited_once()
    args = importer.await_args.args
    assert args[1:3] == ("org_1", 7)


@pytest.mark.asyncio
async def test_ground_truth_dry_run_uses_ground_truth_parser_not_importer(monkeypatch):
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    importer = AsyncMock()
    monkeypatch.setattr(svc.groundtruth_service, "import_records", importer)
    raw = (
        "part_id,process,quantity,actual_unit_cost_usd,source_type\n"
        "P-200,sls,100,12.34,seed\n"
    ).encode()

    run = await svc.run_connector_csv(
        session,
        org_id="org_1",
        user_id=7,
        connector_id="ground_truth_csv",
        raw=raw,
        filename="actuals.csv",
    )

    assert run.status == "passed"
    assert run.rows_valid == 1
    assert run.imported_count == 0
    assert run.raw_stored is False
    importer.assert_not_called()


def test_connector_registry_declares_offline_no_raw_payloads():
    connectors = svc.list_connectors()
    assert {c["id"] for c in connectors} >= {
        "sap_manifest_csv",
        "plm_manifest_csv",
        "ground_truth_csv",
        "sap_s4hana_product_bom_readonly",
        "windchill_part_bom_readonly",
    }
    assert all(c["raw_payload_stored"] is False for c in connectors)
    csv = [c for c in connectors if c["file_format"] == "csv"]
    sandbox = [c for c in connectors if c["mode"] == "sandbox_api"]
    assert all(c["mode"] == "offline_csv" for c in csv)
    assert all(c["boundary_label"] == "exported_fixture" for c in csv)
    assert all(c["live_credentials_required"] is False for c in csv)
    assert {c["id"] for c in sandbox} == {
        "sap_s4hana_product_bom_readonly",
        "windchill_part_bom_readonly",
    }
    assert all(c["boundary_label"] == "sandbox" for c in sandbox)
    assert all(c["configured"] is False for c in sandbox)
    assert all(c["live_credentials_required"] is True for c in sandbox)


def test_serialize_run_includes_connector_promotion_boundary():
    row = MagicMock()
    row.ulid = "01TEST"
    row.connector_id = "sap_manifest_csv"
    row.connector_mode = "offline_csv"
    row.boundary_label = "exported_fixture"
    row.source_system = "SAP ERP"
    row.source_kind = "manifest"
    row.api_name = None
    row.api_version = None
    row.external_tenant_hash = None
    row.correlation_ids_json = None
    row.watermark = None
    row.idempotency_key = "idem-1"
    row.mode = "dry_run"
    row.status = "passed"
    row.filename = "sap.csv"
    row.file_sha256 = "a" * 64
    row.file_size_bytes = 100
    row.source_record_count = 3
    row.normalized_record_count = 3
    row.rows_total = 3
    row.rows_valid = 3
    row.rows_invalid = 0
    row.imported_count = 0
    row.updated_count = 0
    row.skipped_count = 0
    row.raw_stored = False
    row.errors_json = None
    row.metadata_json = {"proof_boundary": "exported_fixture"}
    row.created_at = None
    row.completed_at = None

    body = svc.serialize_run(row)

    assert body["connector_mode"] == "offline_csv"
    assert body["boundary_label"] == "exported_fixture"
    assert body["source_record_count"] == 3
    assert body["normalized_record_count"] == 3
    assert body["correlation_ids"] == []
