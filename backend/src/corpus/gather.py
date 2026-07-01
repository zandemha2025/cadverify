"""Cycle 4 corpus gatherer (spec §2).

Downloads a diverse, REAL, openly-licensed CAD/mesh corpus from reachable sources,
normalizes everything to binary STL, dedups by sha256, computes the geometry summary
via the canonical ``analyze_geometry`` pass, and writes ``data/corpus/manifest.jsonl``.

Sources (spec §2.5):
  1. Thingi10K  (HF dataset ``Thingi10K/Thingi10K``) — bulk, per-file license. PRIMARY.
  2. Existing 107 repo parts (Printables / GitHub / Thangs ...) — additive-biased sample.
  3. Permissive GitHub open-hardware repos — mechanical geometry diversity.
  (4. ABC CAD dataset — gated/login on probed mirrors -> logged BLOCKED, skipped.)

HARD RULES: real downloads only; never fabricate geometry; record source_url + license
for every part; NO auto-LABELING (a tagged ``process_family_guess`` is allowed, never a
label). STEP sources are skipped (no local tessellation — cadquery not installed).

Run from ``backend/``::

    python -m src.corpus.gather                 # full gather
    python -m src.corpus.gather --thingi 420 --github 1 --existing 1
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import requests
import trimesh

from src.analysis.base_analyzer import analyze_geometry, detect_units
from src.corpus.guess import process_family_guess
from src.corpus.paths import MANIFEST, MESH_DIR, ensure_dirs

logger = logging.getLogger("cadverify.corpus.gather")

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
HF_DS = "Thingi10K/Thingi10K"
HF_META = f"https://huggingface.co/datasets/{HF_DS}/resolve/main/metadata"
HF_RAW = f"https://huggingface.co/datasets/{HF_DS}/resolve/main/raw_meshes"

# scratchpad cache for the (large) Thingi10K metadata CSVs
CACHE_DIR = Path(
    "/private/tmp/claude-501/-Users-nazeem-Desktop-developer-cadverify/"
    "3182c9c6-e59b-4394-a584-d9c4cd4ce0dc/scratchpad/corpus_cache"
)
EXISTING_PARTS_DIR = Path(
    "/private/tmp/claude-501/-Users-nazeem-Desktop-developer-cadverify/"
    "3182c9c6-e59b-4394-a584-d9c4cd4ce0dc/scratchpad/parts"
)

# Openly-licensed Thingi10K licenses we accept (exclude Non-Commercial / No-Derivatives
# to keep the corpus cleanly redistributable). Maps the verbose CSV string -> short code.
THINGI_LICENSE_OK = {
    "Creative Commons - Attribution": "CC-BY",
    "Creative Commons - Attribution - Share Alike": "CC-BY-SA",
    "Creative Commons - Public Domain Dedication": "CC0-1.0",
    "Public Domain": "Public-Domain",
    "BSD License": "BSD",
    "GNU - GPL": "GPL",
    "GNU - LGPL": "LGPL",
}

# Face-count buckets (lo, hi] for size stratification (spec §2.6).
FACE_BUCKETS = [
    (50, 1_000),
    (1_000, 5_000),
    (5_000, 20_000),
    (20_000, 100_000),
    (100_000, 400_000),
]
MAX_FACES = 400_000   # keep the viewer responsive; skip + log anything larger
MIN_FACES = 12

# Permissive GitHub open-hardware repos (mechanical geometry diversity, clear LICENSE).
GITHUB_REPOS = [
    # repo, ref (branch/tag), max files to pull
    ("prusa3d/Original-Prusa-i3", "MK3", 30),
    ("BCN3D/BCN3D-Moveo", "master", 32),
    ("AngelLM/Thor", "main", 40),
]

LOG_PATH = Path(
    "/Users/nazeem/Desktop/developer/cadverify/outputs/c4-corpus-log.md"
)

_HEADERS = {"User-Agent": "cadverify-corpus-gatherer/1.0 (research; local corpus)"}


# ──────────────────────────────────────────────────────────────────────────────
# Logging to the gatherer log file (honesty trail)
# ──────────────────────────────────────────────────────────────────────────────
_LOG_LINES: list[str] = []


def glog(msg: str) -> None:
    logger.info(msg)
    _LOG_LINES.append(msg)


def flush_log(header: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with LOG_PATH.open("a") as fh:
        fh.write(f"\n## {header} — {ts}\n\n")
        for line in _LOG_LINES:
            fh.write(f"- {line}\n")
    _LOG_LINES.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Manifest / dedup state
# ──────────────────────────────────────────────────────────────────────────────
def load_seen() -> tuple[set[str], set[tuple]]:
    """Return (seen part_ids, seen (round(vol,1), n_faces) near-dup keys)."""
    seen_ids: set[str] = set()
    near: set[tuple] = set()
    if MANIFEST.exists():
        with MANIFEST.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                seen_ids.add(rec["part_id"])
                near.add((round(float(rec.get("volume_cm3", 0.0)), 1),
                          int(rec.get("n_faces", 0))))
    return seen_ids, near


# ──────────────────────────────────────────────────────────────────────────────
# Normalize-to-STL (spec §2.4)
# ──────────────────────────────────────────────────────────────────────────────
def normalize_to_stl(raw: bytes, fmt: str) -> Optional[bytes]:
    """Return binary-STL bytes for a downloaded mesh, or None if unusable.

    .stl -> kept as-is. Other mesh formats -> loaded via trimesh and re-exported.
    .step/.stp -> caller must skip (no local tessellation).
    """
    fmt = fmt.lower().lstrip(".")
    if fmt == "stl":
        return raw
    if fmt in ("obj", "ply", "off", "glb", "gltf"):
        try:
            loaded = trimesh.load(io.BytesIO(raw), file_type=fmt, force="mesh")
            if isinstance(loaded, trimesh.Scene):
                loaded = trimesh.util.concatenate(loaded.dump())
            if loaded is None or len(loaded.faces) == 0:
                return None
            return loaded.export(file_type="stl")
        except Exception as exc:  # pragma: no cover - source-dependent
            glog(f"normalize: trimesh failed on {fmt} ({exc}); skipped")
            return None
    return None  # unknown / unsupported


# ──────────────────────────────────────────────────────────────────────────────
# Core ingestion
# ──────────────────────────────────────────────────────────────────────────────
def add_part(
    raw: bytes,
    original_format: str,
    filename: str,
    source_url: str,
    dataset: str,
    license: str,
    out_fh,
    seen_ids: set[str],
    near: set[tuple],
    extra: Optional[dict] = None,
    near_dup_guard: bool = True,
) -> Optional[str]:
    """Normalize -> hash -> dedup -> geometry summary -> store STL + manifest line.

    Returns the part_id on success, else None (dropped / duplicate).
    """
    stl_bytes = normalize_to_stl(raw, original_format)
    if stl_bytes is None:
        return None

    part_id = hashlib.sha256(stl_bytes).hexdigest()
    if part_id in seen_ids:
        return None  # exact dup (spec §2.3 primary)

    # Load the normalized bytes for geometry (so the summary matches stored file).
    try:
        mesh = trimesh.load(io.BytesIO(stl_bytes), file_type="stl", force="mesh")
    except Exception as exc:
        glog(f"drop: trimesh load failed for {filename} ({exc})")
        return None
    if not hasattr(mesh, "faces") or len(mesh.faces) == 0:
        glog(f"drop: zero-face mesh {filename}")
        return None
    if len(mesh.faces) > MAX_FACES:
        glog(f"drop: oversized mesh {filename} ({len(mesh.faces)} faces > {MAX_FACES})")
        return None

    geo = analyze_geometry(mesh)
    vol_cm3 = round(geo.volume / 1000.0, 3)
    n_faces = int(geo.face_count)

    if near_dup_guard:
        key = (round(vol_cm3, 1), n_faces)
        if key in near:
            glog(f"near-dup skip: {filename} matches (vol={key[0]}, faces={key[1]})")
            return None

    units = detect_units(mesh)
    if units != "mm":
        glog(f"units note: {filename} detect_units={units} (NOT rescaled; bbox in source units)")

    dest = MESH_DIR / f"{part_id}.stl"
    if not dest.exists():
        dest.write_bytes(stl_bytes)

    record = {
        "part_id": part_id,
        "filename": filename,
        "rel_path": f"meshes/{part_id}.stl",
        "source_url": source_url,
        "dataset": dataset,
        "license": license,
        "original_format": original_format.lower().lstrip("."),
        "downloaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_faces": n_faces,
        "volume_cm3": vol_cm3,
        "bbox_mm": [round(d, 1) for d in geo.bounding_box.dimensions],
        "watertight": bool(geo.is_watertight),
    }
    guess = process_family_guess(mesh, geo)
    if guess is not None:
        record["process_family_guess"] = guess
    if extra:
        record.update(extra)

    out_fh.write(json.dumps(record) + "\n")
    out_fh.flush()
    seen_ids.add(part_id)
    near.add((round(vol_cm3, 1), n_faces))
    return part_id


# ──────────────────────────────────────────────────────────────────────────────
# Source 1: Thingi10K
# ──────────────────────────────────────────────────────────────────────────────
def _cached_csv(name: str) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / name
    if p.exists() and p.stat().st_size > 0:
        return p.read_text()
    url = f"{HF_META}/{name}"
    glog(f"thingi10k: fetching metadata {name}")
    r = requests.get(url, headers=_HEADERS, timeout=90)
    r.raise_for_status()
    p.write_text(r.text)
    return r.text


def thingi10k_candidates() -> list[dict]:
    """Build the stratified candidate list: file_id, license(short), n_faces, category."""
    inp = list(csv.DictReader(io.StringIO(_cached_csv("input_summary.csv"))))
    geo = {row["file_id"]: row for row in
           csv.DictReader(io.StringIO(_cached_csv("geometry_data.csv")))}
    ctx_rows = list(csv.DictReader(io.StringIO(_cached_csv("contextual_data.csv"))))
    cat_by_thing = {r["Thing ID"]: (r.get("Category") or "None") for r in ctx_rows}

    cands: list[dict] = []
    for row in inp:
        fid = row["ID"]
        lic = THINGI_LICENSE_OK.get(row["License"].strip())
        if lic is None:
            continue  # NC/ND/unknown -> excluded
        g = geo.get(fid)
        if not g:
            continue
        try:
            nf = int(g["num_faces"])
        except Exception:
            continue
        if nf < MIN_FACES or nf > MAX_FACES:
            continue
        cands.append({
            "file_id": fid,
            "license": lic,
            "n_faces": nf,
            "category": cat_by_thing.get(row.get("Thing ID", ""), "None"),
        })
    return cands


def select_stratified(cands: list[dict], target: int) -> list[dict]:
    """Pick ~target candidates evenly across face-count buckets, spreading categories.

    Deterministic: orders each bucket by sha1(file_id) and round-robins categories.
    """
    # bucket -> list
    buckets: dict[int, list[dict]] = {i: [] for i in range(len(FACE_BUCKETS))}
    for c in cands:
        for i, (lo, hi) in enumerate(FACE_BUCKETS):
            if lo < c["n_faces"] <= hi:
                buckets[i].append(c)
                break

    def order_key(c: dict) -> str:
        return hashlib.sha1(c["file_id"].encode()).hexdigest()

    per_bucket = max(1, target // len(FACE_BUCKETS))
    chosen: list[dict] = []
    for i in range(len(FACE_BUCKETS)):
        bl = buckets[i]
        # spread categories: sort by (category, deterministic hash) then interleave
        by_cat: dict[str, list[dict]] = {}
        for c in sorted(bl, key=order_key):
            by_cat.setdefault(c["category"], []).append(c)
        cat_queues = list(by_cat.values())
        picked: list[dict] = []
        idx = 0
        while len(picked) < per_bucket and any(cat_queues):
            q = cat_queues[idx % len(cat_queues)]
            if q:
                picked.append(q.pop(0))
            else:
                cat_queues = [x for x in cat_queues if x]
                if not cat_queues:
                    break
            idx += 1
        chosen.extend(picked)
    return chosen


def fetch_thingi10k(target: int, out_fh, seen_ids, near, sleep: float = 0.05) -> int:
    cands = thingi10k_candidates()
    glog(f"thingi10k: {len(cands)} openly-licensed candidates after filtering")
    picks = select_stratified(cands, target)
    glog(f"thingi10k: selected {len(picks)} stratified across face buckets")
    added = 0
    for i, c in enumerate(picks):
        fid = c["file_id"]
        url = f"{HF_RAW}/{fid}.stl"
        try:
            r = requests.get(url, headers=_HEADERS, timeout=60)
            if r.status_code != 200:
                glog(f"thingi10k: HTTP {r.status_code} for {fid}.stl — skipped")
                continue
            pid = add_part(
                raw=r.content, original_format="stl",
                filename=f"{fid}.stl", source_url=url,
                dataset="Thingi10K", license=c["license"], out_fh=out_fh,
                seen_ids=seen_ids, near=near,
                extra={"thingi_category": c["category"]},
            )
            if pid:
                added += 1
        except Exception as exc:
            glog(f"thingi10k: error on {fid} ({exc}) — skipped")
        if sleep:
            time.sleep(sleep)
        if (i + 1) % 50 == 0:
            glog(f"thingi10k: progress {i+1}/{len(picks)}, added={added}")
    glog(f"thingi10k: DONE added {added}")
    return added


# ──────────────────────────────────────────────────────────────────────────────
# Source 2: existing 107 repo parts
# ──────────────────────────────────────────────────────────────────────────────
import re as _re

_PRINTABLES_ID = _re.compile(r"^(\d{4,})_")
# Existing-parts filenames embed the Printables model id under a few prefixes:
#   122552_..  /  printables_122552_..  /  r3_211682_..
_PRINTABLES_PREFIXED = _re.compile(r"^(?:printables|r3)_(\d+)_")

# repo-name fragments -> (github url, license) for the existing parts' GitHub sources
_EXISTING_REPO_LICENSE = {
    "macchina": ("https://github.com/macchina/m2-enclosures", "see-repo"),
    "mazduino": ("https://github.com/amrikarisma/Mazduino", "see-repo"),
    "me7.5duino": ("https://github.com/PyroMix62/ME7.5Duino", "see-repo"),
    "motoboard": ("https://github.com/leech001/MotoBoard", "see-repo"),
    "ecu_stm": ("https://github.com/mstevanin4/ECU_STM_V1", "see-repo"),
    "e12_can": ("https://github.com/pazi88/E12_CAN_gauges", "see-repo"),
    "speeduino": ("https://github.com/speeduino/Hardware", "see-repo"),
    "rusefi": ("https://github.com/rusefi/rusefi", "see-repo"),
}


def _existing_source_url(filename: str, source: str) -> str:
    s = source.lower()
    m = _PRINTABLES_PREFIXED.match(filename) or _PRINTABLES_ID.match(filename)
    if m and "printables" in s:
        return f"https://www.printables.com/model/{m.group(1)}"
    for frag, (url, _lic) in _EXISTING_REPO_LICENSE.items():
        if frag in filename.lower() or frag in s:
            return url
    if "thangs" in s:
        return "https://thangs.com"
    if "bimmerpost" in s:
        return "https://www.bimmerpost.com"
    if "gitlab" in s:
        return "https://gitlab.com/CiscoDerm/ESP32-OBD2-Gauge"
    if "projectzero" in s or "google drive" in s:
        return "https://projectzero.build"
    return ""


def _existing_license(filename: str, source: str) -> str:
    s = source.lower()
    if "github" in s or "gitlab" in s:
        return "UNKNOWN (open-hardware repo — see source_url)"
    if "printables" in s or "thangs" in s or "bimmerpost" in s or "drive" in s:
        return "UNKNOWN (consumer-site per-model — see source_url)"
    return "UNKNOWN"


def ingest_existing(out_fh, seen_ids, near, limit: Optional[int] = None) -> int:
    if not EXISTING_PARTS_DIR.exists():
        glog(f"existing-parts: dir not found {EXISTING_PARTS_DIR} — skipped")
        return 0
    prov: dict[str, dict] = {}
    csv_path = EXISTING_PARTS_DIR / "_manifest.csv"
    if csv_path.exists():
        with csv_path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                fn = (row.get("filename") or "").strip()
                if fn:
                    prov[fn] = row
    added = 0
    stls = sorted(p for p in EXISTING_PARTS_DIR.glob("*.stl") if p.is_file())
    stls += sorted(p for p in EXISTING_PARTS_DIR.glob("*.STL") if p.is_file())
    for stl in stls:
        if limit and added >= limit:
            break
        try:
            raw = stl.read_bytes()
        except Exception as exc:
            glog(f"existing-parts: read failed {stl.name} ({exc})")
            continue
        row = prov.get(stl.name, {})
        source = (row.get("source") or "Local repo parts").strip()
        url = _existing_source_url(stl.name, source)
        lic = _existing_license(stl.name, source)
        pid = add_part(
            raw=raw, original_format="stl", filename=stl.name,
            source_url=url, dataset=f"repo-parts:{source}", license=lic,
            out_fh=out_fh, seen_ids=seen_ids, near=near,
            extra={"category": row.get("category", ""), "additive_biased_sample": True},
        )
        if pid:
            added += 1
    glog(f"existing-parts: added {added}")
    return added


# ──────────────────────────────────────────────────────────────────────────────
# Source 3: permissive GitHub repos
# ──────────────────────────────────────────────────────────────────────────────
def _gh_license(repo: str) -> str:
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/license",
                         headers=_HEADERS, timeout=20)
        if r.status_code == 200:
            return r.json().get("license", {}).get("spdx_id") or "UNKNOWN"
    except Exception:
        pass
    return "UNKNOWN"


def fetch_github(out_fh, seen_ids, near, sleep: float = 0.1) -> int:
    added = 0
    for repo, ref, cap in GITHUB_REPOS:
        lic = _gh_license(repo)
        try:
            tree = requests.get(
                f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1",
                headers=_HEADERS, timeout=30,
            )
            if tree.status_code != 200:
                glog(f"github {repo}@{ref}: tree HTTP {tree.status_code} — skipped")
                continue
            entries = tree.json().get("tree", [])
        except Exception as exc:
            glog(f"github {repo}: tree error ({exc}) — skipped")
            continue
        mesh_files = [e["path"] for e in entries
                      if e.get("type") == "blob"
                      and e["path"].lower().endswith((".stl", ".obj", ".ply", ".off"))]
        glog(f"github {repo}@{ref}: {len(mesh_files)} mesh files, license={lic}")
        repo_added = 0
        for path in mesh_files:
            if repo_added >= cap:
                break
            raw_url = f"https://raw.githubusercontent.com/{repo}/{ref}/" + \
                      requests.utils.quote(path)
            try:
                r = requests.get(raw_url, headers=_HEADERS, timeout=60)
                if r.status_code != 200:
                    glog(f"github {repo}: HTTP {r.status_code} for {path}")
                    continue
                fmt = path.rsplit(".", 1)[-1]
                pid = add_part(
                    raw=r.content, original_format=fmt,
                    filename=path.split("/")[-1],
                    source_url=f"https://github.com/{repo}/blob/{ref}/{path}",
                    dataset=f"github:{repo}", license=lic, out_fh=out_fh,
                    seen_ids=seen_ids, near=near,
                    extra={"repo_path": path},
                )
                if pid:
                    added += 1
                    repo_added += 1
            except Exception as exc:
                glog(f"github {repo}: error on {path} ({exc})")
            if sleep:
                time.sleep(sleep)
        glog(f"github {repo}: added {repo_added}")
    glog(f"github: DONE added {added}")
    return added


# ──────────────────────────────────────────────────────────────────────────────
# ABC dataset — probe for an open mirror, else log BLOCKED (spec §2.5 #4)
# ──────────────────────────────────────────────────────────────────────────────
def probe_abc() -> None:
    mirrors = [
        "https://huggingface.co/api/datasets/deepmind/abc",
        "https://huggingface.co/api/datasets/ABC-Dataset/abc",
    ]
    for m in mirrors:
        try:
            r = requests.get(m, headers=_HEADERS, timeout=20)
            glog(f"ABC mirror probe {m} -> HTTP {r.status_code}")
            if r.status_code in (401, 403):
                glog(f"BLOCKED: ABC mirror {m} gated (HTTP {r.status_code}) — skipped")
            elif r.status_code == 404:
                glog(f"BLOCKED: ABC mirror {m} not found (404) — skipped")
        except Exception as exc:
            glog(f"BLOCKED: ABC mirror {m} unreachable ({exc}) — skipped")
    glog("BLOCKED: ABC CAD dataset — no open, login-free mesh mirror resolved; "
         "STEP-only entries also un-tessellable (cadquery not installed). Skipped per spec §2.4/§2.5.")


# ──────────────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--thingi", type=int, default=420, help="Thingi10K target count")
    ap.add_argument("--github", type=int, default=1, help="1=fetch github repos")
    ap.add_argument("--existing", type=int, default=1, help="1=ingest existing parts")
    ap.add_argument("--existing-limit", type=int, default=0, help="0=all")
    ap.add_argument("--sleep", type=float, default=0.05)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ensure_dirs()

    seen_ids, near = load_seen()
    glog(f"start: {len(seen_ids)} parts already in manifest")
    probe_abc()

    total_added = 0
    with MANIFEST.open("a") as out_fh:
        if args.existing:
            total_added += ingest_existing(
                out_fh, seen_ids, near,
                limit=(args.existing_limit or None))
        if args.thingi > 0:
            total_added += fetch_thingi10k(args.thingi, out_fh, seen_ids, near, args.sleep)
        if args.github:
            total_added += fetch_github(out_fh, seen_ids, near)

    glog(f"DONE: added {total_added} new parts; manifest now {len(seen_ids)} parts")
    flush_log("Gatherer run")
    print(f"corpus parts in manifest: {len(seen_ids)}  (+{total_added} this run)")


if __name__ == "__main__":
    main()
