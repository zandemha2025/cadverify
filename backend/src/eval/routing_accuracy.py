"""Routing-accuracy harness (spec §6.1).

For each part with a human label in the 5 manufacturable classes, run the engine's
canonical routing sequence and compare ``best_process``'s **family** against the
human label. Produces top-1 accuracy, a per-family confusion matrix
(rows = true label, cols = engine family + ``no_route``), per-family
precision/recall, and a ranked mis-route list.

This module does NOT decide the smoke/gate banner — ``run.py`` owns honesty
framing. It just computes numbers from whatever ``{part_id: label}`` mapping it is
handed (real human labels, or the quarantined smoke seed under ``--smoke``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import trimesh

from src.eval import labels as label_store
from src.eval.engine import route_mesh
from src.eval.ontology import MANUFACTURABLE, NO_ROUTE


@dataclass
class PartResult:
    part_id: str
    filename: str
    true_label: str
    engine_best_process: Optional[str]
    engine_family: str
    engine_score: float
    top3: list[tuple[str, float]]
    dataset: Optional[str]
    license: Optional[str]
    correct: bool


@dataclass
class AccuracyReport:
    n_labeled: int                       # parts evaluated (manufacturable, mesh present)
    n_correct: int
    n_no_route: int
    per_label_counts: dict[str, int]
    # confusion[true_label][engine_family] = count
    confusion: dict[str, dict[str, int]]
    per_family: dict[str, dict[str, float]]  # {family: {precision, recall, support}}
    misroutes: list[PartResult]
    results: list[PartResult] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)

    @property
    def top1_accuracy(self) -> Optional[float]:
        if self.n_labeled == 0:
            return None
        return self.n_correct / self.n_labeled

    def to_dict(self) -> dict:
        return {
            "n_labeled": self.n_labeled,
            "n_correct": self.n_correct,
            "n_no_route": self.n_no_route,
            "top1_accuracy": self.top1_accuracy,
            "per_label_counts": self.per_label_counts,
            "confusion": self.confusion,
            "per_family": self.per_family,
            "misroutes": [
                {
                    "part_id": r.part_id,
                    "filename": r.filename,
                    "true_label": r.true_label,
                    "engine_best_process": r.engine_best_process,
                    "engine_family": r.engine_family,
                    "engine_score": r.engine_score,
                    "top3": [{"process": p, "score": s} for p, s in r.top3],
                    "dataset": r.dataset,
                    "license": r.license,
                }
                for r in self.misroutes
            ],
            "skipped": self.skipped,
        }


def _empty_confusion() -> dict[str, dict[str, int]]:
    cols = MANUFACTURABLE + [NO_ROUTE]
    return {row: {col: 0 for col in cols} for row in MANUFACTURABLE}


def evaluate(
    labels: dict[str, str],
    manifest: Optional[dict[str, dict]] = None,
) -> AccuracyReport:
    """Run routing accuracy for ``{part_id: human_label}`` (manufacturable only)."""
    if manifest is None:
        manifest = label_store.load_manifest()

    confusion = _empty_confusion()
    per_label_counts = {k: 0 for k in MANUFACTURABLE}
    results: list[PartResult] = []
    skipped: list[dict] = []
    n_correct = 0
    n_no_route = 0

    for part_id, true_label in sorted(labels.items()):
        if true_label not in MANUFACTURABLE:
            # unsure_other / unknown labels are not scored (spec §6.1).
            skipped.append({"part_id": part_id, "reason": f"label '{true_label}' not scored"})
            continue
        rec = manifest.get(part_id)
        if rec is None:
            skipped.append({"part_id": part_id, "reason": "not in manifest"})
            continue
        path = label_store.mesh_path(part_id, manifest)
        if not Path(path).exists():
            skipped.append({"part_id": part_id, "reason": "mesh file missing"})
            continue
        try:
            mesh = trimesh.load(path, force="mesh")
        except Exception as exc:  # pragma: no cover - corrupt mesh
            skipped.append({"part_id": part_id, "reason": f"load failed: {exc}"})
            continue

        routing = route_mesh(mesh, filename=rec.get("filename", f"{part_id}.stl"))
        engine_family = routing.engine_family
        engine_score = routing.top3[0][1] if routing.top3 else 0.0
        best_proc = routing.best_process.value if routing.best_process else None
        correct = engine_family == true_label

        per_label_counts[true_label] += 1
        confusion[true_label][engine_family] += 1
        if engine_family == NO_ROUTE:
            n_no_route += 1
        if correct:
            n_correct += 1

        results.append(
            PartResult(
                part_id=part_id,
                filename=rec.get("filename", ""),
                true_label=true_label,
                engine_best_process=best_proc,
                engine_family=engine_family,
                engine_score=engine_score,
                top3=routing.top3,
                dataset=rec.get("dataset"),
                license=rec.get("license"),
                correct=correct,
            )
        )

    n_labeled = len(results)
    # Mis-routes ranked by engine confidence (most-confident-wrong first) — the
    # actionable "where is the engine wrong" artifact.
    misroutes = sorted(
        [r for r in results if not r.correct],
        key=lambda r: r.engine_score,
        reverse=True,
    )
    per_family = _precision_recall(confusion)

    return AccuracyReport(
        n_labeled=n_labeled,
        n_correct=n_correct,
        n_no_route=n_no_route,
        per_label_counts=per_label_counts,
        confusion=confusion,
        per_family=per_family,
        misroutes=misroutes,
        results=results,
        skipped=skipped,
    )


def _precision_recall(confusion: dict[str, dict[str, int]]) -> dict[str, dict[str, float]]:
    """Per-family precision/recall from the confusion matrix.

    recall(f)    = confusion[f][f] / sum_over_cols(confusion[f])
    precision(f) = confusion[f][f] / sum_over_rows(confusion[*][f])
    ``no_route`` is a prediction-only column (no row), so it has recall but the
    diagonal is undefined; we report precision/recall only for the 5 real families.
    """
    out: dict[str, dict[str, float]] = {}
    for f in MANUFACTURABLE:
        tp = confusion[f][f]
        support = sum(confusion[f].values())            # true instances of f
        predicted = sum(confusion[r][f] for r in MANUFACTURABLE)  # engine said f
        recall = tp / support if support else 0.0
        precision = tp / predicted if predicted else 0.0
        out[f] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "support": support,
        }
    return out
