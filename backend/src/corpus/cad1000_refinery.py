"""Offline, privacy-safe CAD1000 derivative refinery.

The refinery reads only a local mirror pinned by a validated immutable
manifest.  Raw media and input events never leave that mirror: the output is
small JSONL records containing instructional text, verified artifact metadata,
and fixed-vocabulary event aggregates.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Optional

from src.corpus.cad1000 import CADVERIFY_CORE_SOFTWARE, DATASET_ID, DATASET_URL
from src.corpus.cad1000_manifest import (
    DEFAULT_MANIFEST,
    UNDECLARED_LICENSES,
    load_manifest,
)
from src.parsers.stl_parser import parse_stl


SCHEMA_VERSION = "1.0"
SNAPSHOT_NAME = "cad1000-refined.jsonl"
SHARD_DIRECTORY = "shards"
_CHUNK_BYTES = 1024 * 1024
_REQUIRED_TYPES = {
    "task_description",
    "workflow_metadata",
    "rubric",
    "narration",
    "workflow_video",
    "event_stream",
    "frame_event_stream",
}
_NATIVE_CAD_SUFFIXES = frozenset(
    {
        ".anl",
        ".catanalysis",
        ".catdrawing",
        ".catpart",
        ".catproduct",
        ".dwg",
        ".eprt",
        ".prt",
        ".rvt",
        ".skp",
        ".sldasm",
        ".slddrw",
        ".sldprt",
        ".std",
        ".swj",
    }
)
_EVENT_CATEGORIES = {
    "active_app": "application",
    "app_hidden": "application",
    "app_unhidden": "application",
    "appearance_change": "system",
    "battery_status": "system",
    "click": "pointer",
    "drag": "pointer",
    "input_source_change": "system",
    "key": "keyboard",
    "memory_pressure": "system",
    "modifier_change": "keyboard",
    "mouse_delta": "pointer",
    "mouse_move": "pointer",
    "network_change": "network",
    "power_source_change": "system",
    "privacy_mask_end": "privacy",
    "privacy_mask_start": "privacy",
    "screen_config": "display",
    "scroll": "pointer",
    "text_selection": "keyboard",
    "wifi_change": "network",
    "window_moved": "application",
    "window_resized": "application",
    "window_title_changed": "application",
}


class WorkflowError(ValueError):
    """A safe, workflow-local failure that may be written to quarantine."""

    def __init__(self, code: str, source_path: Optional[str] = None):
        super().__init__(code)
        self.code = code
        self.source_path = source_path


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _atomic_write(path: Path, records: Iterable[Mapping[str, object]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    count = 0
    try:
        with temporary.open("wb") as handle:
            for record in records:
                handle.write(_json_bytes(record) + b"\n")
                count += 1
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return count


def _workflow_fingerprint(manifest: Mapping[str, object], artifacts: list[dict]) -> str:
    material = {
        "refinery_schema": SCHEMA_VERSION,
        "dataset_revision": manifest["dataset_revision"],
        "artifacts": artifacts,
    }
    return hashlib.sha256(_json_bytes(material)).hexdigest()


def _local_path(mirror: Path, artifact: Mapping[str, object]) -> Path:
    root = mirror.resolve()
    candidate = (root / str(artifact["path"])).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise WorkflowError("SOURCE_ESCAPES_MIRROR", str(artifact["path"])) from exc
    if not candidate.is_file():
        raise WorkflowError("SOURCE_MISSING", str(artifact["path"]))
    return candidate


def _verified_source(
    artifact: Mapping[str, object], local_sha256: str, local_bytes: int
) -> dict:
    source_path = str(artifact["path"])
    expected_bytes = artifact.get("bytes")
    if expected_bytes is not None and local_bytes != expected_bytes:
        raise WorkflowError("SOURCE_SIZE_MISMATCH", source_path)
    upstream_sha256 = artifact.get("sha256")
    if upstream_sha256 is not None and local_sha256 != upstream_sha256:
        raise WorkflowError("SOURCE_HASH_MISMATCH", source_path)
    return {
        "artifact_type": artifact["artifact_type"],
        "bytes": local_bytes,
        "hash_status": (
            "LOCAL_SHA256_VERIFIED_AGAINST_UPSTREAM"
            if upstream_sha256 is not None
            else "LOCAL_SHA256_COMPUTED_UPSTREAM_NOT_SUPPLIED"
        ),
        "local_sha256": local_sha256,
        "media_type": artifact["media_type"],
        "path": source_path,
        "upstream_sha256": upstream_sha256,
    }


def _hash_file(mirror: Path, artifact: Mapping[str, object]) -> dict:
    digest = hashlib.sha256()
    total = 0
    with _local_path(mirror, artifact).open("rb") as handle:
        while chunk := handle.read(_CHUNK_BYTES):
            digest.update(chunk)
            total += len(chunk)
    return _verified_source(artifact, digest.hexdigest(), total)


def _read_json(mirror: Path, artifact: Mapping[str, object]) -> tuple[object, dict]:
    digest = hashlib.sha256()
    total = 0
    chunks: list[bytes] = []
    with _local_path(mirror, artifact).open("rb") as handle:
        while chunk := handle.read(_CHUNK_BYTES):
            digest.update(chunk)
            total += len(chunk)
            chunks.append(chunk)
    source = _verified_source(artifact, digest.hexdigest(), total)
    try:
        return json.loads(b"".join(chunks)), source
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkflowError("MALFORMED_JSON", str(artifact["path"])) from exc


def _number(value: object) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        result = float(value)
        if math.isfinite(result):
            return result
    return None


def _require_object(value: object, artifact: Mapping[str, object]) -> dict:
    if not isinstance(value, dict):
        raise WorkflowError("UNEXPECTED_JSON_SHAPE", str(artifact["path"]))
    return value


def _base_record(
    manifest: Mapping[str, object], artifacts: list[dict], fingerprint: str
) -> dict:
    first = artifacts[0]
    raw_rights = manifest["rights"]
    rights = dict(raw_rights) if isinstance(raw_rights, Mapping) else {}
    license_status = str(manifest["license_status"])
    production_eligible = (
        rights.get("production_retrieval") is True
        and license_status.strip().upper() not in UNDECLARED_LICENSES
    )
    return {
        "application": first["application"],
        "authority": "ADVISORY_ONLY",
        "customer_data_excluded": True,
        "dataset": DATASET_ID,
        "dataset_revision": manifest["dataset_revision"],
        "dataset_url": DATASET_URL,
        "eligible_for_production_retrieval": production_eligible,
        "engineering_authority": "NONE",
        "is_manufacturing_ground_truth": False,
        "license_status": license_status,
        "may_affect_deterministic_verdict": False,
        "provenance": "THIRD_PARTY_UNVERIFIED",
        "rights": rights,
        "schema_version": SCHEMA_VERSION,
        "split": first["split"],
        "workflow": first["workflow"],
        "workflow_id": first["workflow_id"],
        "workflow_manifest_sha256": fingerprint,
    }


def _source_stub(artifact: Mapping[str, object]) -> dict:
    return {
        "artifact_type": artifact["artifact_type"],
        "bytes": artifact.get("bytes"),
        "hash_status": artifact["sha256_status"],
        "local_sha256": None,
        "media_type": artifact["media_type"],
        "path": artifact["path"],
        "upstream_sha256": artifact.get("sha256"),
    }


def _single_artifact(artifacts: list[dict], artifact_type: str) -> dict:
    matches = [item for item in artifacts if item["artifact_type"] == artifact_type]
    if len(matches) != 1:
        source_path = matches[0]["path"] if matches else artifacts[0]["path"]
        raise WorkflowError(f"EXPECTED_ONE_{artifact_type.upper()}", source_path)
    return matches[0]


def _safe_deliverables(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        result.append(
            {
                key: item[key]
                for key in ("type", "format", "description")
                if isinstance(item.get(key), str)
            }
        )
    return result


def _narration_rows(value: object, artifact: Mapping[str, object]) -> list[dict]:
    root = _require_object(value, artifact)
    annotations = root.get("annotations")
    if not isinstance(annotations, list):
        raise WorkflowError("INVALID_NARRATION", str(artifact["path"]))
    rows = []
    for index, annotation in enumerate(annotations):
        if not isinstance(annotation, Mapping):
            raise WorkflowError("INVALID_NARRATION", str(artifact["path"]))
        start_s = _number(annotation.get("start_s"))
        end_s = _number(annotation.get("end_s"))
        if start_s is None or end_s is None or start_s < 0 or end_s < start_s:
            raise WorkflowError("INVALID_NARRATION_TIMING", str(artifact["path"]))
        rows.append(
            {
                "action": annotation.get("action") if isinstance(annotation.get("action"), str) else None,
                "app": annotation.get("app") if isinstance(annotation.get("app"), str) else None,
                "details": annotation.get("details") if isinstance(annotation.get("details"), str) else None,
                "end_s": end_s,
                "index": index,
                "intent": annotation.get("intent") if isinstance(annotation.get("intent"), str) else None,
                "start_s": start_s,
            }
        )
    return rows


def _safe_event_type(value: object) -> str:
    return value if isinstance(value, str) and value in _EVENT_CATEGORIES else "other"


def _safe_application(value: object, target_application: str) -> str:
    if not isinstance(value, str):
        return "unknown_application"
    lowered = value.casefold()
    target = target_application.casefold()
    aliases = {
        "catia": "catia",
        "cnext": "catia",
        "solidworks": "solidworks",
        "sldworks": "solidworks",
        "siemens nx": "nx-cad",
        "ugraf": "nx-cad",
        "chrome": "browser",
        "firefox": "browser",
        "edge": "browser",
        "explorer": "file_manager",
        "acrobat": "pdf_viewer",
    }
    for fragment, label in aliases.items():
        if fragment in lowered:
            return "target_application" if label == target else label
    if target and target in lowered:
        return "target_application"
    return "other_application"


def _interval_index(starts_ms: list[float], rows: list[dict], timestamp_ms: float) -> Optional[int]:
    index = bisect.bisect_right(starts_ms, timestamp_ms) - 1
    if index < 0:
        return None
    end_ms = rows[index]["end_s"] * 1000.0
    if timestamp_ms > end_ms or (
        timestamp_ms == end_ms and index + 1 < len(rows)
    ):
        return None
    return index


def _new_timing() -> dict:
    return {
        "active_frames": set(),
        "category_counts": Counter(),
        "event_count": 0,
        "first_event_ms": None,
        "last_event_ms": None,
        "type_counts": Counter(),
    }


def _stream_event_aggregate(
    mirror: Path,
    artifact: Mapping[str, object],
    *,
    target_application: str,
    narration: Optional[list[dict]] = None,
) -> tuple[dict, dict, list[dict]]:
    digest = hashlib.sha256()
    total = 0
    line_count = 0
    observed_count = 0
    synthetic_mouse_moves_skipped = 0
    type_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    transition_counts: Counter[str] = Counter()
    first_timestamp = None
    last_timestamp = None
    first_frame = None
    last_frame = None
    previous_application = None
    timing = [_new_timing() for _ in narration or []]
    starts_ms = [row["start_s"] * 1000.0 for row in narration or []]
    frame_stream = artifact["artifact_type"] == "frame_event_stream"

    with _local_path(mirror, artifact).open("rb") as handle:
        for line_index, raw_line in enumerate(handle):
            digest.update(raw_line)
            total += len(raw_line)
            if not raw_line.strip():
                continue
            line_count += 1
            try:
                row = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise WorkflowError("MALFORMED_NDJSON", str(artifact["path"])) from exc
            if not isinstance(row, Mapping):
                raise WorkflowError("MALFORMED_EVENT_ROW", str(artifact["path"]))
            if frame_stream:
                events = row.get("events")
                if not isinstance(events, list):
                    raise WorkflowError("MALFORMED_FRAME_EVENTS", str(artifact["path"]))
                frame = row.get("frame")
                if isinstance(frame, int) and not isinstance(frame, bool):
                    first_frame = frame if first_frame is None else min(first_frame, frame)
                    last_frame = frame if last_frame is None else max(last_frame, frame)
                outer_timestamp = _number(row.get("video_t_ms"))
            else:
                events = [row]
                frame = line_index
                outer_timestamp = None

            for event in events:
                if not isinstance(event, Mapping):
                    raise WorkflowError("MALFORMED_EVENT", str(artifact["path"]))
                safe_type = _safe_event_type(event.get("type"))
                if frame_stream and safe_type == "mouse_move" and event.get("synthetic") is True:
                    synthetic_mouse_moves_skipped += 1
                    continue
                category = _EVENT_CATEGORIES.get(safe_type, "other")
                observed_count += 1
                type_counts[safe_type] += 1
                category_counts[category] += 1

                # Frame streams use video-relative milliseconds for narration
                # alignment. Event-stream timestamps are source wall-clock data
                # and must never leave the offline raw mirror.
                timestamp = _number(event.get("video_t_ms")) if frame_stream else None
                if timestamp is None:
                    timestamp = outer_timestamp
                if timestamp is not None:
                    first_timestamp = timestamp if first_timestamp is None else min(first_timestamp, timestamp)
                    last_timestamp = timestamp if last_timestamp is None else max(last_timestamp, timestamp)

                if safe_type == "active_app":
                    name = event.get("name", event.get("appName"))
                    current_application = _safe_application(name, target_application)
                    if previous_application is not None and current_application != previous_application:
                        transition_counts[f"{previous_application}->{current_application}"] += 1
                    previous_application = current_application

                if frame_stream and timestamp is not None and narration:
                    index = _interval_index(starts_ms, narration, timestamp)
                    if index is not None:
                        stats = timing[index]
                        stats["event_count"] += 1
                        stats["type_counts"][safe_type] += 1
                        stats["category_counts"][category] += 1
                        if isinstance(frame, int) and not isinstance(frame, bool):
                            stats["active_frames"].add(frame)
                        stats["first_event_ms"] = (
                            timestamp
                            if stats["first_event_ms"] is None
                            else min(stats["first_event_ms"], timestamp)
                        )
                        stats["last_event_ms"] = (
                            timestamp
                            if stats["last_event_ms"] is None
                            else max(stats["last_event_ms"], timestamp)
                        )

    source = _verified_source(artifact, digest.hexdigest(), total)
    aggregate = {
        "app_transition_counts": dict(sorted(transition_counts.items())),
        "event_category_counts": dict(sorted(category_counts.items())),
        "event_range": {
            "first_event_index": 0 if line_count else None,
            "first_frame": first_frame,
            "first_timestamp": first_timestamp,
            "last_event_index": line_count - 1 if line_count else None,
            "last_frame": last_frame,
            "last_timestamp": last_timestamp,
            "timestamp_basis": "video_ms" if frame_stream else "event_order_only",
        },
        "event_type_counts": dict(sorted(type_counts.items())),
        "line_count": line_count,
        "observed_event_count": observed_count,
        "synthetic_frame_mouse_moves_skipped": synthetic_mouse_moves_skipped,
    }
    return source, aggregate, timing


def _mesh_summary(path: Path) -> dict:
    try:
        mesh = parse_stl(path)
    except Exception as exc:
        raise WorkflowError("STL_PARSE_FAILED", path.name) from exc
    extents = [float(value) for value in mesh.extents]
    bounds = [[float(value) for value in row] for row in mesh.bounds]
    surface_area = float(mesh.area)
    volume = float(abs(mesh.volume)) if mesh.is_watertight else None
    if not all(math.isfinite(value) for value in [*extents, *sum(bounds, []), surface_area]):
        raise WorkflowError("INVALID_STL_GEOMETRY", path.name)
    if volume is not None and not math.isfinite(volume):
        raise WorkflowError("INVALID_STL_GEOMETRY", path.name)
    return {
        "bounds": bounds,
        "extents": extents,
        "face_count": int(len(mesh.faces)),
        "surface_area": surface_area,
        "units": "SOURCE_UNITS_UNDECLARED",
        "vertex_count": int(len(mesh.vertices)),
        "volume": volume,
        "watertight": bool(mesh.is_watertight),
    }


def _stl_pairs(inputs: list[dict], outputs: list[dict]) -> list[tuple[dict, dict]]:
    input_stls = [item for item in inputs if PurePosixPath(item["path"]).suffix.lower() == ".stl"]
    output_stls = [item for item in outputs if PurePosixPath(item["path"]).suffix.lower() == ".stl"]
    pairs = []
    for output in output_stls:
        output_stem = PurePosixPath(output["path"]).stem.casefold()
        matching = [
            item
            for item in input_stls
            if PurePosixPath(item["path"]).stem.casefold() == output_stem
        ]
        if len(matching) == 1:
            pairs.append((matching[0], output))
        elif len(input_stls) == 1 and len(output_stls) == 1:
            pairs.append((input_stls[0], output))
    return pairs


def _transition_records(
    mirror: Path,
    base: dict,
    inputs: list[dict],
    outputs: list[dict],
    sources: Mapping[str, dict],
) -> list[dict]:
    records = []
    paired_outputs = set()
    for before_artifact, after_artifact in _stl_pairs(inputs, outputs):
        before = _mesh_summary(_local_path(mirror, before_artifact))
        after = _mesh_summary(_local_path(mirror, after_artifact))
        paired_outputs.add(after_artifact["path"])
        records.append(
            {
                **base,
                "after": after,
                "before": before,
                "geometry_delta": {
                    "extents": [after["extents"][i] - before["extents"][i] for i in range(3)],
                    "surface_area": after["surface_area"] - before["surface_area"],
                    "volume": (
                        after["volume"] - before["volume"]
                        if after["volume"] is not None and before["volume"] is not None
                        else None
                    ),
                },
                "geometry_delta_status": "AVAILABLE_LOCAL_STL_PAIR",
                "knowledge_role": "artifact_transition",
                "record_type": "geometry_transition",
                "sources": [sources[before_artifact["path"]], sources[after_artifact["path"]]],
                "text": "Measured before/after geometry summary from a local STL pair; source units are undeclared.",
            }
        )

    for output in outputs:
        suffix = PurePosixPath(output["path"]).suffix.lower()
        if output["path"] in paired_outputs or suffix not in _NATIVE_CAD_SUFFIXES:
            continue
        same_suffix_inputs = [
            item for item in inputs if PurePosixPath(item["path"]).suffix.lower() == suffix
        ]
        linked = [same_suffix_inputs[0], output] if len(same_suffix_inputs) == 1 else [output]
        records.append(
            {
                **base,
                "geometry_delta_status": "UNAVAILABLE_UNSUPPORTED_PROPRIETARY_FORMAT",
                "geometry_delta_reason": (
                    "Native CAD geometry was not parsed; no before/after geometry delta is claimed."
                ),
                "knowledge_role": "artifact_transition",
                "record_type": "geometry_transition",
                "sources": [sources[item["path"]] for item in linked],
                "text": "Native CAD artifact transition recorded without an invented geometry delta.",
            }
        )
    return records


def _process_workflow(
    manifest: Mapping[str, object], artifacts: list[dict], mirror: Path
) -> list[dict]:
    fingerprint = _workflow_fingerprint(manifest, artifacts)
    base = _base_record(manifest, artifacts, fingerprint)
    by_type = {item["artifact_type"] for item in artifacts}
    missing = sorted(_REQUIRED_TYPES - by_type)
    if missing:
        raise WorkflowError(f"MISSING_REQUIRED_ARTIFACT_{missing[0].upper()}", artifacts[0]["path"])

    task_artifact = _single_artifact(artifacts, "task_description")
    metadata_artifact = _single_artifact(artifacts, "workflow_metadata")
    rubrics_artifact = _single_artifact(artifacts, "rubric")
    narration_artifact = _single_artifact(artifacts, "narration")
    video_artifact = _single_artifact(artifacts, "workflow_video")
    events_artifact = _single_artifact(artifacts, "event_stream")
    frame_events_artifact = _single_artifact(artifacts, "frame_event_stream")

    task_value, task_source = _read_json(mirror, task_artifact)
    metadata_value, metadata_source = _read_json(mirror, metadata_artifact)
    rubrics_value, rubrics_source = _read_json(mirror, rubrics_artifact)
    narration_value, narration_source = _read_json(mirror, narration_artifact)
    task = _require_object(task_value, task_artifact)
    metadata = _require_object(metadata_value, metadata_artifact)
    rubrics = _require_object(rubrics_value, rubrics_artifact)
    narration = _narration_rows(narration_value, narration_artifact)

    task_name = task.get("task") if isinstance(task.get("task"), str) else None
    description = task.get("description") if isinstance(task.get("description"), str) else None
    application_name = task.get("application") if isinstance(task.get("application"), str) else None
    domain = task.get("domain") if isinstance(task.get("domain"), str) else None
    duration_ms = _number(metadata.get("total_duration_ms"))
    fps = _number(metadata.get("fps"))
    total_frames = metadata.get("total_frames")
    if not isinstance(total_frames, int) or isinstance(total_frames, bool) or total_frames < 0:
        total_frames = None

    records = [
        {
            **base,
            "application_name": application_name,
            "deliverables": _safe_deliverables(task.get("deliverables")),
            "description": description,
            "domain": domain,
            "duration_ms": duration_ms,
            "knowledge_role": "design_intent",
            "record_type": "workflow_intent",
            "sources": [task_source, metadata_source],
            "task": task_name,
            "text": "\n".join(value for value in (task_name, description) if value),
        }
    ]

    rubric_rows = rubrics.get("rubrics")
    if not isinstance(rubric_rows, list):
        raise WorkflowError("INVALID_RUBRICS", str(rubrics_artifact["path"]))
    for index, rubric in enumerate(rubric_rows):
        if not isinstance(rubric, Mapping) or not isinstance(rubric.get("requirement"), str):
            raise WorkflowError("INVALID_RUBRICS", str(rubrics_artifact["path"]))
        records.append(
            {
                **base,
                "knowledge_role": "design_requirement",
                "record_type": "workflow_requirement",
                "requirement_index": index,
                "rubric_id": str(rubric["id"]) if rubric.get("id") is not None else None,
                "sources": [rubrics_source],
                "text": rubric["requirement"],
            }
        )

    for row in narration:
        text = "\n".join(
            value for value in (row["action"], row["intent"], row["details"]) if value
        )
        records.append(
            {
                **base,
                "action": row["action"],
                "intent": row["intent"],
                "knowledge_role": "authoring_trace",
                "narration_index": row["index"],
                "record_type": "workflow_narration",
                "segment_application": row["app"],
                "sources": [narration_source],
                "text": text,
                "timestamp_range": {"basis": "video_seconds", "end": row["end_s"], "start": row["start_s"]},
            }
        )

    video_source = _hash_file(mirror, video_artifact)
    records.append(
        {
            **base,
            "evidence_pointer": {
                "availability": "LOCAL_MIRROR_ONLY",
                "source_path": video_artifact["path"],
                "timestamp_basis": "video_ms",
            },
            "fps": fps,
            "knowledge_role": "offline_evidence_pointer",
            "raw_media_policy": "OFFLINE_ONLY_NOT_COPIED",
            "record_type": "video_evidence",
            "sources": [video_source, metadata_source],
            "text": "Raw workflow video is available only in the local mirror as timestamp-addressable evidence.",
            "time_range_ms": {"end": duration_ms, "start": 0.0} if duration_ms is not None else None,
            "total_frames": total_frames,
        }
    )

    event_source, event_aggregate, _ = _stream_event_aggregate(
        mirror,
        events_artifact,
        target_application=str(base["application"]),
    )
    records.append(
        {
            **base,
            **event_aggregate,
            "knowledge_role": "workflow_activity_aggregate",
            "record_type": "event_aggregate",
            "sources": [event_source],
            "text": "Privacy-safe aggregate counts from the workflow event stream.",
        }
    )

    frame_source, frame_aggregate, timing = _stream_event_aggregate(
        mirror,
        frame_events_artifact,
        target_application=str(base["application"]),
        narration=narration,
    )
    records.append(
        {
            **base,
            **frame_aggregate,
            "knowledge_role": "workflow_activity_aggregate",
            "record_type": "frame_event_aggregate",
            "sources": [frame_source],
            "text": "Privacy-safe aggregate counts from timestamp-aligned frame events.",
        }
    )
    for row, stats in zip(narration, timing):
        records.append(
            {
                **base,
                "active_frame_count": len(stats["active_frames"]),
                "event_category_counts": dict(sorted(stats["category_counts"].items())),
                "event_count": stats["event_count"],
                "event_timestamp_range_ms": {
                    "end": stats["last_event_ms"],
                    "start": stats["first_event_ms"],
                },
                "event_type_counts": dict(sorted(stats["type_counts"].items())),
                "knowledge_role": "narration_timing",
                "narration_index": row["index"],
                "record_type": "narration_timing",
                "sources": [frame_source, narration_source],
                "text": "Frame-event timing aggregate aligned to one narration interval.",
                "timestamp_range": {"basis": "video_seconds", "end": row["end_s"], "start": row["start_s"]},
            }
        )

    inputs = sorted(
        (item for item in artifacts if item["artifact_type"] == "workflow_input"),
        key=lambda item: item["path"],
    )
    outputs = sorted(
        (item for item in artifacts if item["artifact_type"] == "workflow_output"),
        key=lambda item: item["path"],
    )
    artifact_sources = {}
    for artifact in [*inputs, *outputs]:
        source = _hash_file(mirror, artifact)
        artifact_sources[artifact["path"]] = source
        records.append(
            {
                **base,
                "artifact_role": "input" if artifact in inputs else "output",
                "knowledge_role": "workflow_artifact",
                "record_type": "artifact_metadata",
                "sources": [source],
                "text": f"Verified local {artifact['artifact_type'].removeprefix('workflow_')} artifact metadata.",
            }
        )
    records.extend(_transition_records(mirror, base, inputs, outputs, artifact_sources))
    return records


def _quarantine_record(
    manifest: Mapping[str, object], artifacts: list[dict], error: WorkflowError
) -> dict:
    fingerprint = _workflow_fingerprint(manifest, artifacts)
    base = _base_record(manifest, artifacts, fingerprint)
    artifact = next(
        (item for item in artifacts if item["path"] == error.source_path), artifacts[0]
    )
    return {
        **base,
        "eligible_for_production_retrieval": False,
        "knowledge_role": "workflow_quarantine",
        "quarantine_reason": error.code,
        "record_type": "workflow_quarantine",
        "sources": [_source_stub(artifact)],
        "text": "Workflow quarantined because its local source set could not be safely refined.",
    }


def _records_sha256(records: Iterable[Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(_json_bytes(record) + b"\n")
    return digest.hexdigest()


def _completion_record(
    base: Mapping[str, object], count: int, status: str, records_sha256: str
) -> dict:
    return {
        **base,
        "knowledge_role": "shard_control",
        "record_count": count,
        "records_sha256": records_sha256,
        "record_type": "workflow_completion",
        "status": status,
        "text": "Atomic workflow shard completion marker.",
    }


def _load_valid_shard(path: Path, expected_fingerprint: str) -> Optional[tuple[list[dict], str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    records = []
    last_line_terminated = False
    try:
        with path.open("rb") as handle:
            for raw_line in handle:
                last_line_terminated = raw_line.endswith(b"\n")
                if not raw_line.strip():
                    continue
                value = json.loads(raw_line)
                if not isinstance(value, dict):
                    return None
                records.append(value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not last_line_terminated or len(records) < 2:
        return None
    completion = records[-1]
    body = records[:-1]
    status = completion.get("status")
    if (
        completion.get("record_type") != "workflow_completion"
        or completion.get("record_count") != len(body)
        or completion.get("records_sha256") != _records_sha256(body)
        or completion.get("workflow_manifest_sha256") != expected_fingerprint
        or status not in {"completed", "quarantined"}
        or any(record.get("workflow_manifest_sha256") != expected_fingerprint for record in body)
    ):
        return None
    return body, status


def _shard_path(output: Path, artifacts: list[dict]) -> Path:
    first = artifacts[0]
    return output / SHARD_DIRECTORY / str(first["application"]) / f"{first['workflow_id']}.jsonl"


def refine(
    manifest_path: Path = DEFAULT_MANIFEST,
    mirror: Path = Path("."),
    output: Path = Path("cad1000-refined"),
    *,
    scope: str = "cadverify-core",
    application: Optional[str] = None,
    limit: Optional[int] = None,
    force: bool = False,
) -> dict:
    """Build resumable local workflow shards and one atomic combined snapshot."""
    if scope not in {"cadverify-core", "all"}:
        raise ValueError("scope must be 'cadverify-core' or 'all'")
    if application is not None and not application.strip("/"):
        raise ValueError("application must be non-empty")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        raise ValueError("limit must be at least 1")
    if not mirror.is_dir():
        raise ValueError(f"mirror is not a directory: {mirror}")

    manifest = load_manifest(manifest_path)
    rights = manifest.get("rights")
    if not isinstance(rights, Mapping) or rights.get("local_research") is not True:
        raise PermissionError(
            "manifest does not grant local_research rights; raw artifacts were not processed"
        )
    grouped: defaultdict[str, list[dict]] = defaultdict(list)
    for artifact in manifest["artifacts"]:
        workflow = artifact["workflow"]
        if not workflow:
            continue
        if application and artifact["application"] != application.strip("/"):
            continue
        if not application and scope == "cadverify-core" and artifact["application"] not in CADVERIFY_CORE_SOFTWARE:
            continue
        grouped[workflow].append(artifact)
    workflows = [(workflow, sorted(items, key=lambda item: item["path"])) for workflow, items in sorted(grouped.items())]
    if limit is not None:
        workflows = workflows[:limit]
    if not workflows:
        raise ValueError("manifest selection did not contain any workflows")

    output.mkdir(parents=True, exist_ok=True)
    selected: list[tuple[list[dict], str]] = []
    processed = reused = completed = quarantined = 0
    for _, artifacts in workflows:
        fingerprint = _workflow_fingerprint(manifest, artifacts)
        shard = _shard_path(output, artifacts)
        cached = None if force else _load_valid_shard(shard, fingerprint)
        if cached is not None:
            records, status = cached
            reused += 1
        else:
            try:
                records = _process_workflow(manifest, artifacts, mirror)
                records_sha256 = _records_sha256(records)
                status = "completed"
            except WorkflowError as exc:
                records = [_quarantine_record(manifest, artifacts, exc)]
                records_sha256 = _records_sha256(records)
                status = "quarantined"
            except Exception:
                records = [
                    _quarantine_record(
                        manifest,
                        artifacts,
                        WorkflowError("UNEXPECTED_WORKFLOW_PROCESSING_FAILURE", artifacts[0]["path"]),
                    )
                ]
                records_sha256 = _records_sha256(records)
                status = "quarantined"
            completion = _completion_record(
                records[0], len(records), status, records_sha256
            )
            _atomic_write(shard, [*records, completion])
            processed += 1
        completed += status == "completed"
        quarantined += status == "quarantined"
        selected.append((records, status))

    snapshot = output / SNAPSHOT_NAME
    record_count = _atomic_write(snapshot, (record for records, _ in selected for record in records))
    return {
        "completed_workflows": completed,
        "dataset": manifest["dataset"],
        "dataset_revision": manifest["dataset_revision"],
        "force": force,
        "processed_workflows": processed,
        "quarantined_workflows": quarantined,
        "records": record_count,
        "reused_workflows": reused,
        "scope": f"application:{application}" if application else scope,
        "selected_workflows": len(workflows),
        "snapshot": str(snapshot),
    }


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--mirror", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scope", choices=("cadverify-core", "all"), default="cadverify-core")
    parser.add_argument("--application")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            refine(
                args.manifest,
                args.mirror,
                args.output,
                scope=args.scope,
                application=args.application,
                limit=args.limit,
                force=args.force,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    _main()
