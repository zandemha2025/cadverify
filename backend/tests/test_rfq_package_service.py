from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.auth.require_api_key import AuthedUser
from src.db.models import CostDecision, RfqPackage
from src.services import rfq_package_service as svc


class _Result:
    def __init__(self, *, rows=None, first=None):
        self._rows = rows or []
        self._first = first

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._first


def _decision(**overrides) -> CostDecision:
    now = datetime.now(timezone.utc)
    d = CostDecision(
        id=overrides.get("id", 1),
        ulid=overrides.get("ulid", "01RFQDECISION"),
        org_id=overrides.get("org_id", "org_1"),
        user_id=overrides.get("user_id", 11),
        mesh_hash=overrides.get("mesh_hash", "meshhash"),
        params_hash="paramhash",
        engine_version="test",
        filename=overrides.get("filename", "VALVE-100.step"),
        file_type="step",
        result_json=overrides.get(
            "result_json",
            {
                "estimates": [
                    {
                        "process": "cnc",
                        "material": "steel",
                        "quantity": 100,
                        "unit_cost_usd": 12.34,
                        "confidence": {"validated": False, "label": "assumption"},
                    }
                ],
                "decision": {"make_now_process": "cnc"},
            },
        ),
        make_now_process="cnc",
        crossover_qty=1000,
        quantities=[100],
        label=None,
        approval_status=overrides.get("approval_status", "unreviewed"),
        created_at=overrides.get("created_at", now),
    )
    d.stale_at = overrides.get("stale_at")
    d.stale_reason = overrides.get("stale_reason")
    d.approved_at = overrides.get("approved_at")
    d.approved_by_user_id = overrides.get("approved_by_user_id")
    d.approval_note = overrides.get("approval_note")
    return d


@pytest.mark.asyncio
async def test_create_package_snapshots_warnings_without_raw_cad(monkeypatch):
    decision = _decision(stale_at=datetime.now(timezone.utc) - timedelta(days=1))
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock(return_value=_Result(rows=[decision]))

    monkeypatch.setattr(svc, "resolve_org", AsyncMock(return_value="org_1"))
    monkeypatch.setattr(
        svc,
        "_manifest_match",
        AsyncMock(return_value={"match": "normalized-stem, exact", "part": {"part_id": "VALVE-100"}}),
    )
    monkeypatch.setattr(svc, "_part_context", AsyncMock(return_value={"program": "Refinery"}))
    monkeypatch.setattr(
        svc,
        "_raw_cad_payload",
        AsyncMock(return_value=(None, None, {"included": False, "reason": "not_requested"})),
    )

    package = await svc.create_package(
        session,
        AuthedUser(user_id=11, api_key_id=0, key_prefix="session", role="analyst"),
        ["01RFQDECISION"],
        svc.RfqPackageOptions(title="Pump RFQ", supplier_name="Supplier A"),
    )

    assert package.title == "Pump RFQ"
    assert package.item_count == 1
    assert package.approved_count == 0
    assert package.stale_count == 1
    assert package.unvalidated_count == 1
    assert package.raw_cad_included is False
    assert package.live_supplier_send is False
    assert package.items_json[0]["declared_part"]["part"]["part_id"] == "VALVE-100"
    assert {w["code"] for w in package.warnings_json} == {
        "decision_unapproved",
        "decision_stale",
        "confidence_unvalidated",
    }
    session.add.assert_called_once_with(package)
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_raw_cad_payload_only_reads_same_org_completed_batch_blob(tmp_path, monkeypatch):
    blob_root = tmp_path / "blobs"
    file_path = blob_root / "batch-1" / "VALVE-100.step"
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(b"STEPDATA")
    monkeypatch.setenv("BATCH_BLOB_DIR", str(blob_root))

    decision = _decision(id=99, org_id="org_1")
    item = SimpleNamespace(filename="VALVE-100.step")
    batch = SimpleNamespace(ulid="batch-1")
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_Result(first=(item, batch)))

    filename, data, meta = await svc._raw_cad_payload(session, decision, True)

    assert filename == "VALVE-100.step"
    assert data == b"STEPDATA"
    assert meta["included"] is True
    assert meta["source"] == "same_org_batch_zip_blob"


@pytest.mark.asyncio
async def test_build_zip_contains_honest_package_files(monkeypatch):
    decision = _decision()
    item = {
        "decision": {
            "id": decision.ulid,
            "filename": decision.filename,
            "approval_status": "approved",
            "is_stale": False,
            "unvalidated_confidence": True,
            "make_now_process": "cnc",
            "crossover_qty": 1000,
        },
        "cost_decision": decision.result_json,
        "declared_part": {"match": "normalized-stem, exact", "part": {"part_id": "VALVE-100"}},
        "part_context": {"program": "Refinery"},
        "raw_cad": {"included": False, "reason": "not_requested"},
    }
    package = RfqPackage(
        ulid="01RFQPACKAGE",
        org_id="org_1",
        user_id=11,
        title="Pump RFQ",
        supplier_name="Supplier A",
        item_count=1,
        approved_count=1,
        stale_count=0,
        unvalidated_count=1,
        raw_cad_included=False,
        live_supplier_send=False,
        items_json=[item],
        warnings_json=[{"code": "confidence_unvalidated", "message": "assumption band"}],
        metadata_json={"note": "Send for budgetary review"},
        created_at=datetime.now(timezone.utc),
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_Result(first=decision))
    monkeypatch.setattr(svc, "generate_cost_pdf", AsyncMock(return_value=b"%PDF-test"))

    data = await svc.build_zip(session, package)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        assert "package_manifest.json" in names
        assert "supplier-brief.md" in names
        assert "line-items.csv" in names
        assert "cost-decisions.json" in names
        assert any(name.endswith("/cost-decision.json") for name in names)
        assert any(name.endswith("/cost-drivers.csv") for name in names)
        assert any(name.endswith("/declared-part.json") for name in names)
        assert any(name.endswith("/part-context.json") for name in names)
        assert any(name.endswith("/should-cost-report.pdf") for name in names)
        assert any(name.endswith("/raw-cad-unavailable.txt") for name in names)
        manifest = json.loads(zf.read("package_manifest.json"))
        assert manifest["live_supplier_send"] is False
        assert manifest["raw_cad_included"] is False
        brief = zf.read("supplier-brief.md").decode()
        assert "not a supplier quote" in brief
