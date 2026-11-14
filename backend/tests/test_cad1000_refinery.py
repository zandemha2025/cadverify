import hashlib
import json
from pathlib import Path

import pytest
import trimesh

from src.corpus.cad1000_manifest import build_manifest, write_manifest
from src.corpus.cad1000_refinery import SNAPSHOT_NAME, refine


REVISION = "a" * 40
CANARIES = (
    "SECRET_TYPED_TEXT",
    "SECRET_WIFI",
    "SECRET_WINDOW_TITLE",
    "SECRET_LOCAL_PATH",
    "SECRET_PID",
)


def _json(value) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def _ndjson(*rows) -> bytes:
    return b"".join(_json(row) + b"\n" for row in rows)


def _workflow_files(
    workflow: str,
    *,
    malformed_task: bool = False,
    artifact_format: str = "sldprt",
) -> dict[str, bytes]:
    prefix = f"solidworks/{workflow}"
    task = {
        "domain": "Mechanical CAD",
        "application": "SOLIDWORKS",
        "task": "Model a mounting bracket",
        "description": "Create a bracket with two mounting holes.",
        "deliverables": [
            {"type": artifact_format, "format": artifact_format, "description": "Native part"}
        ],
    }
    metadata = {
        "category": "cad",
        "event_count": 7,
        "fps": 30,
        "total_duration_ms": 2000,
        "total_frames": 60,
    }
    narration = {
        "annotations": [
            {
                "start_s": 0,
                "end_s": 1,
                "action": "Sketch the base.",
                "intent": "Create the primary profile.",
                "app": "SOLIDWORKS",
                "details": None,
            },
            {
                "start_s": 1,
                "end_s": 2,
                "action": "Extrude the base.",
                "intent": "Create the solid.",
                "app": "SOLIDWORKS",
                "details": "Use the declared dimension.",
            },
        ]
    }
    rubrics = {
        "rubrics": [
            {"id": "R1", "requirement": "The bracket shall have two mounting holes."}
        ]
    }
    events = _ndjson(
        {
            "type": "wifi_change",
            "ssid": "SECRET_WIFI",
            "timestamp": 10000,
        },
        {
            "type": "key",
            "key": "x",
            "characters": "SECRET_TYPED_TEXT",
            "timestamp": 10100,
        },
        {
            "type": "active_app",
            "name": "SOLIDWORKS",
            "windowTitle": "SECRET_WINDOW_TITLE",
            "pid": "SECRET_PID",
            "path": "SECRET_LOCAL_PATH",
            "timestamp": 10200,
        },
        {"type": "active_app", "name": "Google Chrome", "timestamp": 10300},
        {"type": "active_app", "name": "SOLIDWORKS", "timestamp": 10400},
    )
    frame_events = _ndjson(
        {
            "frame": 15,
            "video_t_ms": 500,
            "events": [
                {
                    "type": "mouse_move",
                    "synthetic": True,
                    "x": 999,
                    "y": 999,
                    "path": "SECRET_LOCAL_PATH",
                    "video_t_ms": 500,
                },
                {"type": "click", "x": 1, "y": 2, "video_t_ms": 500},
                {
                    "type": "active_app",
                    "name": "SOLIDWORKS",
                    "windowTitle": "SECRET_WINDOW_TITLE",
                    "video_t_ms": 500,
                },
            ],
        },
        {
            "frame": 45,
            "video_t_ms": 1500,
            "events": [
                {
                    "type": "key",
                    "characters": "SECRET_TYPED_TEXT",
                    "video_t_ms": 1500,
                },
                {
                    "type": "active_app",
                    "name": "Customer Drawing SECRET_WINDOW_TITLE",
                    "pid": "SECRET_PID",
                    "video_t_ms": 1500,
                },
            ],
        },
    )
    extension = ".STL" if artifact_format == "stl" else ".SLDPRT"
    files = {
        f"{prefix}/clip.mp4": b"offline-video-bytes",
        f"{prefix}/events.json": events,
        f"{prefix}/frame_events.json": frame_events,
        f"{prefix}/metadata.json": _json(metadata),
        f"{prefix}/narration.json": _json(narration),
        f"{prefix}/rubrics.json": _json(rubrics),
        f"{prefix}/task_desc.json": b"{" if malformed_task else _json(task),
        f"{prefix}/input_files/part{extension}": b"native-before",
        f"{prefix}/output_files/part{extension}": b"native-after",
    }
    return files


def _write_fixture(
    tmp_path: Path,
    workflows: dict[str, dict[str, bytes]],
    *,
    local_research: bool = True,
    production_retrieval: bool = True,
) -> tuple[Path, Path]:
    mirror = tmp_path / "mirror"
    siblings = []
    for files in workflows.values():
        for relative, content in files.items():
            target = mirror / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            siblings.append(
                {
                    "rfilename": relative,
                    "size": len(content),
                    "lfs": {"sha256": digest, "size": len(content)},
                }
            )
    dataset_info = {
        "id": "markov-ai/cad-1000-hours",
        "sha": REVISION,
        "cardData": {"license": "cc-by-4.0"},
        "siblings": siblings,
    }
    grants = {
        "local_research": local_research,
        "production_retrieval": production_retrieval,
        "training": False,
        "redistribution": False,
    }
    manifest = tmp_path / "manifest.json"
    write_manifest(manifest, build_manifest(dataset_info, grants=grants))
    return manifest, mirror


def _snapshot_records(output: Path) -> list[dict]:
    return [json.loads(line) for line in (output / SNAPSHOT_NAME).read_text().splitlines()]


def test_refinery_redacts_raw_input_and_aligns_timing(tmp_path: Path):
    files = _workflow_files("workflow-a")
    manifest, mirror = _write_fixture(tmp_path, {"workflow-a": files})
    output = tmp_path / "refined"

    summary = refine(manifest, mirror, output)
    records = _snapshot_records(output)
    serialized = json.dumps(records)

    assert summary["completed_workflows"] == 1
    assert summary["quarantined_workflows"] == 0
    assert all(canary not in serialized for canary in CANARIES)
    assert str(mirror) not in serialized

    event_record = next(row for row in records if row["record_type"] == "event_aggregate")
    assert event_record["event_type_counts"] == {"active_app": 3, "key": 1, "wifi_change": 1}
    assert event_record["app_transition_counts"] == {
        "browser->target_application": 1,
        "target_application->browser": 1,
    }
    assert event_record["event_range"]["first_timestamp"] is None
    assert event_record["event_range"]["last_timestamp"] is None
    assert event_record["event_range"]["timestamp_basis"] == "event_order_only"

    frame_record = next(row for row in records if row["record_type"] == "frame_event_aggregate")
    assert frame_record["synthetic_frame_mouse_moves_skipped"] == 1
    assert frame_record["event_type_counts"] == {"active_app": 2, "click": 1, "key": 1}

    timing = sorted(
        (row for row in records if row["record_type"] == "narration_timing"),
        key=lambda row: row["narration_index"],
    )
    assert [row["event_count"] for row in timing] == [2, 2]
    assert [row["active_frame_count"] for row in timing] == [1, 1]
    assert timing[0]["event_timestamp_range_ms"] == {"start": 500.0, "end": 500.0}
    assert timing[1]["event_timestamp_range_ms"] == {"start": 1500.0, "end": 1500.0}


def test_source_hash_rights_and_advisory_contract_are_linked(tmp_path: Path):
    files = _workflow_files("workflow-a")
    manifest, mirror = _write_fixture(tmp_path, {"workflow-a": files})
    output = tmp_path / "refined"

    refine(manifest, mirror, output)
    records = _snapshot_records(output)

    assert records
    for record in records:
        assert record["dataset_revision"] == REVISION
        assert record["workflow"] == "solidworks/workflow-a"
        assert record["application"] == "solidworks"
        assert record["split"] in {"development", "held_out"}
        assert record["authority"] == "ADVISORY_ONLY"
        assert record["engineering_authority"] == "NONE"
        assert record["may_affect_deterministic_verdict"] is False
        assert record["is_manufacturing_ground_truth"] is False
        assert record["eligible_for_production_retrieval"] is True
        assert "verdict" not in record
        assert "makeable" not in record
        assert record["sources"]
        assert all(
            source["hash_status"] == "LOCAL_SHA256_VERIFIED_AGAINST_UPSTREAM"
            and source["local_sha256"] == source["upstream_sha256"]
            for source in record["sources"]
        )

    video = next(row for row in records if row["record_type"] == "video_evidence")
    assert video["raw_media_policy"] == "OFFLINE_ONLY_NOT_COPIED"
    assert video["evidence_pointer"] == {
        "availability": "LOCAL_MIRROR_ONLY",
        "source_path": "solidworks/workflow-a/clip.mp4",
        "timestamp_basis": "video_ms",
    }


def test_native_cad_transition_is_explicitly_unavailable(tmp_path: Path):
    files = _workflow_files("workflow-a")
    manifest, mirror = _write_fixture(tmp_path, {"workflow-a": files})
    output = tmp_path / "refined"

    refine(manifest, mirror, output)
    transition = next(
        row for row in _snapshot_records(output) if row["record_type"] == "geometry_transition"
    )

    assert transition["geometry_delta_status"] == "UNAVAILABLE_UNSUPPORTED_PROPRIETARY_FORMAT"
    assert "no before/after geometry delta is claimed" in transition["geometry_delta_reason"]
    assert "before" not in transition
    assert "after" not in transition
    assert "geometry_delta" not in transition


def test_local_stl_pair_gets_measured_before_after_summary(tmp_path: Path):
    files = _workflow_files("workflow-a", artifact_format="stl")
    prefix = "solidworks/workflow-a"
    files[f"{prefix}/input_files/part.STL"] = trimesh.creation.box(extents=[1, 1, 1]).export(
        file_type="stl"
    )
    files[f"{prefix}/output_files/part.STL"] = trimesh.creation.box(extents=[2, 2, 2]).export(
        file_type="stl"
    )
    manifest, mirror = _write_fixture(tmp_path, {"workflow-a": files})
    output = tmp_path / "refined"

    refine(manifest, mirror, output)
    transition = next(
        row for row in _snapshot_records(output) if row["record_type"] == "geometry_transition"
    )

    assert transition["geometry_delta_status"] == "AVAILABLE_LOCAL_STL_PAIR"
    assert transition["before"]["extents"] == pytest.approx([1, 1, 1])
    assert transition["after"]["extents"] == pytest.approx([2, 2, 2])
    assert transition["geometry_delta"]["volume"] == pytest.approx(7.0)
    assert transition["before"]["units"] == "SOURCE_UNITS_UNDECLARED"


def test_malformed_workflow_is_quarantined_without_aborting_others(tmp_path: Path):
    bad = _workflow_files("workflow-bad", malformed_task=True)
    good = _workflow_files("workflow-good")
    manifest, mirror = _write_fixture(tmp_path, {"bad": bad, "good": good})
    output = tmp_path / "refined"

    summary = refine(manifest, mirror, output)
    records = _snapshot_records(output)

    assert summary["completed_workflows"] == 1
    assert summary["quarantined_workflows"] == 1
    quarantine = next(row for row in records if row["record_type"] == "workflow_quarantine")
    assert quarantine["workflow"] == "solidworks/workflow-bad"
    assert quarantine["quarantine_reason"] == "MALFORMED_JSON"
    assert quarantine["eligible_for_production_retrieval"] is False
    assert any(row["workflow"] == "solidworks/workflow-good" for row in records)


def test_valid_atomic_shard_is_reused_and_force_rebuilds(tmp_path: Path, monkeypatch):
    files = _workflow_files("workflow-a")
    manifest, mirror = _write_fixture(tmp_path, {"workflow-a": files})
    output = tmp_path / "refined"
    first = refine(manifest, mirror, output)
    shard = next((output / "shards").rglob("*.jsonl"))
    before = shard.read_bytes()

    import src.corpus.cad1000_refinery as refinery

    def fail_if_processed(*_args, **_kwargs):
        raise AssertionError("valid completed shard should be reused")

    monkeypatch.setattr(refinery, "_process_workflow", fail_if_processed)
    resumed = refine(manifest, mirror, output)

    assert first["processed_workflows"] == 1
    assert resumed["processed_workflows"] == 0
    assert resumed["reused_workflows"] == 1
    assert shard.read_bytes() == before
    assert not list(output.rglob("*.tmp"))

    forced = refine(manifest, mirror, output, force=True)
    assert forced["processed_workflows"] == 1
    assert forced["quarantined_workflows"] == 1


def test_manifest_rights_fail_closed_for_production_eligibility(tmp_path: Path):
    files = _workflow_files("workflow-a")
    manifest, mirror = _write_fixture(
        tmp_path,
        {"workflow-a": files},
        production_retrieval=False,
    )
    output = tmp_path / "refined"

    refine(manifest, mirror, output)

    assert all(
        record["eligible_for_production_retrieval"] is False
        for record in _snapshot_records(output)
    )


def test_manifest_without_local_research_right_does_not_process_raw_artifacts(
    tmp_path: Path,
):
    files = _workflow_files("workflow-a")
    manifest, mirror = _write_fixture(
        tmp_path, {"workflow-a": files}, local_research=False
    )

    with pytest.raises(PermissionError, match="does not grant local_research"):
        refine(manifest, mirror, tmp_path / "refined")

    assert not (tmp_path / "refined").exists()
