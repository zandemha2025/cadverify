# CadVerify Cycle 4 — Corpus Gatherer Report

**Role:** Corpus Gatherer · **Date:** 2026-06-28 · **Status:** COMPLETE (667 real parts ≥ 300 floor)

This is the honest record of what was **actually downloaded** into the local CAD corpus per
`outputs/c4-spec.md` §2. Every part is a genuine mesh fetched from a reachable, openly-licensed
source. **No geometry was fabricated. No manufacturing-method labels were assigned** (the only
per-part family field is an explicitly-tagged, unverified `process_family_guess` heuristic).

---

## 1. Headline

| Metric | Value |
|---|---|
| **Total parts on disk** | **667** (manifest records == STL files == unique sha256 part_ids) |
| Hard floor (spec) | 300 — **cleared (2.2×)** |
| Corpus location | `data/corpus/meshes/<part_id>.stl` + `data/corpus/manifest.jsonl` (gitignored) |
| On-disk size | 2.6 GB (455 Thingi10K meshes dominate; faces capped at 400k for viewer) |
| Dedup | by sha256 of normalized STL bytes — **0 duplicate ids, 0 sha256 mismatches, 0 orphan files** |
| source_url + license | **present on all 667 records** (0 empty) |
| Spot-check | 3 random manifest parts load cleanly with trimesh ✔ |

---

## 2. Per-source table (name · URL · license · count)

| Source | URL | License(s) | Count |
|---|---|---|---:|
| **Thingi10K** (HF dataset) | `https://huggingface.co/datasets/Thingi10K/Thingi10K` (`/resolve/main/raw_meshes/<id>.stl`) | per-file: CC-BY-SA 239, CC-BY 196, GPL 13, CC0 5, BSD 1, Public-Domain 1 | **455** |
| **Existing 107 repo parts** | per-part real `source_url` (Printables / Thangs / GitHub / GitLab / Bimmerpost / projectzero.build) | per-model UNKNOWN (recorded with real source_url) | **104** |
| **GitHub: AngelLM/Thor** | `https://github.com/AngelLM/Thor` (robot arm) | CC-BY-SA-4.0 | **40** |
| **GitHub: prusa3d/Original-Prusa-i3** | `https://github.com/prusa3d/Original-Prusa-i3` (MK3 printed parts) | GPL-2.0 | **38** |
| **GitHub: BCN3D/BCN3D-Moveo** | `https://github.com/BCN3D/BCN3D-Moveo` (robot arm) | MIT | **30** |
| | | **TOTAL** | **667** |

### License totals across the whole corpus

| License | Count | | License | Count |
|---|---:|---|---|---:|
| CC-BY-SA (Thingi) | 239 | | GPL-2.0 (Prusa) | 38 |
| CC-BY (Thingi) | 196 | | MIT (BCN3D) | 30 |
| CC-BY-SA-4.0 (Thor) | 40 | | GPL / CC0 / BSD / Public-Domain (Thingi) | 13 / 5 / 1 / 1 |
| **UNKNOWN — per-model, see source_url** (existing parts) | **104** | | | |

**84% (563/667)** carry an explicit open license string. The 104 UNKNOWN are the pre-existing
repo parts: their license is *per-model on a consumer site* (Printables/Thangs/forum/Drive) or a
repo without a clean per-file license — every one still has a **real `source_url`** where the
license is checkable, so it is recorded honestly as `UNKNOWN (... — see source_url)` rather than
guessed. No NC / ND Thingi10K licenses were ingested (excluded at selection time).

---

## 3. Geometry-diversity breakdown (the point: not "more hobbyist prints")

Balancing was done by **source + raw geometry buckets only** (spec §2.6) — **never** by the
engine's routing pick (that would bias the very sample the eval measures).

**Face-count** (`n_faces`: min 48 · p25 1,638 · median 8,188 · p75 35,522 · max 389,366)

| <1k | 1k–5k | 5k–20k | 20k–100k | >100k |
|---:|---:|---:|---:|---:|
| 123 | 162 | 164 | 124 | 94 |

**Bounding-box diagonal**

| <30 mm | 30–80 mm | 80–200 mm | >200 mm |
|---:|---:|---:|---:|
| 55 | 200 | 308 | 104 |

**Watertightness:** 534 watertight · **133 non-watertight** (expected for many Thingi10K meshes;
`volume_cm3 = 0.0` is recorded as-is for those per spec §1.1, relying on the `watertight` flag).

Thingi10K downloads were stratified across the five face-count buckets (≈84 per bucket target) and
interleaved across Thingiverse content categories, giving a broad spread of gears, brackets,
mechanical fixtures, housings and organic shapes — geometrically far more varied than the
additive-only automotive enclosures of the original 107.

---

## 4. Heuristic family-guess distribution — **GUESS, NOT A LABEL**

`process_family_guess` is an explicit, engine-independent `heuristic_v1` (bbox dims + watertightness
+ convex-hull solidity; see `backend/src/corpus/guess.py`). Every record is stamped
`"UNVERIFIED HEURISTIC — not a label, not for metrics"`. It exists **only** as a coverage dashboard.
It is **never** a ground-truth label and is **never** used in eval metrics.

| Guessed family | Count | Share |
|---|---:|---:|
| additive | 451 | 67.6% |
| subtractive | 138 | 20.7% |
| sheet_metal | 78 | 11.7% |
| injection_molding / casting | 0 | 0% |

**Honest caveat:** the corpus leans additive in this *heuristic* view. Two real reasons, neither
fabricated away: (a) the only openly-licensed, login-free mesh sources that are actually reachable
(Thingiverse via Thingi10K; 3D-printed enclosure repos) are themselves additive-dominated; (b) the
weak heuristic sends every **non-watertight** mesh (133 of them) to `additive` by default, inflating
that bucket. The spec's soft "≤40% additive" target could not be met **without dropping real data or
inventing molded/cast parts**, both forbidden by the hard rules. Genuinely injection-molded / cast
geometry essentially does not exist in free, redistributable, login-free mesh hubs (it lives behind
GrabCAD login or the gated ABC dataset — see §5). This is surfaced for the human labeler and the
eval harness to weigh, not hidden.

---

## 5. Sources tried-but-unreachable / ToS-skipped (honesty trail)

| Source | Outcome |
|---|---|
| **ABC CAD dataset** (mechanical CAD) | **BLOCKED.** HF mirrors probed `deepmind/abc` and `ABC-Dataset/abc` both returned **HTTP 401 (gated)**. No open, login-free mesh mirror resolved. ABC is also largely STEP, which is un-tessellable locally (cadquery not installed, spec §2.4). Skipped — logged in `c4-corpus-log.md`. |
| **STEP / STP sources generally** | **Skipped** per spec §2.4 — no local tessellation path without cadquery. Never fabricated a substitute mesh. |
| **GrabCAD / consumer CAD portals** | **Not used** — login required and/or ToS forbids redistribution. |
| **Objaverse** (`allenai/objaverse`) | **Not pursued.** Reachable (200) but artistic/consumer geometry — low manufacturing signal; spec marks it optional last-resort. Omitted to avoid diluting with non-mechanical artistic models. |
| GitHub `AngelLM/Thor` first attempt | Transient: requested branch `master` 404'd; corrected to default branch `main` and ingested 40 parts. Logged. |

Thingi10K per-file licenses tagged NC (Non-Commercial) and ND (No-Derivatives) — 2,886 candidate
files — were **deliberately excluded** to keep the corpus cleanly redistributable.

---

## 6. Acceptance checklist

- [x] `data/corpus/meshes/` holds **667** real STLs; `manifest.jsonl` has 667 records, one per part.
- [x] Every record has real `source_url`, `dataset`, `license`, `part_id` (=sha256 of stored bytes),
      and a geometry summary from the canonical `analyze_geometry` (`n_faces`, `volume_cm3`,
      `bbox_mm`, `watertight`).
- [x] Dedup by sha256 (0 dup ids); near-dup `(round(vol,1), n_faces)` guard also applied (7 skips logged).
- [x] `data/` is gitignored (verified with `git check-ignore`).
- [x] `process_family_guess` present + tagged `heuristic_v1`, never a label, never used in metrics.
- [x] **No fabricated parts. No auto-assigned manufacturing-method labels.**
- [x] Spot-check: 3 random manifest parts load with trimesh.
- [x] ≥ 300 parts (667). Blocks (ABC gated, STEP, login sources) logged, never faked.

**Reproduce:** from `backend/` →
`python -m src.corpus.gather --thingi 460 --github 1 --existing 1`
(idempotent: re-runs dedup against the existing manifest by sha256). Modules:
`backend/src/corpus/{paths,gather,guess}.py`.
