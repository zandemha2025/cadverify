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
    assert len(run.file_sha256) == 64
    assert "missing part_id" in run.errors_json[0]["reason"]
    assert "connector_label" in run.metadata_json
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
    }
    assert all(c["mode"] == "offline_csv" for c in connectors)
    assert all(c["raw_payload_stored"] is False for c in connectors)
    assert all(c["live_credentials_required"] is False for c in connectors)
