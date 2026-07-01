"""TINY smoke-seed generator (spec §6.3).

Writes ``data/labels.seed.jsonl`` — one part per ontology key, every line stamped
``labeler: "SMOKE_SEED"``. These are **synthetic seed labels, NOT human ground
truth**. They exist ONLY to exercise the pipeline (prove load -> route -> compare
-> report works) and are NEVER counted toward the human-label gate or mixed into
real metrics (the harness loads them only under ``--smoke``).

Part selection is deterministic and does NOT use the routing engine (that would be
circular). For the three families the corpus ``process_family_guess`` can express
(additive / subtractive / sheet_metal) we pick the first part with a matching
*heuristic guess* purely so the smoke run produces a non-degenerate spread; for the
remaining keys (injection_molding / casting / unsure_other) we pick distinct
arbitrary parts. The labels are fabricated and clearly marked — their correctness
is irrelevant; they only flex the plumbing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src.corpus.paths import LABELS_SEED
from src.eval import labels as label_store
from src.eval.labels import SMOKE_LABELER
from src.eval.ontology import LABELS


def _guess_family(rec: dict) -> str | None:
    g = rec.get("process_family_guess")
    if isinstance(g, dict):
        return g.get("family")
    if isinstance(g, str):
        return g
    return None


def select_smoke_parts(manifest: dict[str, dict]) -> dict[str, str]:
    """Pick one distinct part_id per ontology key (deterministic)."""
    # Stable ordering for determinism.
    items = sorted(manifest.items(), key=lambda kv: kv[0])
    chosen: dict[str, str] = {}
    used: set[str] = set()

    # Pass 1: families the heuristic guess can express get a loosely-matching part.
    for key in LABELS:
        for pid, rec in items:
            if pid in used:
                continue
            if _guess_family(rec) == key:
                chosen[key] = pid
                used.add(pid)
                break

    # Pass 2: fill any remaining key with the next unused part.
    for key in LABELS:
        if key in chosen:
            continue
        for pid, _rec in items:
            if pid not in used:
                chosen[key] = pid
                used.add(pid)
                break

    return chosen


def build_smoke_seed(force: bool = False) -> Path:
    """Generate ``labels.seed.jsonl`` if absent (or ``force``). Returns the path."""
    path = Path(LABELS_SEED)
    if path.exists() and not force:
        return path
    manifest = label_store.load_manifest()
    if not manifest:
        raise RuntimeError(
            "Cannot build smoke seed: corpus manifest is empty. Build the corpus first."
        )
    chosen = select_smoke_parts(manifest)
    ts = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for label, pid in chosen.items():
            rec = {
                "part_id": pid,
                "label": label,
                "labeler": SMOKE_LABELER,
                "ts": ts,
                "confidence": "smoke",
                "notes": "SMOKE — synthetic seed label, NOT human ground truth",
            }
            fh.write(json.dumps(rec) + "\n")
    return path


if __name__ == "__main__":  # pragma: no cover
    p = build_smoke_seed(force=True)
    print(f"wrote smoke seed: {p}")
    for k, v in label_store.smoke_labels().items():
        print(f"  {v:18s} {k}")
