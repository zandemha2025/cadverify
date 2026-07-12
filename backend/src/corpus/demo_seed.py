"""Demo-fallback corpus seeding (Cycle 4, Tool builder).

If the real corpus (``data/corpus/manifest.jsonl``, owned by the Corpus builder)
is empty at build time, the labeling tool can seed a LOCAL corpus from an
operator-provided, license-documented directory so a reviewer can open /label,
see a real part in 3D, and persist a label.

Every accepted mesh must have a source URL and a concrete license in
``_manifest.csv``. Unknown/"see repo" licenses fail closed; the old private batch
is therefore never imported implicitly. Records use the canonical
``analyze_geometry`` pass and remain clearly marked as a demo fallback.

Idempotent: re-running skips parts whose sha256 is already in the manifest.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.corpus.paths import MANIFEST, MESH_DIR, REPO_ROOT, ensure_dirs
from src.corpus.provenance import has_complete_provenance

logger = logging.getLogger("cadverify.corpus.demo_seed")

DEFAULT_DEMO_PARTS_DIR = REPO_ROOT / "data" / "demo-parts"

_PRINTABLES_ID = re.compile(r"^(\d{4,})_")
_MAX_FACES = 2_000_000


def demo_parts_dir() -> Path:
    configured = os.getenv("CADVERIFY_DEMO_PARTS_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_DEMO_PARTS_DIR


def _load_provenance(parts_dir: Path) -> dict[str, dict]:
    """Map original filename -> {source, category} from _manifest.csv."""
    out: dict[str, dict] = {}
    csv_path = parts_dir / "_manifest.csv"
    if not csv_path.exists():
        return out
    try:
        with csv_path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                fn = (row.get("filename") or "").strip()
                if fn:
                    out[fn] = row
    except Exception as exc:  # pragma: no cover - best effort provenance
        logger.warning("demo_seed: failed reading _manifest.csv: %s", exc)
    return out


def _source_url(filename: str, source: str) -> str:
    """Best-effort real provenance URL for a fallback part."""
    m = _PRINTABLES_ID.match(filename)
    if m and "printables" in source.lower():
        return f"https://www.printables.com/model/{m.group(1)}"
    return ""


def _known_part_ids() -> set[str]:
    seen: set[str] = set()
    if MANIFEST.exists():
        with MANIFEST.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    seen.add(json.loads(line)["part_id"])
                except Exception:
                    continue
    return seen


def seed_demo_corpus(parts_dir: Optional[Path] = None) -> int:
    """Seed the local corpus from the repo demo parts. Returns parts added."""
    parts_dir = parts_dir or demo_parts_dir()
    if not parts_dir.exists():
        logger.warning("demo_seed: parts dir not found: %s", parts_dir)
        return 0

    ensure_dirs()
    provenance = _load_provenance(parts_dir)
    seen = _known_part_ids()
    added = 0

    stl_files = sorted(p for p in parts_dir.glob("*.stl") if p.is_file())
    with MANIFEST.open("a") as out:
        for stl in stl_files:
            row = provenance.get(stl.name, {})
            source = (row.get("source") or "").strip()
            source_url = (row.get("source_url") or "").strip() or _source_url(
                stl.name, source
            )
            license_name = (row.get("license") or "").strip()
            if not has_complete_provenance(source_url, license_name):
                logger.warning(
                    "demo_seed: skipping %s without HTTPS source_url + reviewed license",
                    stl.name,
                )
                continue
            try:
                raw = stl.read_bytes()
            except Exception as exc:
                logger.warning("demo_seed: cannot read %s: %s", stl.name, exc)
                continue
            part_id = hashlib.sha256(raw).hexdigest()
            if part_id in seen:
                continue  # dedup by content hash (§2.3)

            try:
                mesh = trimesh.load(str(stl), force="mesh")
            except Exception as exc:
                logger.warning("demo_seed: trimesh load failed %s: %s", stl.name, exc)
                continue
            if not hasattr(mesh, "faces") or len(mesh.faces) == 0:
                logger.warning("demo_seed: skipping zero-face mesh %s", stl.name)
                continue
            if len(mesh.faces) > _MAX_FACES:
                logger.warning("demo_seed: skipping oversized mesh %s (%d faces)", stl.name, len(mesh.faces))
                continue

            geo = analyze_geometry(mesh)
            dest = MESH_DIR / f"{part_id}.stl"
            if not dest.exists():
                shutil.copyfile(stl, dest)

            record = {
                "part_id": part_id,
                "filename": stl.name,
                "rel_path": f"meshes/{part_id}.stl",
                "source_url": source_url,
                "dataset": source,
                "license": license_name,
                "original_format": "stl",
                "downloaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "n_faces": int(geo.face_count),
                "volume_cm3": round(geo.volume / 1000.0, 3),
                "bbox_mm": [round(d, 1) for d in geo.bounding_box.dimensions],
                "watertight": bool(geo.is_watertight),
                "demo_fallback": True,  # honesty flag: NOT the audited gathered corpus
            }
            out.write(json.dumps(record) + "\n")
            out.flush()
            seen.add(part_id)
            added += 1

    logger.info("demo_seed: added %d demo-fallback parts to %s", added, MANIFEST)
    return added


def ensure_corpus_available() -> int:
    """Ensure at least a demo corpus exists. Returns total manifest parts.

    No-op when the manifest already has parts (real or previously seeded).
    """
    existing = _known_part_ids()
    if existing:
        return len(existing)
    seed_demo_corpus()
    return len(_known_part_ids())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = ensure_corpus_available()
    print(f"corpus parts available: {n}")
