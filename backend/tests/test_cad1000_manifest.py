import copy
import json
from pathlib import Path

import pytest

from src.corpus.cad1000_manifest import (
    RIGHTS_FIELDS,
    build_manifest,
    generate_manifest,
    load_manifest,
    validate_manifest,
    workflow_split,
)


REVISION = "a" * 40
HASH = "b" * 64


def dataset_info():
    return {
        "id": "markov-ai/cad-1000-hours",
        "sha": REVISION,
        "cardData": {"pretty_name": "CAD 1000 Hours"},
        "siblings": [
            {"rfilename": "README.md", "size": 10},
            {
                "rfilename": "solidworks/workflow-a/clip.mp4",
                "size": 100,
                "lfs": {"sha256": HASH, "size": 100},
            },
            {"rfilename": "solidworks/workflow-a/task_desc.json", "size": 20},
            {
                "rfilename": "solidworks/workflow-a/output_files/part.SLDPRT",
                "size": 200,
            },
            {"rfilename": "catia/workflow-b/events.json", "size": 30},
        ],
    }


def test_inventory_reconciles_every_artifact_and_upstream_metadata():
    manifest = build_manifest(dataset_info())
    artifacts = {artifact["path"]: artifact for artifact in manifest["artifacts"]}

    assert manifest["dataset_revision"] == REVISION
    assert manifest["source_ref"] == REVISION
    assert manifest["aggregates"] == {
        "artifact_count": 5,
        "artifacts_with_unknown_bytes": 0,
        "artifacts_with_upstream_sha256": 1,
        "artifacts_without_upstream_sha256": 4,
        "by_application": {
            "catia": {"artifacts": 1, "bytes": 30, "workflows": 1},
            "solidworks": {"artifacts": 3, "bytes": 320, "workflows": 1},
        },
        "by_artifact_type": {
            "dataset_documentation": 1,
            "event_stream": 1,
            "task_description": 1,
            "workflow_output": 1,
            "workflow_video": 1,
        },
        "by_media_type": {
            "application/json": 2,
            "model/vnd.solidworks.part": 1,
            "text/markdown": 1,
            "video/mp4": 1,
        },
        "known_bytes": 360,
        "workflow_count": 2,
        "workflow_splits": manifest["aggregates"]["workflow_splits"],
    }
    assert sum(manifest["aggregates"]["workflow_splits"].values()) == 2
    assert manifest["reconciliation"]["complete"] is True
    assert manifest["reconciliation"]["source_artifact_count"] == 5
    assert manifest["reconciliation"]["source_known_bytes"] == 360

    video = artifacts["solidworks/workflow-a/clip.mp4"]
    assert video["bytes"] == 100
    assert video["media_type"] == "video/mp4"
    assert video["artifact_type"] == "workflow_video"
    assert video["application"] == "solidworks"
    assert video["workflow"] == "solidworks/workflow-a"
    assert video["sha256"] == HASH
    assert video["sha256_status"] == "UPSTREAM_SUPPLIED_UNVERIFIED_LOCALLY"
    assert f"/resolve/{REVISION}/" in video["immutable_url"]

    readme = artifacts["README.md"]
    assert readme["workflow"] is None
    assert readme["sha256"] is None
    assert readme["sha256_status"] == "NOT_SUPPLIED_UNVERIFIED"


def test_undeclared_license_fails_closed_for_every_artifact():
    manifest = build_manifest(dataset_info())
    assert manifest["license_status"] == "UNDECLARED"
    assert manifest["rights"] == {field: False for field in RIGHTS_FIELDS}
    assert manifest["customer_data_excluded"] is True
    assert all(artifact["rights"] == manifest["rights"] for artifact in manifest["artifacts"])
    assert all(artifact["customer_data_excluded"] is True for artifact in manifest["artifacts"])

    with pytest.raises(ValueError, match="Undeclared license"):
        build_manifest(dataset_info(), grants={"local_research": True})


def test_workflow_split_is_stable_before_tuning_and_independent_of_file_order():
    source = dataset_info()
    first = build_manifest(source)
    reversed_source = {**source, "siblings": list(reversed(source["siblings"]))}
    second = build_manifest(reversed_source)

    assert first == second
    workflow_artifacts = [
        artifact
        for artifact in first["artifacts"]
        if artifact["workflow"] == "solidworks/workflow-a"
    ]
    expected = workflow_split("solidworks/workflow-a", REVISION)
    assert {artifact["split"] for artifact in workflow_artifacts} == {expected}
    assert first["split_policy"]["frozen_before_tuning"] is True


@pytest.mark.parametrize(
    "mutate,match",
    [
        (
            lambda manifest: manifest["artifacts"][0].__setitem__("path", "../escape"),
            "Unsafe artifact path",
        ),
        (
            lambda manifest: manifest["aggregates"].__setitem__("known_bytes", 1),
            "aggregates did not reconcile",
        ),
        (
            lambda manifest: manifest["rights"].__setitem__("training", True),
            "Undeclared license",
        ),
    ],
)
def test_malformed_or_rights_unsafe_manifest_is_rejected(mutate, match):
    manifest = copy.deepcopy(build_manifest(dataset_info()))
    mutate(manifest)
    with pytest.raises(ValueError, match=match):
        validate_manifest(manifest)


def test_manifest_rejects_a_source_ref_from_another_revision():
    manifest = copy.deepcopy(build_manifest(dataset_info()))
    manifest["source_ref"] = "c" * 40

    with pytest.raises(ValueError, match="source reference"):
        validate_manifest(manifest)


def test_atomic_local_generation_resumes_valid_pinned_snapshot(tmp_path: Path):
    output = tmp_path / "cad1000-manifest.json"
    source = tmp_path / "dataset-info.json"
    source.write_text(json.dumps(dataset_info()), encoding="utf-8")

    generated = generate_manifest(output, dataset_info=source)
    assert load_manifest(output) == generated
    assert not output.with_suffix(".json.tmp").exists()

    def must_not_fetch(_url: str):
        raise AssertionError("valid pinned manifest should resume without a network call")

    assert generate_manifest(output, fetch_json=must_not_fetch) == generated
