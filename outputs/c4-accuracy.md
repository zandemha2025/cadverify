# Cycle 4 — Routing-Accuracy + Similarity (machine report)

_Generated 2026-06-29T03:50:17.692704+00:00 by `python -m src.eval.run`._

> **SMOKE — synthetic seed labels, NOT human ground truth.** This run scored the quarantined smoke seed
> (`data/labels.seed.jsonl`, labeler `SMOKE_SEED`) purely to exercise the
> pipeline. These numbers are **NOT** an accuracy measurement.

> **INSUFFICIENT HUMAN LABELS (n=0 < 30) — PIPELINE SMOKE ONLY, NOT GROUND TRUTH**
> Headline accuracy is withheld; the confusion matrix below is PROVISIONAL.

**Status:** SMOKE  |  **human labels (manufacturable):** 0  |  **gate:** 0/30

## Coverage

- Parts scored this run: **5**
- `no_route` (engine produced no pick): **0**
- Per-label counts: `{"additive": 1, "subtractive": 1, "injection_molding": 1, "sheet_metal": 1, "casting": 1}`
- Skipped: **1** (`[{"part_id": "01f0ad14923567aea3d4b365275ce88d3d62dbd29c9034fc19fcb54f23ce14f9", "reason": "label 'unsure_other' not scored"}]`)

## Top-1 accuracy

_Withheld — not ground truth (see banner). Raw fraction shown for plumbing only:_
- raw correct/scored = **1/5** (0.200) — PROVISIONAL/SMOKE

## Confusion matrix (rows = true human label, cols = engine family)

```
true \ engine   addtv  subtr  injmo  sheet  cast   noRte   | total
------------------------------------------------------------------
additive            1      0      0      0      0      0   | 1
subtractive         1      0      0      0      0      0   | 1
injection_molding      1      0      0      0      0      0   | 1
sheet_metal         1      0      0      0      0      0   | 1
casting             0      1      0      0      0      0   | 1
```

## Per-family precision / recall

| family | precision | recall | support |
|---|---|---|---|
| additive | 0.250 | 1.000 | 1 |
| subtractive | 0.000 | 0.000 | 1 |
| injection_molding | 0.000 | 0.000 | 1 |
| sheet_metal | 0.000 | 0.000 | 1 |
| casting | 0.000 | 0.000 | 1 |

## Mis-route list (ranked by engine confidence — most-confident-wrong first)

| true | engine_best | engine_family | score | top-3 | dataset | part_id |
|---|---|---|---|---|---|---|
| sheet_metal | dlp | additive | 1.00 | dlp:1.00, cnc_3axis:1.00, cnc_5axis:1.00 | Thingi10K | `01094739dae3` |
| casting | wire_edm | subtractive | 1.00 | wire_edm:1.00, sla:0.90, dlp:0.90 | Thingi10K | `01b094f4fc70` |
| subtractive | sla | additive | 1.00 | sla:1.00, dlp:1.00, sls:1.00 | Thingi10K | `0204c16ec9ac` |
| injection_molding | sls | additive | 0.90 | sls:0.90, mjf:0.90, fdm:0.80 | Thingi10K | `0109832a6889` |

## k-NN similarity example ('resembles these labeled parts')

_Neighbour pool + feature provenance: neighbour pool = SMOKE seed labels; vectors from features.npz + 2 on-the-fly rows (N=502)_

Query part: `023e1210312d (macchina_m2_M2R3_CASE_TOP_UTD.STL)`

| rank | neighbor part_id | label | distance | shared descriptors | dataset |
|---|---|---|---|---|---|
| 1 | `0012f6a9f15c` | additive | 2.199 | watertight, log_n_curved, log_bodies | Thingi10K |
| 2 | `01b094f4fc70` | casting | 3.152 | watertight, curved_area_frac, log_bodies | Thingi10K |
| 3 | `01094739dae3` | sheet_metal | 3.341 | watertight, log_n_curved, curved_area_frac | Thingi10K |
| 4 | `0204c16ec9ac` | subtractive | 4.134 | watertight, log_n_curved, log_bodies | Thingi10K |
| 5 | `0109832a6889` | injection_molding | 4.943 | watertight, log_n_curved, curved_area_frac | Thingi10K |
| 6 | `01f0ad149235` | unsure_other | 6.106 | curved_area_frac, log_n_curved, squareness | Thingi10K |

## Regenerating real metrics once humans have labelled

1. Label parts in the tool (writes `data/labels.jsonl`, append-only).
2. Once **>= 30** parts carry a manufacturable human label, run the real eval:
   ```
   cd backend
   python -m src.eval.run --build-features   # one-time; builds features.npz
   python -m src.eval.run                     # real, ungated metrics
   ```
3. The smoke seed never participates in a non-`--smoke` run.
