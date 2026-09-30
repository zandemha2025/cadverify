from __future__ import annotations

import hashlib
import io
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import trimesh

from src.costing.groundtruth import GroundTruthRecord
from src.services import groundtruth_service
from src.services.source_artifact_service import (
    artifact_key,
    read_costable_mesh_artifact,
    read_source_artifact,
    save_costable_mesh_artifact,
    save_source_artifact,
)
from src.storage import ObjectNotFoundError


ROOT = Path(__file__).resolve().parents[2]
CUBE_STEP = ROOT / "backend" / "tests" / "assets" / "cube.step"
ACTUALS_CSV = ROOT / "docs" / "training" / "fixtures" / "ground-truth-mixed.csv"


@pytest.mark.asyncio
async def test_costable_source_units_are_separate_and_legacy_is_rebuilt(tmp_path, monkeypatch):
    from src.services import source_artifact_service as artifacts

    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "objects"))
    mm = trimesh.creation.box(extents=[1, 1, 1])
    inch = mm.copy()
    inch.apply_scale(25.4)
    raw = mm.export(file_type="stl")
    digest = hashlib.sha256(raw).hexdigest()
    await save_source_artifact("org-units", digest, "box.stl", raw)
    # Legacy first-write-wins derivatives have no trustworthy unit identity.
    legacy = artifact_key("org-units", digest, ".stl").replace("source.stl", "costable.stl")
    artifacts._store().put(legacy, inch.export(file_type="stl"), content_type="model/stl")
    for units, expected in (("mm", 1.0), ("inch", 25.4), ("mm", 1.0)):
        payload = await read_costable_mesh_artifact("org-units", digest, source_units=units)
        mesh = trimesh.load(io.BytesIO(payload), file_type="stl")
        assert mesh.extents.tolist() == pytest.approx([expected] * 3, rel=1e-6)

    records = [GroundTruthRecord(part_id=f"box-{units}", process="fdm", quantity=50,
                                actual_unit_cost_usd=4.2, evidence_sha256=digest,
                                source_units=units) for units in ("mm", "inch")]

    def inspect_materialized(_org, actual, *, parts_dir, store_dir):
        assert all(record.source_units == "mm" for record in actual)
        assert actual[0].part_path != actual[1].part_path
        dimensions = [trimesh.load(Path(parts_dir) / record.part_path).extents[0] for record in actual]
        assert dimensions == pytest.approx([1.0, 25.4], rel=1e-6)
        return {"checked": 2}

    with (
        patch.object(groundtruth_service, "load_org_ground_truth", AsyncMock(return_value=records)),
        patch.object(groundtruth_service, "recalibrate_from_records", inspect_materialized),
    ):
        assert await groundtruth_service.recalibrate_org(AsyncMock(), "org-units") == {"checked": 2}
    with pytest.raises(ObjectNotFoundError):
        await read_costable_mesh_artifact("other-org", digest, source_units="inch")


def test_ground_truth_unit_choice_reaches_geometry_and_engine_cache(tmp_path):
    from src.costing.groundtruth import EngineCostCache

    path = tmp_path / "unitless.stl"
    trimesh.creation.box(extents=[10, 10, 10]).export(path)
    cache = EngineCostCache()
    mm = cache._report(str(path), 50, None, "polymer", "US", source_units="mm")
    inch = cache._report(str(path), 50, None, "polymer", "US", source_units="inch")
    assert mm.geometry["volume_cm3"] == pytest.approx(1.0)
    assert inch.geometry["volume_cm3"] == pytest.approx(254 ** 3 / 1000, rel=1e-6)


@pytest.mark.asyncio
async def test_source_artifacts_are_exact_idempotent_and_tenant_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "objects"))
    source = CUBE_STEP.read_bytes()
    digest = hashlib.sha256(source).hexdigest()

    locator = await save_source_artifact("org-a", digest, "cube.step", source)
    assert locator.startswith("file:")
    assert artifact_key("org-a", digest, ".step").endswith(f"/{digest}/source.step")
    assert await read_source_artifact("org-a", digest) == (source, ".step")
    assert await save_source_artifact("org-a", digest, ".step", source) == locator

    with pytest.raises(ValueError, match="do not match"):
        await save_source_artifact("org-a", digest, ".step", b"different")
    with pytest.raises(ObjectNotFoundError):
        await read_source_artifact("org-b", digest)

    costable = trimesh.creation.box(extents=[20, 15, 10]).export(file_type="stl")
    await save_costable_mesh_artifact("org-a", digest, costable)
    assert await read_costable_mesh_artifact("org-a", digest) == costable
    assert await read_source_artifact("org-a", digest) == (source, ".step")


@pytest.mark.asyncio
async def test_eight_source_bound_test_actuals_complete_measured_calibration(
    tmp_path, monkeypatch
):
    """Mechanics success oracle; these isolated test facts are not accuracy claims."""
    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "objects"))
    payloads, errors = groundtruth_service.parse_ground_truth_csv(
        ACTUALS_CSV.read_text()
    )
    assert len(payloads) == 8 and len(errors) == 1
    # The downloadable guide fixture is safely tagged demo. This isolated test
    # deliberately flips only the in-memory rows to exercise the successful
    # real-record branch without publishing test costs as customer truth.
    records = [
        replace(
            GroundTruthRecord(**payload),
            stand_in=False,
            source_type="actual",
            source="isolated release-test fact",
        )
        for payload in payloads
    ]
    source = CUBE_STEP.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    assert {record.evidence_sha256 for record in records} == {digest}
    await save_source_artifact("org-release-test", digest, ".step", source)
    await save_costable_mesh_artifact(
        "org-release-test",
        digest,
        trimesh.creation.box(extents=[20, 15, 10]).export(file_type="stl"),
    )

    with patch.object(
        groundtruth_service,
        "load_org_ground_truth",
        AsyncMock(return_value=records),
    ):
        result = await groundtruth_service.recalibrate_org(
            AsyncMock(),
            "org-release-test",
            store_dir=str(tmp_path / "calibrations"),
        )

    assert result["n_records"] == 8
    assert result["n_skipped"] == 0
    assert result["skipped"] == []
    assert result["from_real"] is True
    assert result["validated"] is True
    assert result["heldout_metrics_real"]["n_records"] >= 3
    assert "VALIDATED" in result["claim"]
