"""Immutable, rights-aware inventory for ``markov-ai/cad-1000-hours``.

This module inventories Hugging Face sibling metadata only.  It never downloads
the dataset artifacts themselves, and it never treats an upstream hash as a
locally verified checksum.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Optional, Union

from src.corpus.cad1000 import API_URL, DATASET_ID, DATASET_URL
from src.corpus.paths import CAD1000_KNOWLEDGE


SCHEMA_VERSION = "1.0"
DEFAULT_MANIFEST = CAD1000_KNOWLEDGE.with_name("cad1000-manifest.json")
RIGHTS_FIELDS = (
    "local_research",
    "production_retrieval",
    "training",
    "redistribution",
)
UNDECLARED_LICENSES = frozenset({"", "NONE", "NULL", "UNDECLARED", "UNKNOWN"})
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_MEDIA_TYPES = {
    ".csv": "text/csv",
    ".cs": "text/x-csharp",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jfif": "image/jpeg",
    ".jpg": "image/jpeg",
    ".json": "application/json",
    ".log": "text/plain",
    ".md": "text/markdown",
    ".mp4": "video/mp4",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".txt": "text/plain",
    ".vb": "text/x-visual-basic",
    ".webp": "image/webp",
}
_CAD_MEDIA_TYPES = {
    ".anl": "application/vnd.staad.analysis",
    ".catanalysis": "model/vnd.dassault.catanalysis",
    ".catdrawing": "model/vnd.dassault.catdrawing",
    ".catpart": "model/vnd.dassault.catpart",
    ".catproduct": "model/vnd.dassault.catproduct",
    ".dwg": "image/vnd.dwg",
    ".eprt": "model/vnd.edrawings.part",
    ".prt": "model/vnd.siemens-nx.part",
    ".rvt": "model/vnd.autodesk.revit",
    ".skp": "model/vnd.sketchup",
    ".sldasm": "model/vnd.solidworks.assembly",
    ".slddrw": "model/vnd.solidworks.drawing",
    ".sldprt": "model/vnd.solidworks.part",
    ".std": "application/vnd.staad.project",
    ".swj": "application/vnd.solidworks.journal",
}

JsonFetcher = Callable[[str], object]


def _fetch_json(url: str) -> object:
    request = urllib.request.Request(
        url, headers={"User-Agent": "cadverify-cad1000-manifest/1.0"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _normalized_license(dataset_info: Mapping[str, object]) -> str:
    card = dataset_info.get("cardData")
    value = card.get("license") if isinstance(card, Mapping) else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        return ",".join(sorted(item.strip() for item in value if item.strip())) or "UNDECLARED"
    return "UNDECLARED"


def _rights_policy(
    license_status: str, grants: Optional[Mapping[str, bool]] = None
) -> dict:
    unknown = set(grants or ()) - set(RIGHTS_FIELDS)
    if unknown:
        raise ValueError(f"Unknown rights fields: {sorted(unknown)}")
    rights = {field: False for field in RIGHTS_FIELDS}
    for field, value in (grants or {}).items():
        if not isinstance(value, bool):
            raise ValueError(f"Right {field!r} must be boolean")
        rights[field] = value
    if license_status.strip().upper() in UNDECLARED_LICENSES and any(rights.values()):
        raise ValueError("Undeclared license cannot grant artifact rights")
    return rights


def workflow_split(
    workflow: str, revision: str, *, held_out_percent: int = 20
) -> str:
    """Assign a workflow to a stable split using only pre-tuning identity."""
    if not isinstance(held_out_percent, int) or isinstance(held_out_percent, bool):
        raise ValueError("held_out_percent must be an integer")
    if not 1 <= held_out_percent <= 99:
        raise ValueError("held_out_percent must be between 1 and 99")
    identity = f"{DATASET_ID}@{revision}/{workflow}".encode("utf-8")
    bucket = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big") % 100
    return "held_out" if bucket < held_out_percent else "development"


def _workflow_identity(path: str) -> tuple:
    parts = PurePosixPath(path).parts
    if len(parts) < 3 or parts[0] == "assets":
        return None, None, None
    return parts[0], parts[1], "/".join(parts[:2])


def _media_type(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    return (
        _MEDIA_TYPES.get(suffix)
        or _CAD_MEDIA_TYPES.get(suffix)
        or "application/octet-stream"
    )


def _artifact_type(path: str) -> str:
    parts = PurePosixPath(path).parts
    name = parts[-1].lower()
    if len(parts) == 1:
        return "dataset_documentation" if name.endswith(".md") else "dataset_metadata"
    if parts[0] == "assets":
        return "dataset_asset"
    if len(parts) >= 4 and parts[-2] == "input_files":
        return "workflow_input"
    if len(parts) >= 4 and parts[-2] == "output_files":
        return "workflow_output"
    return {
        "clip.mp4": "workflow_video",
        "events.json": "event_stream",
        "frame_events.json": "frame_event_stream",
        "metadata.json": "workflow_metadata",
        "narration.json": "narration",
        "rubrics.json": "rubric",
        "task_desc.json": "task_description",
        "task_overview.pdf": "task_overview",
    }.get(name, "workflow_artifact")


def _safe_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Artifact path must be a non-empty POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"Unsafe artifact path: {value!r}")
    return value


def _artifact(
    sibling: Mapping[str, object],
    *,
    revision: str,
    license_status: str,
    rights: Mapping[str, bool],
    held_out_percent: int,
) -> dict:
    path = _safe_path(sibling.get("rfilename"))
    raw_bytes = sibling.get("size")
    size = raw_bytes if isinstance(raw_bytes, int) and not isinstance(raw_bytes, bool) and raw_bytes >= 0 else None
    lfs = sibling.get("lfs")
    supplied_hash = lfs.get("sha256") if isinstance(lfs, Mapping) else None
    if supplied_hash is not None and (
        not isinstance(supplied_hash, str)
        or not _SHA256_RE.fullmatch(supplied_hash.lower())
    ):
        raise ValueError(f"Invalid upstream SHA-256 for {path}")
    sha256 = supplied_hash.lower() if isinstance(supplied_hash, str) else None
    application, workflow_id, workflow = _workflow_identity(path)
    quoted_path = urllib.parse.quote(path, safe="/")
    split = (
        workflow_split(workflow, revision, held_out_percent=held_out_percent)
        if workflow
        else "not_applicable"
    )
    return {
        "application": application,
        "artifact_type": _artifact_type(path),
        "bytes": size,
        "bytes_status": "UPSTREAM_SUPPLIED" if size is not None else "NOT_SUPPLIED_UNVERIFIED",
        "customer_data_excluded": True,
        "dataset_revision": revision,
        "immutable_url": f"{DATASET_URL}/resolve/{revision}/{quoted_path}",
        "license_status": license_status,
        "media_type": _media_type(path),
        "path": path,
        "rights": dict(rights),
        "sha256": sha256,
        "sha256_status": (
            "UPSTREAM_SUPPLIED_UNVERIFIED_LOCALLY"
            if sha256
            else "NOT_SUPPLIED_UNVERIFIED"
        ),
        "split": split,
        "workflow": workflow,
        "workflow_id": workflow_id,
    }


def _aggregate(artifacts: list) -> dict:
    known_bytes = sum(item["bytes"] for item in artifacts if item["bytes"] is not None)
    applications = defaultdict(lambda: {"artifacts": 0, "bytes": 0, "workflows": set()})
    artifact_types = Counter()
    media_types = Counter()
    workflows_by_split = defaultdict(set)
    workflow_set = set()
    for item in artifacts:
        artifact_types[item["artifact_type"]] += 1
        media_types[item["media_type"]] += 1
        workflow = item["workflow"]
        application = item["application"]
        if workflow:
            workflow_set.add(workflow)
            workflows_by_split[item["split"]].add(workflow)
        if application:
            row = applications[application]
            row["artifacts"] += 1
            row["bytes"] += item["bytes"] or 0
            if workflow:
                row["workflows"].add(workflow)
    return {
        "artifact_count": len(artifacts),
        "artifacts_with_unknown_bytes": sum(item["bytes"] is None for item in artifacts),
        "artifacts_with_upstream_sha256": sum(item["sha256"] is not None for item in artifacts),
        "artifacts_without_upstream_sha256": sum(item["sha256"] is None for item in artifacts),
        "by_application": {
            name: {
                "artifacts": row["artifacts"],
                "bytes": row["bytes"],
                "workflows": len(row["workflows"]),
            }
            for name, row in sorted(applications.items())
        },
        "by_artifact_type": dict(sorted(artifact_types.items())),
        "by_media_type": dict(sorted(media_types.items())),
        "known_bytes": known_bytes,
        "workflow_count": len(workflow_set),
        "workflow_splits": {
            name: len(values) for name, values in sorted(workflows_by_split.items())
        },
    }


def _reconciliation(source: list, artifacts: list, aggregates: Mapping[str, object]) -> dict:
    source_known_bytes = sum(
        item["size"]
        for item in source
        if isinstance(item.get("size"), int)
        and not isinstance(item.get("size"), bool)
        and item["size"] >= 0
    )
    source_unknown_bytes = sum(
        not (
            isinstance(item.get("size"), int)
            and not isinstance(item.get("size"), bool)
            and item["size"] >= 0
        )
        for item in source
    )
    count_matches = len(source) == len(artifacts) == aggregates["artifact_count"]
    bytes_match = (
        source_known_bytes == aggregates["known_bytes"]
        and source_unknown_bytes == aggregates["artifacts_with_unknown_bytes"]
    )
    return {
        "artifact_count_matches": count_matches,
        "bytes_match": bytes_match,
        "complete": count_matches and bytes_match,
        "manifest_artifact_count": len(artifacts),
        "manifest_known_bytes": aggregates["known_bytes"],
        "source_artifact_count": len(source),
        "source_known_bytes": source_known_bytes,
        "source_unknown_bytes": source_unknown_bytes,
    }


def build_manifest(
    dataset_info: object,
    *,
    grants: Optional[Mapping[str, bool]] = None,
    held_out_percent: int = 20,
) -> dict:
    """Build a deterministic manifest from one Hugging Face dataset-info response."""
    if not isinstance(dataset_info, Mapping):
        raise ValueError("Hugging Face dataset info was not an object")
    if dataset_info.get("id") != DATASET_ID:
        raise ValueError(f"Unexpected dataset id: {dataset_info.get('id')!r}")
    revision = str(dataset_info.get("sha", "")).lower()
    if not _COMMIT_RE.fullmatch(revision):
        raise ValueError("Dataset info did not contain an immutable commit SHA")
    source = dataset_info.get("siblings")
    if not isinstance(source, list) or not source:
        raise ValueError("Dataset info did not contain a non-empty siblings list")
    if not all(isinstance(item, Mapping) for item in source):
        raise ValueError("Dataset sibling was not an object")

    license_status = _normalized_license(dataset_info)
    rights = _rights_policy(license_status, grants)
    artifacts = sorted(
        (
            _artifact(
                item,
                revision=revision,
                license_status=license_status,
                rights=rights,
                held_out_percent=held_out_percent,
            )
            for item in source
        ),
        key=lambda item: item["path"],
    )
    if len({item["path"] for item in artifacts}) != len(artifacts):
        raise ValueError("Dataset info contained duplicate artifact paths")
    aggregates = _aggregate(artifacts)
    manifest = {
        "aggregates": aggregates,
        "artifacts": artifacts,
        "customer_data_excluded": True,
        "dataset": DATASET_ID,
        "dataset_revision": revision,
        "dataset_url": DATASET_URL,
        "license_status": license_status,
        "reconciliation": _reconciliation(source, artifacts, aggregates),
        "rights": rights,
        "schema_version": SCHEMA_VERSION,
        "source_ref": revision,
        "split_policy": {
            "algorithm": "sha256_mod_100_v1",
            "frozen_before_tuning": True,
            "held_out_percent": held_out_percent,
            "unit": "workflow",
        },
    }
    return validate_manifest(manifest)


def _validate_artifact(
    artifact: object,
    *,
    revision: str,
    license_status: str,
    rights: Mapping[str, bool],
    held_out_percent: int,
) -> None:
    if not isinstance(artifact, Mapping):
        raise ValueError("Manifest artifact was not an object")
    path = _safe_path(artifact.get("path"))
    size = artifact.get("bytes")
    if size is not None and (
        not isinstance(size, int) or isinstance(size, bool) or size < 0
    ):
        raise ValueError(f"Invalid artifact byte count for {path}")
    sha256 = artifact.get("sha256")
    if sha256 is not None and (
        not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256)
    ):
        raise ValueError(f"Invalid artifact SHA-256 for {path}")
    if artifact.get("dataset_revision") != revision:
        raise ValueError(f"Artifact revision mismatch for {path}")
    application, workflow_id, workflow = _workflow_identity(path)
    quoted_path = urllib.parse.quote(path, safe="/")
    if (
        artifact.get("application") != application
        or artifact.get("workflow_id") != workflow_id
        or artifact.get("workflow") != workflow
        or artifact.get("artifact_type") != _artifact_type(path)
        or artifact.get("media_type") != _media_type(path)
        or artifact.get("immutable_url")
        != f"{DATASET_URL}/resolve/{revision}/{quoted_path}"
    ):
        raise ValueError(f"Artifact identity mismatch for {path}")
    expected_bytes_status = (
        "UPSTREAM_SUPPLIED" if size is not None else "NOT_SUPPLIED_UNVERIFIED"
    )
    if artifact.get("bytes_status") != expected_bytes_status:
        raise ValueError(f"Artifact byte status mismatch for {path}")
    if artifact.get("license_status") != license_status or artifact.get("rights") != rights:
        raise ValueError(f"Artifact rights mismatch for {path}")
    if artifact.get("customer_data_excluded") is not True:
        raise ValueError(f"Customer-data exclusion missing for {path}")
    expected_split = (
        workflow_split(workflow, revision, held_out_percent=held_out_percent)
        if workflow
        else "not_applicable"
    )
    if artifact.get("split") != expected_split:
        raise ValueError(f"Artifact split mismatch for {path}")
    expected_sha_status = (
        "UPSTREAM_SUPPLIED_UNVERIFIED_LOCALLY"
        if sha256 is not None
        else "NOT_SUPPLIED_UNVERIFIED"
    )
    if artifact.get("sha256_status") != expected_sha_status:
        raise ValueError(f"Artifact SHA-256 status mismatch for {path}")


def validate_manifest(manifest: object) -> dict:
    """Reject malformed, rights-unsafe, or unreconciled manifests."""
    if not isinstance(manifest, dict):
        raise ValueError("Manifest was not an object")
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("dataset") != DATASET_ID:
        raise ValueError("Unsupported CAD1000 manifest")
    revision = manifest.get("dataset_revision")
    if not isinstance(revision, str) or not _COMMIT_RE.fullmatch(revision):
        raise ValueError("Manifest revision was not an immutable commit SHA")
    if manifest.get("source_ref") != revision:
        raise ValueError("Manifest source reference did not match dataset revision")
    if manifest.get("dataset_url") != DATASET_URL:
        raise ValueError("Manifest dataset URL was invalid")
    license_status = manifest.get("license_status")
    if not isinstance(license_status, str):
        raise ValueError("Manifest license status was invalid")
    rights = manifest.get("rights")
    if not isinstance(rights, dict) or set(rights) != set(RIGHTS_FIELDS):
        raise ValueError("Manifest rights were invalid")
    if any(not isinstance(value, bool) for value in rights.values()):
        raise ValueError("Manifest rights must be boolean")
    _rights_policy(license_status, rights)
    if manifest.get("customer_data_excluded") is not True:
        raise ValueError("Manifest must exclude customer data")
    split_policy = manifest.get("split_policy")
    if not isinstance(split_policy, dict) or split_policy.get("algorithm") != "sha256_mod_100_v1":
        raise ValueError("Manifest split policy was invalid")
    held_out_percent = split_policy.get("held_out_percent")
    if not isinstance(held_out_percent, int) or isinstance(held_out_percent, bool):
        raise ValueError("Manifest held-out percentage was invalid")
    workflow_split("validation", revision, held_out_percent=held_out_percent)
    if split_policy.get("unit") != "workflow" or split_policy.get("frozen_before_tuning") is not True:
        raise ValueError("Manifest split policy was not frozen by workflow")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("Manifest artifacts were missing")
    for artifact in artifacts:
        _validate_artifact(
            artifact,
            revision=revision,
            license_status=license_status,
            rights=rights,
            held_out_percent=held_out_percent,
        )
    paths = [item["path"] for item in artifacts]
    if len(set(paths)) != len(paths) or paths != sorted(paths):
        raise ValueError("Manifest artifact paths must be unique and sorted")
    aggregates = _aggregate(artifacts)
    if manifest.get("aggregates") != aggregates:
        raise ValueError("Manifest aggregates did not reconcile")
    reconciliation = manifest.get("reconciliation")
    if not isinstance(reconciliation, dict):
        raise ValueError("Manifest reconciliation was missing")
    if (
        reconciliation.get("complete") is not True
        or reconciliation.get("artifact_count_matches") is not True
        or reconciliation.get("bytes_match") is not True
        or reconciliation.get("source_artifact_count") != aggregates["artifact_count"]
        or reconciliation.get("manifest_artifact_count") != aggregates["artifact_count"]
        or reconciliation.get("source_known_bytes") != aggregates["known_bytes"]
        or reconciliation.get("manifest_known_bytes") != aggregates["known_bytes"]
        or reconciliation.get("source_unknown_bytes")
        != aggregates["artifacts_with_unknown_bytes"]
    ):
        raise ValueError("Manifest source reconciliation was invalid")
    return manifest


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict:
    with path.open(encoding="utf-8") as handle:
        return validate_manifest(json.load(handle))


def write_manifest(path: Path, manifest: object) -> dict:
    """Validate and atomically replace a local immutable manifest snapshot."""
    validated = validate_manifest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(validated, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return validated


def generate_manifest(
    output: Path = DEFAULT_MANIFEST,
    *,
    dataset_info: Optional[Union[Mapping[str, object], Path]] = None,
    resume: bool = True,
    fetch_json: JsonFetcher = _fetch_json,
    grants: Optional[Mapping[str, bool]] = None,
    held_out_percent: int = 20,
) -> dict:
    """Create an atomic snapshot, or resume an already-valid pinned snapshot."""
    if resume and output.exists():
        return load_manifest(output)
    if isinstance(dataset_info, Path):
        with dataset_info.open(encoding="utf-8") as handle:
            source = json.load(handle)
    elif dataset_info is not None:
        source = dataset_info
    else:
        source = fetch_json(f"{API_URL}?blobs=true")
    return write_manifest(
        output,
        build_manifest(source, grants=grants, held_out_percent=held_out_percent),
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dataset-info", type=Path, help="local Hugging Face API response")
    parser.add_argument("--refresh", action="store_true", help="replace an existing snapshot")
    parser.add_argument("--held-out-percent", type=int, default=20)
    args = parser.parse_args()
    manifest = generate_manifest(
        args.output,
        dataset_info=args.dataset_info,
        resume=not args.refresh,
        held_out_percent=args.held_out_percent,
    )
    print(json.dumps({**manifest["aggregates"], "dataset_revision": manifest["dataset_revision"]}))


if __name__ == "__main__":
    _main()
