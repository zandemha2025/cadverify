"""Eval CLI orchestrator (spec §6).

    python -m src.eval.run --smoke            # exercise the pipeline on the seed
    python -m src.eval.run                     # real run (gated on >=30 human labels)
    python -m src.eval.run --build-features    # build data/corpus/features.npz (heavy)

Honesty framing (spec §6.3) lives here:

* Real metrics are **gated**. Until there are ``--min-human-labels`` (default 30)
  human labels in the 5 manufacturable classes, every number is marked
  PROVISIONAL and no headline accuracy is emitted.
* The smoke seed is loaded ONLY under ``--smoke`` and every output is stamped
  ``SMOKE — synthetic seed labels, NOT human ground truth``.

Writes ``outputs/c4-accuracy.json`` + ``outputs/c4-accuracy.md`` and prints a
confusion matrix + a k-NN similarity example to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.corpus.paths import FEATURES_NPZ, REPO_ROOT
from src.eval import labels as label_store
from src.eval import similarity as sim
from src.eval.ontology import MANUFACTURABLE, NO_ROUTE
from src.eval.routing_accuracy import AccuracyReport, evaluate
from src.eval.seed import build_smoke_seed

DEFAULT_OUT_DIR = REPO_ROOT / "outputs"
MIN_HUMAN_LABELS = 30

SMOKE_TAG = "SMOKE — synthetic seed labels, NOT human ground truth"
GATE_BANNER = "INSUFFICIENT HUMAN LABELS (n={n} < {thr}) — PIPELINE SMOKE ONLY, NOT GROUND TRUTH"


# ──────────────────────────────────────────────────────────────
# Feature store (full npz if present, else a bounded in-memory sample)
# ──────────────────────────────────────────────────────────────
def _ensure_store(
    manifest: dict[str, dict],
    must_cover: set[str],
    sample: int,
) -> tuple[sim.FeatureStore, str]:
    """Return (store, provenance_note). Prefer the persisted full matrix."""
    if Path(FEATURES_NPZ).exists():
        store = sim.load_features()
        covered = set(store.part_ids.tolist())
        if must_cover <= covered:
            return store, f"features.npz (full corpus, N={len(covered)})"
        # Persisted matrix is stale / partial — extend with the missing parts.
        extra = [p for p in must_cover if p not in covered]
        ext = sim.build_feature_matrix(part_ids=extra, manifest=manifest)
        import numpy as np

        part_ids = np.concatenate([store.part_ids, ext.part_ids])
        X = np.vstack([store.X, ext.X])
        merged = sim.FeatureStore(
            part_ids=part_ids,
            X=X,
            mean=X.mean(axis=0),
            std=X.std(axis=0) + 1e-9,
            dims=store.dims,
        )
        return merged, f"features.npz + {len(extra)} on-the-fly rows (N={len(part_ids)})"

    # No persisted matrix: build a bounded sample including everything we must cover.
    ids = list(must_cover)
    for pid in manifest:
        if len(ids) >= max(sample, len(must_cover)):
            break
        if pid not in must_cover:
            ids.append(pid)
    store = sim.build_feature_matrix(part_ids=ids, manifest=manifest)
    return store, f"on-the-fly SAMPLE matrix (N={len(ids)}; run --build-features for the full corpus)"


def _pick_query(manifest: dict[str, dict], pool: dict[str, str]) -> Optional[str]:
    """A real corpus part to use as the similarity-demo query (not in the pool)."""
    for pid in sorted(manifest):
        if pid not in pool:
            return pid
    return None


# ──────────────────────────────────────────────────────────────
# Rendering
# ──────────────────────────────────────────────────────────────
def render_confusion_text(report: AccuracyReport) -> str:
    cols = MANUFACTURABLE + [NO_ROUTE]
    short = {
        "additive": "addtv",
        "subtractive": "subtr",
        "injection_molding": "injmo",
        "sheet_metal": "sheet",
        "casting": "cast ",
        NO_ROUTE: "noRte",
    }
    head = "true \\ engine  " + " ".join(f"{short[c]:>6}" for c in cols) + "   | total"
    lines = [head, "-" * len(head)]
    for row in MANUFACTURABLE:
        cells = " ".join(f"{report.confusion[row][c]:>6}" for c in cols)
        total = sum(report.confusion[row].values())
        lines.append(f"{row:14} {cells}   | {total}")
    return "\n".join(lines)


def render_markdown(
    report: AccuracyReport,
    *,
    smoke: bool,
    gate_ok: bool,
    n_human: int,
    thr: int,
    sim_example: Optional[dict],
    sim_note: str,
    generated_at: str,
) -> str:
    L: list[str] = []
    L.append("# Cycle 4 — Routing-Accuracy + Similarity (machine report)")
    L.append("")
    L.append(f"_Generated {generated_at} by `python -m src.eval.run`._")
    L.append("")

    # Honesty banners first.
    if smoke:
        L.append(f"> **{SMOKE_TAG}.** This run scored the quarantined smoke seed")
        L.append("> (`data/labels.seed.jsonl`, labeler `SMOKE_SEED`) purely to exercise the")
        L.append("> pipeline. These numbers are **NOT** an accuracy measurement.")
    if not gate_ok:
        L.append("")
        L.append(f"> **{GATE_BANNER.format(n=n_human, thr=thr)}**")
        L.append("> Headline accuracy is withheld; the confusion matrix below is PROVISIONAL.")
    L.append("")

    status = "SMOKE" if smoke else ("PROVISIONAL" if not gate_ok else "REAL")
    L.append(f"**Status:** {status}  |  **human labels (manufacturable):** {n_human}  "
             f"|  **gate:** {n_human}/{thr}")
    L.append("")

    L.append("## Coverage")
    L.append("")
    L.append(f"- Parts scored this run: **{report.n_labeled}**")
    L.append(f"- `no_route` (engine produced no pick): **{report.n_no_route}**")
    L.append(f"- Per-label counts: `{json.dumps(report.per_label_counts)}`")
    if report.skipped:
        L.append(f"- Skipped: **{len(report.skipped)}** "
                 f"(`{json.dumps(report.skipped[:5])}`{' …' if len(report.skipped) > 5 else ''})")
    L.append("")

    L.append("## Top-1 accuracy")
    L.append("")
    if smoke or not gate_ok:
        L.append("_Withheld — not ground truth (see banner). Raw fraction shown for plumbing only:_")
        frac = report.top1_accuracy
        L.append(f"- raw correct/scored = **{report.n_correct}/{report.n_labeled}** "
                 f"({'n/a' if frac is None else f'{frac:.3f}'}) — PROVISIONAL/SMOKE")
    else:
        L.append(f"- **top-1 accuracy = {report.top1_accuracy:.4f}** "
                 f"({report.n_correct}/{report.n_labeled})")
    L.append("")

    L.append("## Confusion matrix (rows = true human label, cols = engine family)")
    L.append("")
    L.append("```")
    L.append(render_confusion_text(report))
    L.append("```")
    L.append("")

    L.append("## Per-family precision / recall")
    L.append("")
    L.append("| family | precision | recall | support |")
    L.append("|---|---|---|---|")
    for f in MANUFACTURABLE:
        pf = report.per_family[f]
        L.append(f"| {f} | {pf['precision']:.3f} | {pf['recall']:.3f} | {pf['support']} |")
    L.append("")

    L.append("## Mis-route list (ranked by engine confidence — most-confident-wrong first)")
    L.append("")
    if not report.misroutes:
        L.append("_No mis-routes among scored parts._")
    else:
        L.append("| true | engine_best | engine_family | score | top-3 | dataset | part_id |")
        L.append("|---|---|---|---|---|---|---|")
        for r in report.misroutes[:50]:
            top3 = ", ".join(f"{p}:{s:.2f}" for p, s in r.top3)
            L.append(
                f"| {r.true_label} | {r.engine_best_process} | {r.engine_family} | "
                f"{r.engine_score:.2f} | {top3} | {r.dataset} | `{r.part_id[:12]}` |"
            )
    L.append("")

    L.append("## k-NN similarity example ('resembles these labeled parts')")
    L.append("")
    L.append(f"_Neighbour pool + feature provenance: {sim_note}_")
    L.append("")
    if not sim_example or not sim_example.get("neighbors"):
        L.append("_No neighbours available (empty label pool or feature store)._")
    else:
        L.append(f"Query part: `{sim_example['query']}`")
        L.append("")
        L.append("| rank | neighbor part_id | label | distance | shared descriptors | dataset |")
        L.append("|---|---|---|---|---|---|")
        for i, n in enumerate(sim_example["neighbors"], 1):
            L.append(
                f"| {i} | `{n['part_id'][:12]}` | {n['label']} | {n['distance']:.3f} | "
                f"{', '.join(n['shared'])} | {n['dataset']} |"
            )
    L.append("")

    L.append("## Regenerating real metrics once humans have labelled")
    L.append("")
    L.append("1. Label parts in the tool (writes `data/labels.jsonl`, append-only).")
    L.append(f"2. Once **>= {thr}** parts carry a manufacturable human label, run the real eval:")
    L.append("   ```")
    L.append("   cd backend")
    L.append("   python -m src.eval.run --build-features   # one-time; builds features.npz")
    L.append("   python -m src.eval.run                     # real, ungated metrics")
    L.append("   ```")
    L.append("3. The smoke seed never participates in a non-`--smoke` run.")
    L.append("")
    return "\n".join(L)


# ──────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────
def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = label_store.load_manifest()
    if not manifest:
        print("ERROR: corpus manifest is empty — build the corpus first.", file=sys.stderr)
        return 2

    # The human-label gate is always computed from REAL labels, never the seed.
    real_human = label_store.human_labels(labeler=args.labeler)
    n_human = label_store.count_manufacturable(real_human)
    gate_ok = n_human >= args.min_human_labels

    if args.smoke:
        build_smoke_seed()  # idempotent
        eval_labels = label_store.smoke_labels()
        if not eval_labels:
            print("ERROR: smoke seed is empty.", file=sys.stderr)
            return 2
        label_source = "SMOKE seed (data/labels.seed.jsonl)"
    else:
        eval_labels = real_human
        label_source = f"human labels (data/labels.jsonl, labeler={args.labeler or 'majority'})"

    print(f"[run] label source: {label_source}; parts={len(eval_labels)}")
    print(f"[run] human-label gate: {n_human}/{args.min_human_labels} "
          f"({'OK' if gate_ok else 'NOT MET — provisional only'})")
    if args.smoke:
        print(f"[run] {SMOKE_TAG}")

    # 1) Routing accuracy.
    report = evaluate(eval_labels, manifest=manifest)

    # 2) k-NN similarity demo against the same label pool.
    pool = eval_labels
    query_id = _pick_query(manifest, pool)
    sim_example: Optional[dict] = None
    sim_note = "n/a"
    if query_id and pool:
        must_cover = set(pool) | {query_id}
        store, prov = _ensure_store(manifest, must_cover, sample=args.sample)
        idx = store.index_of(query_id)
        if idx is not None:
            qvec = store.X[idx]
            neighbors = sim.knn(
                qvec, store, pool, k=args.k, manifest=manifest, exclude_part_id=query_id
            )
            qfn = manifest.get(query_id, {}).get("filename", query_id)
            sim_example = {
                "query": f"{query_id[:12]} ({qfn})",
                "neighbors": [
                    {
                        "part_id": n.part_id,
                        "label": n.label,
                        "distance": n.distance,
                        "dataset": n.dataset,
                        "shared": n.shared,
                    }
                    for n in neighbors
                ],
            }
            pool_kind = "SMOKE seed labels" if args.smoke else "human labels"
            sim_note = f"neighbour pool = {pool_kind}; vectors from {prov}"

    generated_at = datetime.now(timezone.utc).isoformat()

    # 3) Persist JSON + Markdown.
    payload = {
        "generated_at": generated_at,
        "mode": "smoke" if args.smoke else "real",
        "gate": {
            "human_labels_manufacturable": n_human,
            "threshold": args.min_human_labels,
            "gate_ok": gate_ok,
        },
        "label_source": label_source,
        "smoke_tag": SMOKE_TAG if args.smoke else None,
        "accuracy": report.to_dict(),
        "similarity_example": sim_example,
        "similarity_note": sim_note,
    }
    (out_dir / "c4-accuracy.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md = render_markdown(
        report,
        smoke=args.smoke,
        gate_ok=gate_ok,
        n_human=n_human,
        thr=args.min_human_labels,
        sim_example=sim_example,
        sim_note=sim_note,
        generated_at=generated_at,
    )
    (out_dir / "c4-accuracy.md").write_text(md, encoding="utf-8")

    # 4) Print to stdout (acceptance: confusion matrix + similarity example).
    print()
    print("=== CONFUSION MATRIX (rows=true label, cols=engine family) ===")
    print(render_confusion_text(report))
    print()
    if sim_example and sim_example["neighbors"]:
        print("=== k-NN SIMILARITY EXAMPLE ===")
        print(f"query: {sim_example['query']}")
        print(f"pool:  {sim_note}")
        for i, n in enumerate(sim_example["neighbors"], 1):
            print(f"  {i}. {n['part_id'][:12]}  label={n['label']:<16} "
                  f"d={n['distance']:.3f}  shared={', '.join(n['shared'])}")
    else:
        print("=== k-NN SIMILARITY EXAMPLE: (no neighbours — empty pool) ===")
    print()
    print(f"wrote {out_dir / 'c4-accuracy.json'}")
    print(f"wrote {out_dir / 'c4-accuracy.md'}")
    return 0


def build_features_cmd(args: argparse.Namespace) -> int:
    manifest = label_store.load_manifest()
    if not manifest:
        print("ERROR: corpus manifest is empty.", file=sys.stderr)
        return 2
    ids = list(manifest.keys())
    if args.limit:
        ids = ids[: args.limit]

    # Resume: reuse any rows already persisted (heavy build is killable/restartable).
    precomputed: dict = {}
    if Path(FEATURES_NPZ).exists():
        prev = sim.load_features()
        for k, pid in enumerate(prev.part_ids.tolist()):
            precomputed[pid] = prev.X[k]
        precomputed = {p: v for p, v in precomputed.items() if p in set(ids)}
        print(f"[build-features] resuming: {len(precomputed)} rows already persisted")

    todo = [p for p in ids if p not in precomputed]
    print(f"[build-features] {len(todo)} to compute / {len(ids)} total → {FEATURES_NPZ}")

    def _checkpoint(part_ids, rows):
        sim.save_features(sim._store_from_rows(list(part_ids), rows))
        print(f"[build-features] checkpoint: {len(part_ids)} rows persisted", file=sys.stderr)

    store = sim.build_feature_matrix(
        part_ids=ids, manifest=manifest, progress=True,
        precomputed=precomputed, on_checkpoint=_checkpoint, checkpoint_every=25,
    )
    sim.save_features(store)
    print(f"[build-features] DONE: wrote {FEATURES_NPZ} (X shape {store.X.shape})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="src.eval.run", description=__doc__)
    ap.add_argument("--smoke", action="store_true",
                    help="score the quarantined smoke seed (pipeline exercise only)")
    ap.add_argument("--labeler", default=None,
                    help="restrict to one labeler (default: majority across labelers)")
    ap.add_argument("--min-human-labels", type=int, default=MIN_HUMAN_LABELS,
                    help="gate threshold for emitting real metrics (default 30)")
    ap.add_argument("--k", type=int, default=8, help="k for the similarity example")
    ap.add_argument("--sample", type=int, default=80,
                    help="sample size for the on-the-fly feature matrix when features.npz is absent")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--build-features", action="store_true",
                    help="build/persist data/corpus/features.npz over the whole corpus and exit")
    ap.add_argument("--limit", type=int, default=None,
                    help="limit parts for --build-features (debugging)")
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.build_features:
        return build_features_cmd(args)
    return run(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
