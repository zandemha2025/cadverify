"""Manifest + human-label loading and last-write-wins resolution (spec §3, §6).

Pure read-side helpers. This module **never writes a label** — labels are
human-applied through the labeling tool only (``POST /api/v1/corpus/labels``).

Resolution contract (spec §3):
    effective_labels = {}
    for line in file (in order):
        effective_labels[(part_id, labeler)] = line     # last write wins
A part's label is then resolved either for a specific ``labeler`` or by
**majority** across labelers (default).

The smoke seed (``data/labels.seed.jsonl``, labeler ``SMOKE_SEED``) is loaded by a
*separate* function and is never returned by the human-label functions, so it can
never contaminate real metrics.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Optional

from src.corpus.paths import LABELS_PATH, LABELS_SEED, MANIFEST, MESH_DIR

SMOKE_LABELER = "SMOKE_SEED"


# ──────────────────────────────────────────────────────────────
# Manifest
# ──────────────────────────────────────────────────────────────
def load_manifest(path: Optional[Path] = None) -> dict[str, dict]:
    """Load ``manifest.jsonl`` into ``{part_id: record}`` (last line wins)."""
    path = path if path is not None else MANIFEST
    out: dict[str, dict] = {}
    if not Path(path).exists():
        return out
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            pid = rec.get("part_id")
            if pid:
                out[pid] = rec
    return out


def mesh_path(part_id: str, manifest: Optional[dict[str, dict]] = None) -> Path:
    """Resolve the on-disk STL path for a part_id (filename IS the sha256)."""
    if manifest and part_id in manifest and manifest[part_id].get("rel_path"):
        from src.corpus.paths import CORPUS_ROOT

        return (CORPUS_ROOT / manifest[part_id]["rel_path"]).resolve()
    return (MESH_DIR / f"{part_id}.stl").resolve()


# ──────────────────────────────────────────────────────────────
# Labels
# ──────────────────────────────────────────────────────────────
def _read_lines(path: Path) -> list[dict]:
    out: list[dict] = []
    if not Path(path).exists():
        return out
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("part_id") and rec.get("label"):
                out.append(rec)
    return out


def resolve_effective(lines: list[dict]) -> dict[tuple[str, str], dict]:
    """Last-write-wins per ``(part_id, labeler)`` (spec §3)."""
    eff: dict[tuple[str, str], dict] = {}
    for rec in lines:
        labeler = rec.get("labeler") or "local"
        eff[(rec["part_id"], labeler)] = rec
    return eff


def _majority(values: list[str]) -> Optional[str]:
    if not values:
        return None
    counts = Counter(values)
    top = counts.most_common()
    # Deterministic tie-break: highest count, then alphabetical key.
    top.sort(key=lambda kv: (-kv[1], kv[0]))
    return top[0][0]


def human_labels(
    labeler: Optional[str] = None,
    path: Optional[Path] = None,
) -> dict[str, str]:
    """Resolve human labels to ``{part_id: label}`` (excludes the smoke seed).

    The smoke labeler ``SMOKE_SEED`` is dropped unconditionally. When ``labeler``
    is given, only that labeler's labels are used; otherwise a part's label is the
    **majority** across labelers.
    """
    path = path if path is not None else LABELS_PATH
    eff = resolve_effective(_read_lines(path))
    by_part: dict[str, list[str]] = {}
    for (part_id, who), rec in eff.items():
        if who == SMOKE_LABELER:
            continue
        if labeler is not None and who != labeler:
            continue
        by_part.setdefault(part_id, []).append(rec["label"])
    resolved: dict[str, str] = {}
    for part_id, labs in by_part.items():
        lab = labs[0] if labeler is not None else _majority(labs)
        if lab:
            resolved[part_id] = lab
    return resolved


def part_label_records(path: Optional[Path] = None) -> dict[str, list[dict]]:
    """All resolved label records per part (for the part-detail endpoint / report)."""
    path = path if path is not None else LABELS_PATH
    eff = resolve_effective(_read_lines(path))
    out: dict[str, list[dict]] = {}
    for (part_id, _who), rec in eff.items():
        out.setdefault(part_id, []).append(rec)
    return out


def smoke_labels(path: Optional[Path] = None) -> dict[str, str]:
    """Load the smoke seed (labeler ``SMOKE_SEED``) -> ``{part_id: label}``.

    SMOKE ONLY — synthetic seed labels, NOT human ground truth.
    """
    path = path if path is not None else LABELS_SEED
    out: dict[str, str] = {}
    for rec in _read_lines(path):
        if (rec.get("labeler") or "") == SMOKE_LABELER:
            out[rec["part_id"]] = rec["label"]
    return out


def count_manufacturable(labels: dict[str, str]) -> int:
    """How many labels fall in the 5 manufacturable classes (for the gate)."""
    from src.eval.ontology import MANUFACTURABLE

    return sum(1 for v in labels.values() if v in MANUFACTURABLE)
