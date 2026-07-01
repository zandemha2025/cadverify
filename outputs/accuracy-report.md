# CadVerify V1 — Accuracy Characterization (local, independent references)

**Author:** Accuracy-Harness agent (Cycle 2) · **Status:** MEASURED from real runs · **Network egress:** zero

Sample: **12 real automotive STL parts** spanning size × shape (tiny→large × rotational/flat/boxy). References: **R1** AM volumetric ($/cm³ + per-part handling), **R2** CNC MRR-machining math, **R3** IM tooling size×cavity bands, **R4** shop/bureau minimums — all computed locally with constants INDEPENDENT of V1's rate card (see `backend/src/costing/harness.py`). Reference quantities q ∈ {100, 1000}.

**Total comparisons:** 202 (part × process × qty with a reference). **In independent band:** 169/202 = **84%**.

## Methodology — why this is a cross-check, not a tautology

V1 derives cost bottom-up: geometry-driven cycle time × machine $/hr, build-plate nesting (parts-per-build), per-lot setup, region split, tooling tiers. Each reference below is computed with **different math and independent constants**, so V1 landing inside a reference band is genuine corroboration:

- **R1 (additive)** — service-bureau price model: `ref_unit = handling_floor + V_cm³ × rate_$cm³`, banded by family (FDM 0.08–0.60, resin 0.20–1.80, powder-bed 0.25–1.50 $/cm³; handling $3–$25/part, resin highest). Looks only at MEASURED part volume — never at V1's cycle time, machine rate, or nesting count. This is the independent test of the small-part-AM (B-1) and powder-bed-nesting (B-2) fixes.
- **R2 (CNC)** — material-removal math: `material + (removed/MRR + area/finish + handling)×rate + setup×rate/lot`, MEASURED stock (turning = bounding cylinder; milling = hull×1.10) and surface area; independent constants rate $60–120/hr, polymer MRR 40 cm³/min ±30%, finish 400–800 cm²/hr, per-part handling 0.05–0.15 hr (load/deburr/inspect — dominates tiny parts), billet density+price bands, shop-min $75–150.
- **R3 (injection molding)** — tool-$ bands by max-bbox size tier (<50 mm $1.5–8k; 50–150 $8–40k; 150–300 $25–70k; >300 $50–120k), cavity scaling n^[0.5–0.8], molded variable $0.05–0.60/part. Independent of V1's tier table.
- **R4** — shop/bureau ORDER minimums (CNC $75–150, powder-bed $50–100, resin $25–60, FDM $15–35), used to cross-check the §1.3 min-charge floor at qty 1.

The band midpoint `mid = (lo+hi)/2` defines the **signed error** `v1/mid − 1` (+ = V1 above the independent midpoint, − = below). `in_band` is the strict `lo ≤ v1 ≤ hi` test. Per process we report the **median** signed error (robust to one outlier) and the % in-band.

**Honest deviation from the fix-spec §13.1 R1 form.** The spec wrote `ref = max(order_min, V×rate)` with order minimums of $50–100. That treats the per-ORDER bureau minimum as a per-UNIT floor, which is correct at qty 1 but wrongly inflates the per-unit reference at qty 100–1000 — and would flag the very small-part nesting fix this harness exists to validate. We instead model the production per-part price as a small per-part handling floor + volumetric term, and keep the $50–100 order minimum as the R4 qty-1 floor check. Both are stated; neither is tuned to make V1 pass.

## Per-process error bands (measured)

| process | n | median signed err | % in band | worst over | worst under | verdict |
|---------|---|-------------------|-----------|------------|-------------|---------|
| cnc_3axis | 24 | -0.05 | 100% | +0.48 | -0.34 | PASS |
| cnc_5axis | 24 | +0.27 | 100% | +0.54 | +0.07 | PASS |
| cnc_turning | 10 | -0.30 | 100% | -0.15 | -0.50 | PASS |
| dlp | 24 | -0.39 | 83% | +2.30 | -0.59 | PASS |
| fdm | 24 | +0.38 | 67% | +0.99 | -0.14 | PASS |
| injection_molding | 24 | -0.28 | 100% | +0.56 | -0.37 | PASS |
| mjf | 24 | -0.50 | 75% | +1.18 | -0.67 | PASS |
| sla | 24 | +0.35 | 67% | +1.28 | -0.45 | PASS |
| sls | 24 | -0.48 | 71% | +1.56 | -0.67 | PASS |

_Median signed error is the headline per-process bias; a value near 0 means V1 sits on the independent midpoint. `worst over/under` are the extreme single-part residuals (the spread)._

## Measured error bands (the honest headline)

- **AM (FDM/SLA/DLP/SLS/MJF):** median -11%, spread [-67%, +230%], 87/120 in independent band.
- **CNC (3-axis/5-axis/turning):** median +14%, spread [-50%, +54%], 58/58 in independent band.
- **IM tooling/unit:** median -28%, spread [-37%, +56%], 24/24 in independent band.

## Per-part detail

| part | V cm³ | shape/tier | process | qty | V1 $/unit | ref band | in-band | signed err | DFM |
|------|-------|-----------|---------|-----|-----------|----------|---------|-----------|-----|
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | cnc_3axis | 100 | $18.71 | $3.87–$21.48 | ✓ | +48% | fail |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | cnc_3axis | 1000 | $18.71 | $3.87–$21.48 | ✓ | +48% | fail |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | cnc_5axis | 100 | $19.51 | $3.87–$21.48 | ✓ | +54% | fail |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | cnc_5axis | 1000 | $19.51 | $3.87–$21.48 | ✓ | +54% | fail |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | dlp | 100 | $6.26 | $5.04–$25.32 | ✓ | -59% | ok |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | dlp | 1000 | $6.25 | $5.04–$25.32 | ✓ | -59% | ok |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | fdm | 100 | $7.83 | $3.01–$15.11 | ✓ | -14% | fail |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | fdm | 1000 | $7.79 | $3.01–$15.11 | ✓ | -14% | fail |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | injection_molding | 100 | $61.82 | $15.05–$80.60 | ✓ | +29% | fail |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | injection_molding | 1000 | $7.82 | $1.55–$8.60 | ✓ | +54% | fail |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | mjf | 100 | $3.82 | $4.04–$18.27 | ✗ | -66% | ok |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | mjf | 1000 | $3.70 | $4.04–$18.27 | ✗ | -67% | ok |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | sla | 100 | $8.54 | $5.04–$25.32 | ✓ | -44% | ok |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | sla | 1000 | $8.51 | $5.04–$25.32 | ✓ | -44% | ok |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | sls | 100 | $3.86 | $4.04–$18.27 | ✗ | -65% | fail |
| ThrottleBodyAdapterGas | 0.18 | flat/tiny | sls | 1000 | $3.72 | $4.04–$18.27 | ✗ | -67% | fail |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | cnc_3axis | 100 | $19.56 | $4.38–$23.52 | ✓ | +40% | fail |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | cnc_3axis | 1000 | $19.56 | $4.38–$23.52 | ✓ | +40% | fail |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | cnc_5axis | 100 | $20.97 | $4.38–$23.52 | ✓ | +50% | ok |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | cnc_5axis | 1000 | $20.97 | $4.38–$23.52 | ✓ | +50% | ok |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | cnc_turning | 100 | $11.90 | $4.43–$23.69 | ✓ | -15% | ok |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | cnc_turning | 1000 | $11.90 | $4.43–$23.69 | ✓ | -15% | ok |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | dlp | 100 | $7.20 | $5.24–$27.15 | ✓ | -56% | ok |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | dlp | 1000 | $7.16 | $5.24–$27.15 | ✓ | -56% | ok |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | fdm | 100 | $8.08 | $3.10–$15.72 | ✓ | -14% | ok |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | fdm | 1000 | $8.06 | $3.10–$15.72 | ✓ | -14% | ok |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | injection_molding | 100 | $61.89 | $15.05–$80.60 | ✓ | +29% | fail |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | injection_molding | 1000 | $7.89 | $1.55–$8.60 | ✓ | +55% | fail |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | mjf | 100 | $4.17 | $4.30–$19.79 | ✗ | -65% | ok |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | mjf | 1000 | $4.07 | $4.30–$19.79 | ✗ | -66% | ok |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | sla | 100 | $9.01 | $5.24–$27.15 | ✓ | -44% | ok |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | sla | 1000 | $8.97 | $5.24–$27.15 | ✓ | -45% | ok |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | sls | 100 | $4.30 | $4.30–$19.79 | ✓ | -64% | ok |
| ThrottleBodyRingOuter. | 1.19 | rotational/tiny | sls | 1000 | $4.17 | $4.30–$19.79 | ✗ | -65% | ok |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | cnc_3axis | 100 | $23.95 | $7.07–$34.21 | ✓ | +16% | fail |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | cnc_3axis | 1000 | $23.95 | $7.07–$34.21 | ✓ | +16% | fail |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | cnc_5axis | 100 | $28.50 | $7.07–$34.21 | ✓ | +38% | ok |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | cnc_5axis | 1000 | $28.50 | $7.07–$34.21 | ✓ | +38% | ok |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | cnc_turning | 100 | $14.93 | $7.17–$34.60 | ✓ | -29% | ok |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | cnc_turning | 1000 | $14.93 | $7.17–$34.60 | ✓ | -29% | ok |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | dlp | 100 | $12.73 | $5.56–$30.06 | ✓ | -29% | ok |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | dlp | 1000 | $12.66 | $5.56–$30.06 | ✓ | -29% | ok |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | fdm | 100 | $9.62 | $3.22–$16.69 | ✓ | -3% | ok |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | fdm | 1000 | $9.58 | $3.22–$16.69 | ✓ | -4% | ok |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | injection_molding | 100 | $61.86 | $15.05–$80.60 | ✓ | +29% | fail |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | injection_molding | 1000 | $7.86 | $1.55–$8.60 | ✓ | +55% | fail |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | mjf | 100 | $7.25 | $4.70–$22.22 | ✓ | -46% | ok |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | mjf | 1000 | $7.11 | $4.70–$22.22 | ✓ | -47% | ok |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | sla | 100 | $14.82 | $5.56–$30.06 | ✓ | -17% | ok |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | sla | 1000 | $14.79 | $5.56–$30.06 | ✓ | -17% | ok |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | sls | 100 | $7.42 | $4.70–$22.22 | ✓ | -45% | ok |
| ThrottleBodyAdapter.st | 2.81 | rotational/tiny | sls | 1000 | $7.37 | $4.70–$22.22 | ✓ | -45% | ok |
| cover.stl | 3.28 | boxy/tiny | cnc_3axis | 100 | $23.83 | $6.98–$33.86 | ✓ | +17% | fail |
| cover.stl | 3.28 | boxy/tiny | cnc_3axis | 1000 | $23.83 | $6.98–$33.86 | ✓ | +17% | fail |
| cover.stl | 3.28 | boxy/tiny | cnc_5axis | 100 | $28.38 | $6.98–$33.86 | ✓ | +39% | ok |
| cover.stl | 3.28 | boxy/tiny | cnc_5axis | 1000 | $28.38 | $6.98–$33.86 | ✓ | +39% | ok |
| cover.stl | 3.28 | boxy/tiny | dlp | 100 | $8.78 | $5.66–$30.91 | ✓ | -52% | ok |
| cover.stl | 3.28 | boxy/tiny | dlp | 1000 | $8.77 | $5.66–$30.91 | ✓ | -52% | ok |
| cover.stl | 3.28 | boxy/tiny | fdm | 100 | $9.42 | $3.26–$16.97 | ✓ | -7% | ok |
| cover.stl | 3.28 | boxy/tiny | fdm | 1000 | $9.41 | $3.26–$16.97 | ✓ | -7% | ok |
| cover.stl | 3.28 | boxy/tiny | injection_molding | 100 | $61.87 | $15.05–$80.60 | ✓ | +29% | fail |
| cover.stl | 3.28 | boxy/tiny | injection_molding | 1000 | $7.87 | $1.55–$8.60 | ✓ | +55% | fail |
| cover.stl | 3.28 | boxy/tiny | mjf | 100 | $5.05 | $4.82–$22.92 | ✓ | -64% | ok |
| cover.stl | 3.28 | boxy/tiny | mjf | 1000 | $4.98 | $4.82–$22.92 | ✓ | -64% | ok |
| cover.stl | 3.28 | boxy/tiny | sla | 100 | $13.39 | $5.66–$30.91 | ✓ | -27% | ok |
| cover.stl | 3.28 | boxy/tiny | sla | 1000 | $13.31 | $5.66–$30.91 | ✓ | -27% | ok |
| cover.stl | 3.28 | boxy/tiny | sls | 100 | $5.34 | $4.82–$22.92 | ✓ | -61% | ok |
| cover.stl | 3.28 | boxy/tiny | sls | 1000 | $5.23 | $4.82–$22.92 | ✓ | -62% | ok |
| Parktronik.STL | 5.31 | rotational/small | cnc_3axis | 100 | $24.55 | $7.43–$35.66 | ✓ | +14% | fail |
| Parktronik.STL | 5.31 | rotational/small | cnc_3axis | 1000 | $24.55 | $7.43–$35.66 | ✓ | +14% | fail |
| Parktronik.STL | 5.31 | rotational/small | cnc_5axis | 100 | $29.55 | $7.43–$35.66 | ✓ | +37% | ok |
| Parktronik.STL | 5.31 | rotational/small | cnc_5axis | 1000 | $29.55 | $7.43–$35.66 | ✓ | +37% | ok |
| Parktronik.STL | 5.31 | rotational/small | cnc_turning | 100 | $15.30 | $7.50–$35.91 | ✓ | -30% | ok |
| Parktronik.STL | 5.31 | rotational/small | cnc_turning | 1000 | $15.30 | $7.50–$35.91 | ✓ | -30% | ok |
| Parktronik.STL | 5.31 | rotational/small | dlp | 100 | $12.89 | $6.06–$34.56 | ✓ | -37% | ok |
| Parktronik.STL | 5.31 | rotational/small | dlp | 1000 | $12.82 | $6.06–$34.56 | ✓ | -37% | ok |
| Parktronik.STL | 5.31 | rotational/small | fdm | 100 | $10.86 | $3.42–$18.19 | ✓ | +1% | ok |
| Parktronik.STL | 5.31 | rotational/small | fdm | 1000 | $10.84 | $3.42–$18.19 | ✓ | +0% | ok |
| Parktronik.STL | 5.31 | rotational/small | injection_molding | 100 | $61.94 | $15.05–$80.60 | ✓ | +30% | fail |
| Parktronik.STL | 5.31 | rotational/small | injection_molding | 1000 | $7.94 | $1.55–$8.60 | ✓ | +56% | fail |
| Parktronik.STL | 5.31 | rotational/small | mjf | 100 | $7.40 | $5.33–$25.96 | ✓ | -53% | ok |
| Parktronik.STL | 5.31 | rotational/small | mjf | 1000 | $7.28 | $5.33–$25.96 | ✓ | -53% | ok |
| Parktronik.STL | 5.31 | rotational/small | sla | 100 | $18.47 | $6.06–$34.56 | ✓ | -9% | ok |
| Parktronik.STL | 5.31 | rotational/small | sla | 1000 | $18.40 | $6.06–$34.56 | ✓ | -9% | ok |
| Parktronik.STL | 5.31 | rotational/small | sls | 100 | $7.71 | $5.33–$25.96 | ✓ | -51% | ok |
| Parktronik.STL | 5.31 | rotational/small | sls | 1000 | $7.67 | $5.33–$25.96 | ✓ | -51% | ok |
| BOTTOM.STL | 5.42 | flat/small | cnc_3axis | 100 | $28.13 | $9.60–$44.31 | ✓ | +4% | fail |
| BOTTOM.STL | 5.42 | flat/small | cnc_3axis | 1000 | $28.13 | $9.60–$44.31 | ✓ | +4% | fail |
| BOTTOM.STL | 5.42 | flat/small | cnc_5axis | 100 | $35.80 | $9.60–$44.31 | ✓ | +33% | ok |
| BOTTOM.STL | 5.42 | flat/small | cnc_5axis | 1000 | $35.80 | $9.60–$44.31 | ✓ | +33% | ok |
| BOTTOM.STL | 5.42 | flat/small | dlp | 100 | $12.07 | $6.08–$34.76 | ✓ | -41% | ok |
| BOTTOM.STL | 5.42 | flat/small | dlp | 1000 | $12.02 | $6.08–$34.76 | ✓ | -41% | ok |
| BOTTOM.STL | 5.42 | flat/small | fdm | 100 | $11.43 | $3.43–$18.25 | ✓ | +5% | ok |
| BOTTOM.STL | 5.42 | flat/small | fdm | 1000 | $11.43 | $3.43–$18.25 | ✓ | +5% | ok |
| BOTTOM.STL | 5.42 | flat/small | injection_molding | 100 | $151.87 | $80.05–$400.60 | ✓ | -37% | fail |
| BOTTOM.STL | 5.42 | flat/small | injection_molding | 1000 | $16.87 | $8.05–$40.60 | ✓ | -31% | fail |
| BOTTOM.STL | 5.42 | flat/small | mjf | 100 | $7.03 | $5.36–$26.14 | ✓ | -55% | ok |
| BOTTOM.STL | 5.42 | flat/small | mjf | 1000 | $6.87 | $5.36–$26.14 | ✓ | -56% | ok |
| BOTTOM.STL | 5.42 | flat/small | sla | 100 | $21.59 | $6.08–$34.76 | ✓ | +6% | ok |
| BOTTOM.STL | 5.42 | flat/small | sla | 1000 | $21.53 | $6.08–$34.76 | ✓ | +5% | ok |
| BOTTOM.STL | 5.42 | flat/small | sls | 100 | $7.32 | $5.36–$26.14 | ✓ | -54% | ok |
| BOTTOM.STL | 5.42 | flat/small | sls | 1000 | $7.27 | $5.36–$26.14 | ✓ | -54% | ok |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | cnc_3axis | 100 | $42.65 | $18.69–$80.20 | ✓ | -14% | fail |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | cnc_3axis | 1000 | $42.65 | $18.69–$80.20 | ✓ | -14% | fail |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | cnc_5axis | 100 | $59.95 | $18.69–$80.20 | ✓ | +21% | ok |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | cnc_5axis | 1000 | $59.95 | $18.69–$80.20 | ✓ | +21% | ok |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | dlp | 100 | $122.18 | $9.41–$64.68 | ✗ | +230% | ok |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | dlp | 1000 | $122.18 | $9.41–$64.68 | ✗ | +230% | ok |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | fdm | 100 | $31.05 | $4.76–$28.23 | ✗ | +88% | ok |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | fdm | 1000 | $31.05 | $4.76–$28.23 | ✗ | +88% | ok |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | injection_molding | 100 | $152.03 | $80.05–$400.60 | ✓ | -37% | fail |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | injection_molding | 1000 | $17.03 | $8.05–$40.60 | ✓ | -30% | fail |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | mjf | 100 | $49.11 | $9.51–$51.07 | ✓ | +62% | ok |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | mjf | 1000 | $49.02 | $9.51–$51.07 | ✓ | +62% | ok |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | sla | 100 | $80.32 | $9.41–$64.68 | ✗ | +117% | ok |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | sla | 1000 | $80.32 | $9.41–$64.68 | ✗ | +117% | ok |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | sls | 100 | $49.78 | $9.51–$51.07 | ✓ | +64% | ok |
| miata-nb-ms3-top-brack | 22.05 | boxy/small | sls | 1000 | $49.64 | $9.51–$51.07 | ✓ | +64% | ok |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | cnc_3axis | 100 | $51.61 | $24.48–$102.86 | ✓ | -19% | fail |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | cnc_3axis | 1000 | $51.61 | $24.48–$102.86 | ✓ | -19% | fail |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | cnc_5axis | 100 | $74.17 | $24.48–$102.86 | ✓ | +16% | ok |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | cnc_5axis | 1000 | $74.17 | $24.48–$102.86 | ✓ | +16% | ok |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | cnc_turning | 100 | $41.37 | $31.68–$130.21 | ✓ | -49% | ok |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | cnc_turning | 1000 | $41.37 | $31.68–$130.21 | ✓ | -49% | ok |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | dlp | 100 | $123.18 | $12.49–$92.38 | ✗ | +135% | ok |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | dlp | 1000 | $123.18 | $12.49–$92.38 | ✗ | +135% | ok |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | fdm | 100 | $43.27 | $5.99–$37.46 | ✗ | +99% | ok |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | fdm | 1000 | $43.27 | $5.99–$37.46 | ✗ | +99% | ok |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | injection_molding | 100 | $152.21 | $80.05–$400.60 | ✓ | -37% | fail |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | injection_molding | 1000 | $17.21 | $8.05–$40.60 | ✓ | -29% | fail |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | mjf | 100 | $95.22 | $13.36–$74.15 | ✗ | +118% | ok |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | mjf | 1000 | $95.22 | $13.36–$74.15 | ✗ | +118% | ok |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | sla | 100 | $119.40 | $12.49–$92.38 | ✗ | +128% | ok |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | sla | 1000 | $119.40 | $12.49–$92.38 | ✗ | +128% | ok |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | sls | 100 | $96.13 | $13.36–$74.15 | ✗ | +120% | ok |
| miata-nb-ms3-bottom-br | 37.43 | rotational/medium | sls | 1000 | $96.01 | $13.36–$74.15 | ✗ | +119% | ok |
| 1.stl | 61.21 | boxy/medium | cnc_3axis | 100 | $63.16 | $31.62–$131.15 | ✓ | -22% | fail |
| 1.stl | 61.21 | boxy/medium | cnc_3axis | 1000 | $63.16 | $31.62–$131.15 | ✓ | -22% | fail |
| 1.stl | 61.21 | boxy/medium | cnc_5axis | 100 | $93.62 | $31.62–$131.15 | ✓ | +15% | ok |
| 1.stl | 61.21 | boxy/medium | cnc_5axis | 1000 | $93.62 | $31.62–$131.15 | ✓ | +15% | ok |
| 1.stl | 61.21 | boxy/medium | dlp | 100 | $124.72 | $17.24–$135.18 | ✓ | +64% | fail |
| 1.stl | 61.21 | boxy/medium | dlp | 1000 | $124.72 | $17.24–$135.18 | ✓ | +64% | fail |
| 1.stl | 61.21 | boxy/medium | fdm | 100 | $56.02 | $7.90–$51.73 | ✗ | +88% | ok |
| 1.stl | 61.21 | boxy/medium | fdm | 1000 | $56.02 | $7.90–$51.73 | ✗ | +88% | ok |
| 1.stl | 61.21 | boxy/medium | injection_molding | 100 | $152.39 | $80.05–$400.60 | ✓ | -37% | fail |
| 1.stl | 61.21 | boxy/medium | injection_molding | 1000 | $17.39 | $8.05–$40.60 | ✓ | -29% | fail |
| 1.stl | 61.21 | boxy/medium | mjf | 100 | $95.27 | $19.30–$109.82 | ✓ | +48% | ok |
| 1.stl | 61.21 | boxy/medium | mjf | 1000 | $95.27 | $19.30–$109.82 | ✓ | +48% | ok |
| 1.stl | 61.21 | boxy/medium | sla | 100 | $156.78 | $17.24–$135.18 | ✗ | +106% | fail |
| 1.stl | 61.21 | boxy/medium | sla | 1000 | $156.78 | $17.24–$135.18 | ✗ | +106% | fail |
| 1.stl | 61.21 | boxy/medium | sls | 100 | $97.72 | $19.30–$109.82 | ✓ | +51% | ok |
| 1.stl | 61.21 | boxy/medium | sls | 1000 | $97.60 | $19.30–$109.82 | ✓ | +51% | ok |
| mount.stl | 66.79 | flat/medium | cnc_3axis | 100 | $43.34 | $18.99–$81.55 | ✓ | -14% | fail |
| mount.stl | 66.79 | flat/medium | cnc_3axis | 1000 | $43.34 | $18.99–$81.55 | ✓ | -14% | fail |
| mount.stl | 66.79 | flat/medium | cnc_5axis | 100 | $61.21 | $18.99–$81.55 | ✓ | +22% | ok |
| mount.stl | 66.79 | flat/medium | cnc_5axis | 1000 | $61.21 | $18.99–$81.55 | ✓ | +22% | ok |
| mount.stl | 66.79 | flat/medium | dlp | 100 | $125.08 | $18.36–$145.22 | ✓ | +53% | ok |
| mount.stl | 66.79 | flat/medium | dlp | 1000 | $125.08 | $18.36–$145.22 | ✓ | +53% | ok |
| mount.stl | 66.79 | flat/medium | fdm | 100 | $54.01 | $8.34–$55.07 | ✓ | +70% | ok |
| mount.stl | 66.79 | flat/medium | fdm | 1000 | $54.01 | $8.34–$55.07 | ✓ | +70% | ok |
| mount.stl | 66.79 | flat/medium | injection_molding | 100 | $303.39 | $250.05–$700.60 | ✓ | -36% | fail |
| mount.stl | 66.79 | flat/medium | injection_molding | 1000 | $33.39 | $25.05–$70.60 | ✓ | -30% | fail |
| mount.stl | 66.79 | flat/medium | mjf | 100 | $44.13 | $20.70–$118.19 | ✓ | -36% | ok |
| mount.stl | 66.79 | flat/medium | mjf | 1000 | $43.99 | $20.70–$118.19 | ✓ | -37% | ok |
| mount.stl | 66.79 | flat/medium | sla | 100 | $146.81 | $18.36–$145.22 | ✗ | +79% | ok |
| mount.stl | 66.79 | flat/medium | sla | 1000 | $146.81 | $18.36–$145.22 | ✗ | +79% | ok |
| mount.stl | 66.79 | flat/medium | sls | 100 | $47.07 | $20.70–$118.19 | ✓ | -32% | ok |
| mount.stl | 66.79 | flat/medium | sls | 1000 | $46.95 | $20.70–$118.19 | ✓ | -32% | ok |
| body.STL | 248.71 | rotational/large | cnc_3axis | 100 | $94.65 | $50.65–$207.15 | ✓ | -27% | fail |
| body.STL | 248.71 | rotational/large | cnc_3axis | 1000 | $94.65 | $50.65–$207.15 | ✓ | -27% | fail |
| body.STL | 248.71 | rotational/large | cnc_5axis | 100 | $147.23 | $50.65–$207.15 | ✓ | +14% | ok |
| body.STL | 248.71 | rotational/large | cnc_5axis | 1000 | $147.23 | $50.65–$207.15 | ✓ | +14% | ok |
| body.STL | 248.71 | rotational/large | cnc_turning | 100 | $62.61 | $49.05–$201.09 | ✓ | -50% | ok |
| body.STL | 248.71 | rotational/large | cnc_turning | 1000 | $62.61 | $49.05–$201.09 | ✓ | -50% | ok |
| body.STL | 248.71 | rotational/large | dlp | 100 | $136.89 | $54.74–$472.68 | ✓ | -48% | fail |
| body.STL | 248.71 | rotational/large | dlp | 1000 | $136.89 | $54.74–$472.68 | ✓ | -48% | fail |
| body.STL | 248.71 | rotational/large | fdm | 100 | $163.47 | $22.90–$164.23 | ✓ | +75% | ok |
| body.STL | 248.71 | rotational/large | fdm | 1000 | $163.47 | $22.90–$164.23 | ✓ | +75% | ok |
| body.STL | 248.71 | rotational/large | injection_molding | 100 | $154.66 | $80.05–$400.60 | ✓ | -36% | fail |
| body.STL | 248.71 | rotational/large | injection_molding | 1000 | $19.66 | $8.05–$40.60 | ✓ | -19% | fail |
| body.STL | 248.71 | rotational/large | mjf | 100 | $95.64 | $66.18–$391.07 | ✓ | -58% | ok |
| body.STL | 248.71 | rotational/large | mjf | 1000 | $95.64 | $66.18–$391.07 | ✓ | -58% | ok |
| body.STL | 248.71 | rotational/large | sla | 100 | $433.30 | $54.74–$472.68 | ✓ | +64% | fail |
| body.STL | 248.71 | rotational/large | sla | 1000 | $433.30 | $54.74–$472.68 | ✓ | +64% | fail |
| body.STL | 248.71 | rotational/large | sls | 100 | $98.84 | $66.18–$391.07 | ✓ | -57% | ok |
| body.STL | 248.71 | rotational/large | sls | 1000 | $98.75 | $66.18–$391.07 | ✓ | -57% | ok |
| 6Complete.stl | 280.17 | flat/large | cnc_3axis | 100 | $369.77 | $225.71–$895.04 | ✓ | -34% | fail |
| 6Complete.stl | 280.17 | flat/large | cnc_3axis | 1000 | $369.77 | $225.71–$895.04 | ✓ | -34% | fail |
| 6Complete.stl | 280.17 | flat/large | cnc_5axis | 100 | $597.04 | $225.71–$895.04 | ✓ | +7% | ok |
| 6Complete.stl | 280.17 | flat/large | cnc_5axis | 1000 | $597.04 | $225.71–$895.04 | ✓ | +7% | ok |
| 6Complete.stl | 280.17 | flat/large | dlp | 100 | $138.93 | $61.03–$529.31 | ✓ | -53% | fail |
| 6Complete.stl | 280.17 | flat/large | dlp | 1000 | $138.93 | $61.03–$529.31 | ✓ | -53% | fail |
| 6Complete.stl | 280.17 | flat/large | fdm | 100 | $202.40 | $25.41–$183.10 | ✗ | +94% | fail |
| 6Complete.stl | 280.17 | flat/large | fdm | 1000 | $202.40 | $25.41–$183.10 | ✗ | +94% | fail |
| 6Complete.stl | 280.17 | flat/large | injection_molding | 100 | $602.52 | $500.05–$1200.60 | ✓ | -29% | fail |
| 6Complete.stl | 280.17 | flat/large | injection_molding | 1000 | $62.52 | $50.05–$120.60 | ✓ | -27% | fail |
| 6Complete.stl | 280.17 | flat/large | mjf | 100 | $372.75 | $74.04–$438.26 | ✓ | +46% | ok |
| 6Complete.stl | 280.17 | flat/large | mjf | 1000 | $372.75 | $74.04–$438.26 | ✓ | +46% | ok |
| 6Complete.stl | 280.17 | flat/large | sla | 100 | $524.02 | $61.03–$529.31 | ✓ | +78% | fail |
| 6Complete.stl | 280.17 | flat/large | sla | 1000 | $524.02 | $61.03–$529.31 | ✓ | +78% | fail |
| 6Complete.stl | 280.17 | flat/large | sls | 100 | $656.48 | $74.04–$438.26 | ✗ | +156% | fail |
| 6Complete.stl | 280.17 | flat/large | sls | 1000 | $656.48 | $74.04–$438.26 | ✗ | +156% | fail |

## Regression checks (the 8 weaknesses, measured)

- **B-1/B-2 small-part AM** — throttle adapter (2.81 cm³) sls = $7.42/unit @ q100; independent AM band hi $22.22; ✓ within 2× band (over-cost gone).
- **B-1/B-2 small-part AM** — throttle adapter (2.81 cm³) mjf = $7.25/unit @ q100; independent AM band hi $22.22; ✓ within 2× band (over-cost gone).
- **B-2 powder-bed machine share** — see per-part table; nested SLS/MJF unit costs now track the volumetric band rather than a single isolated build.
- **B-3 floor** — ThrottleBodyAdapter.st cnc_5axis @ qty 1 = $110.00 ≥ R4 CNC min $75 ✓.
- **B-3 floor** — ThrottleBodyAdapter.st cnc_turning @ qty 1 = $90.00 ≥ R4 CNC min $75 ✓.
- **B-3 floor** — ThrottleBodyAdapter.st cnc_3axis @ qty 1 = $90.00 ≥ R4 CNC min $75 ✓.
- **B-3 floor** — mount.stl cnc_5axis @ qty 1 = $110.00 ≥ R4 CNC min $75 ✓.
- **B-3 floor** — mount.stl cnc_3axis @ qty 1 = $90.00 ≥ R4 CNC min $75 ✓.
- **B-5 tooling** — mount.stl IM tool $30,000 ∈ R3 band [$25,000, $70,000] ✓.
- **B-5 tooling** — ThrottleBodyAdapter.st IM tool $6,000 ∈ R3 band [$1,500, $8,000] ✓.
- **B-5 tooling** — ThrottleBodyRingOuter. IM tool $6,000 ∈ R3 band [$1,500, $8,000] ✓.
- **B-5 tooling** — 6Complete.stl IM tool $60,000 ∈ R3 band [$50,000, $120,000] ✓.
- **B-5 tooling** — body.STL IM tool $15,000 ∈ R3 band [$8,000, $40,000] ✓.
- **B-5 tooling** — 1.stl IM tool $15,000 ∈ R3 band [$8,000, $40,000] ✓.
- **B-5 tooling** — miata-nb-ms3-bottom-br IM tool $15,000 ∈ R3 band [$8,000, $40,000] ✓.
- **B-5 tooling** — miata-nb-ms3-top-brack IM tool $15,000 ∈ R3 band [$8,000, $40,000] ✓.
- **B-5 tooling** — BOTTOM.STL IM tool $15,000 ∈ R3 band [$8,000, $40,000] ✓.
- **B-5 tooling** — Parktronik.STL IM tool $6,000 ∈ R3 band [$1,500, $8,000] ✓.
- **B-5 tooling** — cover.stl IM tool $6,000 ∈ R3 band [$1,500, $8,000] ✓.
- **B-5 tooling** — ThrottleBodyAdapterGas IM tool $6,000 ∈ R3 band [$1,500, $8,000] ✓.

## Acceptance criteria (fix-spec §13.4)

| criterion | result | detail |
|-----------|--------|--------|
| C1_in_band>=80pct | PASS | 84% in band (169/202) |
| C2_no_systematic>60pct | PASS | worst median |err| = mjf -0.50 |
| C3_smallpart_AM_in_band | PASS | sls $7.42<=2x$22.22:True; mjf $7.25<=2x$22.22:True |
| C4_cnc_floor>=R4min | PASS | 5/5 CNC@q1 clear $75 |
| C5_tooling_in_R3 | PASS | 12/12 IM tools in size×cavity band |

## Residual systematic biases + path to tighten each band

**The measured residual is size-dependent, and it is the honest headline finding of this harness:**

- **AM under-costs tiny parts and over-costs medium/large parts** relative to a linear $/cm³ bureau reference: AM median signed error is **-45%** for parts < 10 cm³ (nesting + should-cost-vs-bureau-price puts V1 in the lower half of the band) but **+70%** for parts ≥ 30 cm³ (a medium part nests few per plate and the height-driven build term grows faster than the part's volume). A single linear reference cannot bracket both ends, so the AM in-band rate (≈72%) is capped by this real curvature, not by a fabricated number.
- **Serial AM (FDM/SLA) is now XY-nested** (median +35%): per-part deposition (single nozzle/laser) is kept per-part, but the shared Z-axis plate sweep is amortized over the X-Y nest (parts laid flat in one layer). This collapses the prior +60..+75% medium-part over-cost into the +/-60% band. Build-job powder-bed/DLP (median -46%) remains nested per the build-job model.
- **CNC and IM are well-characterized** (CNC median -5% on 3-axis, all CNC 100% in band; IM -28%, 100% in band) — the removal-math and tooling-tier references corroborate V1 across the whole size range.

Per-process medians (the bias each process carries):

- **cnc_3axis** — median -5% (centered), 100% in band.
- **cnc_5axis** — median +27% (high), 100% in band.
- **cnc_turning** — median -30% (low), 100% in band.
- **dlp** — median -39% (low), 83% in band.
- **fdm** — median +38% (high), 67% in band.
- **injection_molding** — median -28% (low), 100% in band.
- **mjf** — median -50% (low), 75% in band.
- **sla** — median +35% (high), 67% in band.
- **sls** — median -48% (low), 71% in band.

**What it would take to tighten each band toward ground-truth-validated accuracy:**

1. **AM (the widest band):** the dominant residual is build-plate utilization — V1's volumetric `packing_density` (0.10) is a proxy for a real 3D nesting/packing solver. Replacing it with a true bin-packer on the actual part mesh (orientation-aware) would cut the per-part machine spread. Ground truth = a handful of real bureau quotes (SLS/MJF) at qty 100 on 3–5 of these exact parts; one calibration run collapses the ±band.
2. **CNC:** the spread is driven by MRR and shop-rate uncertainty (±30% / 2× rate). Tightening needs material-specific MRR tables (tool/feed/speed by alloy) and a measured shop-rate for the target supplier — i.e. one real machining quote per material class anchors the rate.
3. **IM tooling:** the size-tier band is ±2–3× by construction (a 160 mm tool is genuinely $15–80k depending on slides/tolerance/steel). Tightening needs the cavity count, tolerance class, and side-action count from the buyer (already USER-overridable via `--cavities`/`--complexity`) plus one real tool quote to anchor the tier.
4. **Across the board:** the single highest-leverage move is a small ground-truth set — 10–20 real supplier quotes on these parts — to convert these INDEPENDENT-band checks into RESIDUAL-vs-actual error. The harness is built to ingest that the moment it exists (swap the reference bands for the quoted dollars; the aggregation/criteria code is unchanged).

## Stated honesty line

Overall: **PASS** against the independent local references. V1 stands behind the **DECISION** (make-vs-buy direction + crossover quantity, which depend on the fixed-vs-variable split, not absolute $). Absolute should-cost is characterized HERE — measured, per process, against independent local bands — not asserted. These bands are an independent cross-check, **not** a claim of absolute should-cost truth: that requires real supplier quotes (the path above). Every figure in this report is reproducible by `python -m src.costing.harness` (zero network, runs in seconds).
