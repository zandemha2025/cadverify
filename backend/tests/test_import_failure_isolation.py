"""A rejected row must not erase its predecessor or abort later import rows."""
import os

import pytest
from sqlalchemy import select
from ulid import ULID

from src.db import engine
from src.db.models import GroundTruthRecordRow, ManifestPart, Organization
from src.services import groundtruth_service, integration_service, manifest_service


@pytest.mark.skipif(not os.getenv("DATABASE_URL", "").startswith("postgresql"), reason="requires local Postgres")
@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["manifest", "ground_truth"])
async def test_rejected_replacement_preserves_original_and_good_rows(kind, monkeypatch):
    monkeypatch.setattr(groundtruth_service, "_extract_geometry_features", lambda *args: None)
    org_id = str(ULID())
    try:
        async with engine.get_session_factory()() as session:
            session.add(Organization(id=org_id, name="Import rollback check", slug=f"import-{org_id.lower()}"))
            await session.flush()
            if kind == "manifest":
                model = ManifestPart
                original = manifest_service.parse_manifest_csv("part_id,quantity\nexisting,7\n")[0][0]
                importer = manifest_service.import_manifest
                field, bad = "quantity", 2**31
            else:
                model = GroundTruthRecordRow
                original = groundtruth_service.parse_ground_truth_csv(
                    "part_id,process,quantity,actual_unit_cost_usd,source_type,notes\n"
                    "existing,sls,7,12,seed,original\n"
                )[0][0]
                importer = groundtruth_service.import_records
                field, bad = "notes", "invalid\x00text"
            await importer(session, org_id, None, [original])
            result = await importer(session, org_id, None, [
                {**original, "part_id": "before"},
                {**original, field: bad},
                {**original, "part_id": "after"},
            ])
            if kind == "manifest":
                assert (result["imported"], result["updated"], result["skipped"]) == (2, 0, 1)
                errors = result["errors"]
            else:
                assert result[0] == 2
                errors = result[1]
            assert len(errors) == 1 and errors[0]["index"] == 1
            assert "INSERT" not in errors[0]["reason"] and "UPDATE" not in errors[0]["reason"]
            assert "invalid" not in errors[0]["reason"], "database errors must not echo uploaded values"
            rows = (await session.execute(select(model).where(model.org_id == org_id))).scalars().all()
            assert {row.part_id for row in rows} == {"before", "existing", "after"}
            existing = next(row for row in rows if row.part_id == "existing")
            assert existing.quantity == 7
            if kind == "ground_truth":
                assert existing.notes == "original"
            await session.rollback()  # Isolated test data, including the org, never commits.
    finally:
        await engine.dispose_engine()


def test_manifest_dry_run_rejects_unstorable_integer():
    rows, errors = manifest_service.parse_manifest_csv(
        "part_id,units_per_parent,annual_volume,quantity\n"
        "max,2147483647,2147483647,2147483647\n"
        "too-many,2147483648,2147483648,2147483648\n"
    )
    assert [row["part_id"] for row in rows] == ["max"]
    assert errors[0]["line"] == 3
    assert all(name in errors[0]["reason"] for name in ("units_per_parent", "annual_volume", "quantity"))


@pytest.mark.asyncio
async def test_run_counts_do_not_call_failed_writes_valid(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    session = AsyncMock()
    session.add = MagicMock()
    monkeypatch.setattr(manifest_service, "import_manifest", AsyncMock(return_value={
        "imported": 0, "updated": 0, "errors": [{"index": 0, "reason": "The row could not be saved."}],
    }))
    run = await integration_service.run_connector_csv(
        session, org_id="org", user_id=None, connector_id="sap_manifest_csv",
        raw=b"part_id\nrejected\n", mode="import",
    )
    assert run.status == "failed"
    assert (run.rows_total, run.rows_valid, run.rows_invalid, run.skipped_count) == (1, 0, 1, 1)
    assert run.normalized_record_count == 1
