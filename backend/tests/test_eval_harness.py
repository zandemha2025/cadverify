"""Tests for the Cycle 4 EVAL + SIMILARITY harness (spec §6).

These exercise the harness on *procedural* meshes and a *temporary* corpus so
nothing depends on the (gitignored) local corpus. They prove:

* the ontology maps every ProcessType and round-trips the 6 keys,
* the canonical engine wrapper sets best_process with the score>0 rule,
* the 18-dim feature vector is finite and shaped, and k-NN ranks by L2,
* routing accuracy builds a correct confusion matrix + precision/recall,
* label resolution is last-write-wins and quarantines the smoke seed,
* the gate withholds real metrics until >=30 human labels,
* the full --smoke run writes outputs and never leaks the seed into real metrics.
"""

from __future__ import annotations

import io
import json

import numpy as np
import pytest
import trimesh

from src.analysis.models import ProcessType
from src.eval import labels as label_store
from src.eval import similarity as sim
from src.eval.engine import geometry_pass, route_mesh
from src.eval.ontology import FAMILY_OF, LABELS, MANUFACTURABLE, NO_ROUTE, family_of
from src.eval.routing_accuracy import evaluate


# ──────────────────────────────────────────────────────────────
# Fixtures: a tiny on-disk corpus in a tmp dir
# ──────────────────────────────────────────────────────────────
def _stl_bytes(mesh: trimesh.Trimesh) -> bytes:
    buf = io.BytesIO()
    mesh.export(buf, file_type="stl")
    return buf.getvalue()


@pytest.fixture
def tmp_corpus(tmp_path, monkeypatch):
    """Build a 4-part temp corpus + manifest and repoint all path constants."""
    import hashlib

    data_dir = tmp_path / "data"
    corpus_root = data_dir / "corpus"
    mesh_dir = corpus_root / "meshes"
    mesh_dir.mkdir(parents=True)
    manifest_path = corpus_root / "manifest.jsonl"
    labels_path = data_dir / "labels.jsonl"
    seed_path = data_dir / "labels.seed.jsonl"
    features_npz = corpus_root / "features.npz"

    meshes = {
        "box": trimesh.creation.box(extents=[20.0, 20.0, 20.0]),
        "plate": trimesh.creation.box(extents=[40.0, 40.0, 2.0]),
        "cyl": trimesh.creation.cylinder(radius=8.0, height=40.0, sections=48),
        "long": trimesh.creation.box(extents=[80.0, 10.0, 10.0]),
    }
    part_ids: dict[str, str] = {}
    with open(manifest_path, "w") as fh:
        for name, mesh in meshes.items():
            raw = _stl_bytes(mesh)
            pid = hashlib.sha256(raw).hexdigest()
            part_ids[name] = pid
            (mesh_dir / f"{pid}.stl").write_bytes(raw)
            fh.write(json.dumps({
                "part_id": pid,
                "filename": f"{name}.stl",
                "rel_path": f"meshes/{pid}.stl",
                "dataset": "unit-test",
                "license": "CC0",
                "n_faces": len(mesh.faces),
                "watertight": bool(mesh.is_watertight),
            }) + "\n")

    # Repoint every path constant the harness imports.
    import src.corpus.paths as paths
    for mod in (paths, label_store, sim):
        pass
    monkeypatch.setattr(paths, "CORPUS_ROOT", corpus_root, raising=False)
    monkeypatch.setattr(paths, "MESH_DIR", mesh_dir, raising=False)
    monkeypatch.setattr(paths, "MANIFEST", manifest_path, raising=False)
    monkeypatch.setattr(paths, "FEATURES_NPZ", features_npz, raising=False)
    monkeypatch.setattr(paths, "LABELS_PATH", labels_path, raising=False)
    monkeypatch.setattr(paths, "LABELS_SEED", seed_path, raising=False)
    # label_store imported the names directly — patch its references too.
    monkeypatch.setattr(label_store, "MANIFEST", manifest_path, raising=False)
    monkeypatch.setattr(label_store, "MESH_DIR", mesh_dir, raising=False)
    monkeypatch.setattr(label_store, "LABELS_PATH", labels_path, raising=False)
    monkeypatch.setattr(label_store, "LABELS_SEED", seed_path, raising=False)
    monkeypatch.setattr(sim, "FEATURES_NPZ", features_npz, raising=False)

    return {
        "data_dir": data_dir,
        "corpus_root": corpus_root,
        "mesh_dir": mesh_dir,
        "manifest": manifest_path,
        "labels": labels_path,
        "seed": seed_path,
        "features_npz": features_npz,
        "part_ids": part_ids,
        "meshes": meshes,
    }


# ──────────────────────────────────────────────────────────────
# Ontology
# ──────────────────────────────────────────────────────────────
def test_ontology_maps_every_process_type():
    assert set(FAMILY_OF.keys()) == set(ProcessType)
    assert set(FAMILY_OF.values()) <= set(MANUFACTURABLE)


def test_ontology_keys_and_sentinel():
    assert LABELS == [
        "additive", "subtractive", "injection_molding",
        "sheet_metal", "casting", "unsure_other",
    ]
    assert MANUFACTURABLE == LABELS[:5]
    assert family_of(None) == NO_ROUTE
    assert family_of(ProcessType.CNC_3AXIS) == "subtractive"
    assert family_of(ProcessType.SHEET_METAL) == "sheet_metal"
    assert family_of(ProcessType.DIE_CASTING) == "injection_molding"


# ──────────────────────────────────────────────────────────────
# Engine wrapper
# ──────────────────────────────────────────────────────────────
def test_route_mesh_sets_best_process_with_score_rule(cube_10mm):
    routing = route_mesh(cube_10mm, filename="cube.stl")
    # rank_processes only sorts; the wrapper must set best_process itself.
    assert routing.result.best_process == routing.best_process
    if routing.ranked and routing.ranked[0].score > 0:
        assert routing.best_process is not None
        assert routing.engine_family in MANUFACTURABLE
    else:
        assert routing.best_process is None
        assert routing.engine_family == NO_ROUTE
    assert len(routing.top3) <= 3


def test_geometry_pass_attaches_features(cube_10mm):
    gp = geometry_pass(cube_10mm)
    assert gp.ctx.features is gp.features
    assert gp.geometry.face_count == len(cube_10mm.faces)


# ──────────────────────────────────────────────────────────────
# Feature vector + k-NN
# ──────────────────────────────────────────────────────────────
def test_feature_vector_shape_and_finite(cube_10mm):
    gp = geometry_pass(cube_10mm)
    v = sim.feature_vector(gp.mesh, gp.geometry, gp.ctx)
    assert v.shape == (sim.N_DIMS,)
    assert v.shape == (18,)
    assert np.all(np.isfinite(v))
    # watertight cube -> watertight flag set, solidity near 1.
    assert v[8] == 1.0
    assert 0.0 <= v[3] <= 1.0


def test_feature_vector_handles_degenerate_mesh():
    # Single degenerate triangle: must not raise, must be finite.
    m = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]])
    gp = geometry_pass(m)
    v = sim.feature_vector(gp.mesh, gp.geometry, gp.ctx)
    assert np.all(np.isfinite(v))


def test_build_matrix_and_knn_ranks_by_l2(tmp_corpus):
    manifest = label_store.load_manifest()
    store = sim.build_feature_matrix(manifest=manifest)
    assert store.X.shape == (4, 18)
    sim.save_features(store)
    reloaded = sim.load_features()
    assert np.allclose(reloaded.X, store.X)

    # Query the box against a labeled pool; nearest must be the box itself
    # (distance 0) when it is in the pool and not excluded.
    pid_box = tmp_corpus["part_ids"]["box"]
    pid_plate = tmp_corpus["part_ids"]["plate"]
    pid_cyl = tmp_corpus["part_ids"]["cyl"]
    pool = {pid_box: "subtractive", pid_plate: "sheet_metal", pid_cyl: "additive"}
    qidx = store.index_of(pid_box)
    neighbors = sim.knn(store.X[qidx], store, pool, k=3, manifest=manifest)
    assert neighbors[0].part_id == pid_box
    assert neighbors[0].distance == pytest.approx(0.0, abs=1e-9)
    # distances sorted ascending
    dists = [n.distance for n in neighbors]
    assert dists == sorted(dists)
    # shared descriptors present and valid dim names
    assert all(s in sim.DIMS for n in neighbors for s in n.shared)


def test_knn_excludes_query_and_filters_to_pool(tmp_corpus):
    manifest = label_store.load_manifest()
    store = sim.build_feature_matrix(manifest=manifest)
    pid_box = tmp_corpus["part_ids"]["box"]
    pid_cyl = tmp_corpus["part_ids"]["cyl"]
    pool = {pid_box: "subtractive", pid_cyl: "additive"}
    neighbors = sim.knn(store.X[store.index_of(pid_box)], store, pool, k=5,
                        manifest=manifest, exclude_part_id=pid_box)
    ids = {n.part_id for n in neighbors}
    assert pid_box not in ids           # excluded query
    assert ids <= set(pool)             # only labeled pool members


# ──────────────────────────────────────────────────────────────
# Label resolution + gate
# ──────────────────────────────────────────────────────────────
def test_label_resolution_last_write_wins_and_quarantines_seed(tmp_corpus):
    pids = tmp_corpus["part_ids"]
    with open(tmp_corpus["labels"], "w") as fh:
        fh.write(json.dumps({"part_id": pids["box"], "label": "additive", "labeler": "a"}) + "\n")
        fh.write(json.dumps({"part_id": pids["box"], "label": "subtractive", "labeler": "a"}) + "\n")
        fh.write(json.dumps({"part_id": pids["cyl"], "label": "casting", "labeler": "b"}) + "\n")
    with open(tmp_corpus["seed"], "w") as fh:
        fh.write(json.dumps({"part_id": pids["plate"], "label": "sheet_metal",
                             "labeler": "SMOKE_SEED"}) + "\n")

    human = label_store.human_labels()
    # last write wins for (box, a)
    assert human[pids["box"]] == "subtractive"
    assert human[pids["cyl"]] == "casting"
    # smoke seed never appears among human labels
    assert pids["plate"] not in human
    # but is loadable separately
    assert label_store.smoke_labels()[pids["plate"]] == "sheet_metal"


def test_count_manufacturable_excludes_unsure(tmp_corpus):
    labels = {"p1": "additive", "p2": "unsure_other", "p3": "casting"}
    assert label_store.count_manufacturable(labels) == 2


# ──────────────────────────────────────────────────────────────
# Routing accuracy / confusion matrix
# ──────────────────────────────────────────────────────────────
def test_evaluate_builds_confusion_and_precision_recall(tmp_corpus):
    manifest = label_store.load_manifest()
    pids = tmp_corpus["part_ids"]
    # Hand the evaluator real meshes with arbitrary labels; we assert structure,
    # not that the engine is "right" (it is unvalidated — that's the whole point).
    labels = {
        pids["box"]: "subtractive",
        pids["plate"]: "sheet_metal",
        pids["cyl"]: "additive",
        pids["long"]: "unsure_other",  # must be skipped (not manufacturable)
    }
    report = evaluate(labels, manifest=manifest)
    assert report.n_labeled == 3           # the unsure_other part is skipped
    assert any(s["reason"].startswith("label") for s in report.skipped)
    # confusion rows/cols well-formed
    assert set(report.confusion.keys()) == set(MANUFACTURABLE)
    for row in report.confusion.values():
        assert set(row.keys()) == set(MANUFACTURABLE + [NO_ROUTE])
    # every scored part lands in exactly one confusion cell
    assert sum(sum(r.values()) for r in report.confusion.values()) == 3
    # precision/recall computed for all 5 families
    assert set(report.per_family.keys()) == set(MANUFACTURABLE)
    # top-1 accuracy = correct / scored
    assert report.top1_accuracy == report.n_correct / report.n_labeled


def test_misroutes_ranked_by_confidence(tmp_corpus):
    manifest = label_store.load_manifest()
    pids = tmp_corpus["part_ids"]
    # Force mis-routes by labeling everything injection_molding (engine won't agree on all).
    labels = {pid: "injection_molding" for pid in pids.values()}
    report = evaluate(labels, manifest=manifest)
    scores = [r.engine_score for r in report.misroutes]
    assert scores == sorted(scores, reverse=True)
    for r in report.misroutes:
        assert r.engine_family != "injection_molding"


# ──────────────────────────────────────────────────────────────
# run.py orchestration (gate + smoke quarantine + output files)
# ──────────────────────────────────────────────────────────────
@pytest.fixture
def run_corpus(tmp_corpus, monkeypatch):
    """Extend tmp_corpus so run.py/seed.py resolve the temp paths too."""
    from src.eval import run as run_mod
    from src.eval import seed as seed_mod

    monkeypatch.setattr(run_mod, "FEATURES_NPZ", tmp_corpus["features_npz"], raising=False)
    monkeypatch.setattr(seed_mod, "LABELS_SEED", tmp_corpus["seed"], raising=False)
    return tmp_corpus


def test_run_smoke_writes_outputs_and_flags_gate(run_corpus, tmp_path):
    from src.eval import run as run_mod

    out_dir = tmp_path / "out"
    rc = run_mod.main(["--smoke", "--out-dir", str(out_dir), "--sample", "4", "--k", "3"])
    assert rc == 0
    payload = json.loads((out_dir / "c4-accuracy.json").read_text())
    assert payload["mode"] == "smoke"
    assert payload["gate"]["gate_ok"] is False          # 0 human labels
    assert payload["gate"]["human_labels_manufacturable"] == 0
    md = (out_dir / "c4-accuracy.md").read_text()
    assert "SMOKE" in md
    assert "INSUFFICIENT HUMAN LABELS" in md
    # smoke seed file was created and quarantined out of human labels
    assert label_store.smoke_labels()
    assert label_store.human_labels() == {}


def test_run_real_mode_passes_gate_and_runs_similarity(run_corpus, tmp_path):
    from src.eval import run as run_mod

    pids = run_corpus["part_ids"]
    # 3 human labels; leave 'long' unlabeled so it can be the similarity query.
    with open(run_corpus["labels"], "w") as fh:
        fh.write(json.dumps({"part_id": pids["box"], "label": "subtractive", "labeler": "x"}) + "\n")
        fh.write(json.dumps({"part_id": pids["plate"], "label": "sheet_metal", "labeler": "x"}) + "\n")
        fh.write(json.dumps({"part_id": pids["cyl"], "label": "additive", "labeler": "x"}) + "\n")

    out_dir = tmp_path / "out"
    rc = run_mod.main(["--out-dir", str(out_dir), "--min-human-labels", "2",
                       "--sample", "4", "--k", "3"])
    assert rc == 0
    payload = json.loads((out_dir / "c4-accuracy.json").read_text())
    assert payload["mode"] == "real"
    assert payload["gate"]["gate_ok"] is True
    assert payload["gate"]["human_labels_manufacturable"] == 3
    # similarity example must be present and drawn from the labeled pool
    ex = payload["similarity_example"]
    assert ex is not None and ex["neighbors"]
    assert {n["part_id"] for n in ex["neighbors"]} <= set(pids.values())
    md = (out_dir / "c4-accuracy.md").read_text()
    assert "INSUFFICIENT HUMAN LABELS" not in md      # gate met -> no banner


def test_smoke_seed_is_one_part_per_key_in_real_corpus():
    """On the REAL corpus the seed has distinct parts (skip if corpus absent)."""
    manifest = label_store.load_manifest()
    if not manifest:
        pytest.skip("real corpus manifest not present")
    from src.eval.seed import select_smoke_parts

    chosen = select_smoke_parts(manifest)
    assert len(set(chosen.values())) == len(chosen)   # all distinct parts
    assert set(chosen.keys()) <= set(LABELS)
