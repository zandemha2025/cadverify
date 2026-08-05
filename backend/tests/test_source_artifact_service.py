from __future__ import annotations

import hashlib
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
