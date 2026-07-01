"""Corpus + human-labeling endpoints (Cycle 4, spec §4).

LOCAL SINGLE-OPERATOR TOOL. Mounted only when ``LABELING_ENABLED=1`` (see
main.py) so the labeling surface never ships to production and no CAD egresses.
These routes deliberately do NOT use ``require_api_key`` / ``require_role`` — they
are protected by the env gate + running on localhost. Parts are streamed straight
from the local ``data/corpus`` to the viewer; nothing leaves the machine.

Endpoints (all under ``/api/v1/corpus``):
    GET  /parts                       paginated corpus list (+ label overlay)
    GET  /parts/{part_id}/mesh.stl     stream one STL (path-safe, ETag = content hash)
    GET  /parts/{part_id}              one manifest record + all its labels
    POST /labels                       record one human label (append-only)
    GET  /progress                     labeling progress + coverage view
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Optional, Union

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.corpus.paths import CORPUS_ROOT, LABELS_PATH, MANIFEST, ensure_dirs

# Structured logger — routes through the app's structlog JSON+scrub+request_id
# pipeline, so corpus-tool events are request-correlated. This is a local,
# dev-gated tool (LABELING_ENABLED=1); we log corpus ids/labels (not CAD bytes).
logger = structlog.get_logger("cadverify.corpus")

router = APIRouter(prefix="/api/v1/corpus", tags=["corpus-labeling"])

# 6-key ontology (spec §1.2). Prefer the shared eval constant; fall back to the
# literal keys so the tool runs even if the eval package is not built yet.
try:  # pragma: no cover - import shape varies during parallel build
    from src.eval.ontology import LABELS as ONTOLOGY_LABELS  # type: ignore
except Exception:
    ONTOLOGY_LABELS = [
        "additive",
        "subtractive",
        "injection_molding",
        "sheet_metal",
        "casting",
        "unsure_other",
    ]


# ----------------------------------------------------------------------------
# Manifest (cached, reloaded on mtime change) + demo-fallback seeding
# ----------------------------------------------------------------------------

_manifest_cache: list[dict] = []
_manifest_index: dict[str, dict] = {}
_manifest_mtime: float = -1.0
_seed_attempted = False


def _ensure_seeded() -> None:
    """Seed a demo corpus from the repo parts iff the manifest is empty (§ fallback)."""
    global _seed_attempted
    if _seed_attempted:
        return
    _seed_attempted = True
    try:
        from src.corpus.demo_seed import ensure_corpus_available

        ensure_corpus_available()
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("corpus_seed_failed", error=str(exc))


def _get_manifest() -> list[dict]:
    """Return manifest records (deduped by part_id), reloading on file change."""
    global _manifest_mtime, _manifest_cache, _manifest_index

    _ensure_seeded()
    if not MANIFEST.exists():
        _manifest_cache, _manifest_index = [], {}
        return _manifest_cache

    mtime = MANIFEST.stat().st_mtime
    if mtime == _manifest_mtime and _manifest_cache:
        return _manifest_cache

    records: list[dict] = []
    index: dict[str, dict] = {}
    with MANIFEST.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            pid = rec.get("part_id")
            if not pid or pid in index:
                continue  # dedup by part_id; first occurrence wins
            records.append(rec)
            index[pid] = rec

    _manifest_cache, _manifest_index, _manifest_mtime = records, index, mtime
    return _manifest_cache


def _manifest_record(part_id: str) -> Optional[dict]:
    _get_manifest()
    return _manifest_index.get(part_id)


def _guess_family(rec: dict) -> Optional[str]:
    """Extract the process_family_guess family string (or None). Never a label."""
    guess = rec.get("process_family_guess")
    if isinstance(guess, dict):
        return guess.get("family")
    if isinstance(guess, str):
        return guess
    return None


# ----------------------------------------------------------------------------
# Labels (append-only; last-write-wins per (part_id, labeler))
# ----------------------------------------------------------------------------


def _read_effective_labels() -> dict[tuple, dict]:
    """Scan labels.jsonl; keep the LAST record per (part_id, labeler)."""
    eff: dict[tuple, dict] = {}
    if not LABELS_PATH.exists():
        return eff
    with LABELS_PATH.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            pid, who = rec.get("part_id"), rec.get("labeler")
            if pid and who:
                eff[(pid, who)] = rec
    return eff


def _labels_by_part(eff: dict[tuple, dict]) -> dict[str, list[dict]]:
    by_part: dict[str, list[dict]] = {}
    for (pid, _who), rec in eff.items():
        by_part.setdefault(pid, []).append(rec)
    return by_part


def _resolved_label(
    part_id: str,
    labeler: Optional[str],
    eff: dict[tuple, dict],
    by_part: dict[str, list[dict]],
) -> Optional[str]:
    """Resolve a part's label for ``labeler`` (exact), else majority across labelers."""
    if labeler:
        rec = eff.get((part_id, labeler))
        return rec.get("label") if rec else None
    recs = by_part.get(part_id)
    if not recs:
        return None
    counts = Counter(r.get("label") for r in recs if r.get("label"))
    if not counts:
        return None
    return counts.most_common(1)[0][0]


# ----------------------------------------------------------------------------
# GET /parts — paginated list
# ----------------------------------------------------------------------------


@router.get("/parts")
def list_parts(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    unlabeled_only: bool = False,
    labeler: Optional[str] = None,
):
    manifest = _get_manifest()
    eff = _read_effective_labels()
    by_part = _labels_by_part(eff)

    labeled_total = sum(
        1 for r in manifest if _resolved_label(r["part_id"], labeler, eff, by_part)
    )

    rows = manifest
    if unlabeled_only:
        rows = [
            r
            for r in manifest
            if _resolved_label(r["part_id"], labeler, eff, by_part) is None
        ]

    total = len(rows)
    page = rows[offset : offset + limit]
    parts = [
        {
            "part_id": r["part_id"],
            "filename": r.get("filename"),
            "dataset": r.get("dataset"),
            "license": r.get("license"),
            "n_faces": r.get("n_faces"),
            "volume_cm3": r.get("volume_cm3"),
            "bbox_mm": r.get("bbox_mm"),
            "watertight": r.get("watertight"),
            "process_family_guess": _guess_family(r),
            "label": _resolved_label(r["part_id"], labeler, eff, by_part),
            "mesh_url": f"/api/v1/corpus/parts/{r['part_id']}/mesh.stl",
        }
        for r in page
    ]

    manifest_total = len(manifest)
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "labeled": labeled_total,
        "unlabeled": manifest_total - labeled_total,
        "parts": parts,
    }


# ----------------------------------------------------------------------------
# GET /parts/{part_id}/mesh.stl — stream one STL (path-safe)
# ----------------------------------------------------------------------------


@router.get("/parts/{part_id}/mesh.stl")
def stream_mesh(part_id: str):
    rec = _manifest_record(part_id)
    if rec is None:
        logger.warning("corpus_mesh_404", part_id=part_id, reason="not_in_manifest")
        raise HTTPException(status_code=404, detail="part_id not in manifest")

    rel_path = rec.get("rel_path") or f"meshes/{part_id}.stl"
    root = CORPUS_ROOT.resolve()
    path = (CORPUS_ROOT / rel_path).resolve()
    if not path.is_relative_to(root):  # reject traversal (py3.9+)
        logger.warning("corpus_mesh_404", part_id=part_id, reason="path_traversal")
        raise HTTPException(status_code=404, detail="invalid mesh path")
    if not path.is_file():
        logger.warning("corpus_mesh_404", part_id=part_id, reason="file_missing")
        raise HTTPException(status_code=404, detail="mesh file missing")

    return FileResponse(
        str(path),
        media_type="model/stl",
        filename=f"{part_id}.stl",
        headers={"ETag": part_id, "Cache-Control": "public, max-age=3600"},
    )


# ----------------------------------------------------------------------------
# GET /parts/{part_id} — one record + its labels
# ----------------------------------------------------------------------------


@router.get("/parts/{part_id}")
def get_part(part_id: str):
    rec = _manifest_record(part_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="part_id not in manifest")

    eff = _read_effective_labels()
    labels = [
        {
            "labeler": r.get("labeler"),
            "label": r.get("label"),
            "ts": r.get("ts"),
            "confidence": r.get("confidence"),
            "notes": r.get("notes"),
        }
        for (pid, _who), r in eff.items()
        if pid == part_id
    ]
    out = dict(rec)
    out["process_family_guess"] = _guess_family(rec)
    out["labels"] = labels
    return out


# ----------------------------------------------------------------------------
# POST /labels — record a human label (append-only)
# ----------------------------------------------------------------------------


class LabelIn(BaseModel):
    part_id: str
    label: str
    labeler: Optional[str] = None
    confidence: Optional[Union[str, float]] = None
    notes: Optional[str] = Field(default=None, max_length=4000)


@router.post("/labels")
def post_label(body: LabelIn, request: Request):
    if _manifest_record(body.part_id) is None:
        raise HTTPException(status_code=404, detail="part_id not in manifest")
    if body.label not in ONTOLOGY_LABELS:
        raise HTTPException(
            status_code=422,
            detail=f"label must be one of {ONTOLOGY_LABELS}",
        )

    labeler = (
        body.labeler
        or request.headers.get("X-Labeler")
        or os.getenv("LABELER")
        or "local"
    )
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    record = {
        "part_id": body.part_id,
        "label": body.label,
        "labeler": labeler,
        "ts": ts,
    }
    if body.confidence is not None:
        record["confidence"] = body.confidence
    if body.notes:
        record["notes"] = body.notes

    ensure_dirs()
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LABELS_PATH.open("a") as fh:  # append-only — never mutate prior lines
        fh.write(json.dumps(record) + "\n")
        fh.flush()

    logger.info(
        "corpus_label",
        part_id=body.part_id,
        label=body.label,
        labeler=labeler,
        ts=ts,
    )

    return {
        "ok": True,
        "part_id": body.part_id,
        "label": body.label,
        "labeler": labeler,
        "ts": ts,
    }


# ----------------------------------------------------------------------------
# GET /progress — labeling progress + coverage view
# ----------------------------------------------------------------------------


@router.get("/progress")
def progress(labeler: Optional[str] = None):
    manifest = _get_manifest()
    eff = _read_effective_labels()
    by_part = _labels_by_part(eff)

    per_label = Counter()
    labeled = 0
    for r in manifest:
        lbl = _resolved_label(r["part_id"], labeler, eff, by_part)
        if lbl:
            labeled += 1
            per_label[lbl] += 1

    per_label_counts = {k: per_label.get(k, 0) for k in ONTOLOGY_LABELS}
    per_guess_counts = Counter(
        g for g in (_guess_family(r) for r in manifest) if g
    )
    labelers = sorted({who for (_pid, who) in eff.keys()})

    return {
        "total_parts": len(manifest),
        "labeled": labeled,
        "unlabeled": len(manifest) - labeled,
        "per_label_counts": per_label_counts,
        "per_guess_counts": dict(per_guess_counts),
        "labelers": labelers,
    }
