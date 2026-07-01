"""Canonical local-corpus paths (Cycle 4, spec §2.1).

Define **once** and import everywhere. The data dir is gitignored (CAD-as-IP):
the corpus meshes and the human labels never leave the machine and are never
committed.

Layout::

    data/                              # gitignored
      corpus/
        meshes/<part_id>.stl           # part_id == sha256 of stored STL bytes
        manifest.jsonl                 # one JSON record per part (append-only)
        features.npz                   # similarity vectors (written by eval)
      labels.jsonl                     # human labels (append-only)
      labels.seed.jsonl                # TINY smoke seed (labeler == SMOKE_SEED)

Override the root with the ``CADVERIFY_DATA_DIR`` env var (default ``<repo>/data``).
"""

from __future__ import annotations

import os
from pathlib import Path

# <repo>/backend/src/corpus/paths.py -> parents: [corpus, src, backend, <repo>]
REPO_ROOT = Path(__file__).resolve().parents[3]


def _data_dir() -> Path:
    override = os.getenv("CADVERIFY_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return REPO_ROOT / "data"


DATA_DIR = _data_dir()
CORPUS_ROOT = DATA_DIR / "corpus"
MESH_DIR = CORPUS_ROOT / "meshes"
MANIFEST = CORPUS_ROOT / "manifest.jsonl"
FEATURES_NPZ = CORPUS_ROOT / "features.npz"

# Human label store + smoke seed. ``LABELS_PATH`` (and the ``LABELS`` alias the
# spec names) is the *file path* to labels.jsonl — NOT to be confused with the
# 6-key ontology list ``src.eval.ontology.LABELS``.
LABELS_PATH = DATA_DIR / "labels.jsonl"
LABELS = LABELS_PATH  # spec §2.1 alias
LABELS_SEED = DATA_DIR / "labels.seed.jsonl"


def ensure_dirs() -> None:
    """Create the corpus/mesh directories if they do not yet exist."""
    MESH_DIR.mkdir(parents=True, exist_ok=True)
