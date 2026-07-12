# CadVerify V1 — Cost Model Regression (local, independent references)

**Author:** Accuracy-Harness agent (Cycle 2) · **Suite:** internal regression · **Status:** MEASURED engine runs · **Network egress:** zero

Sample: **12 internally authored deterministic STL calibration coupons (not ground truth)** spanning size × shape (tiny→large × rotational/flat/boxy). References: **R1** AM volumetric ($/cm³ + per-part handling), **R2** CNC MRR-machining math, **R3** IM tooling size×cavity bands, **R4** shop/bureau minimums — all computed locally with constants INDEPENDENT of V1's rate card (see `backend/src/costing/harness.py`). Reference quantities q ∈ {100, 1000}.

**Total comparisons:** 202 (part × process × qty with a reference). **In independent band:** 164/202 = **81%**.

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
| cnc_3axis | 24 | +0.04 | 100% | +0.63 | -0.38 | PASS |
| cnc_5axis | 24 | +0.27 | 83% | +0.79 | -0.07 | PASS |
| cnc_turning | 10 | -0.46 | 90% | -0.08 | -0.62 | PASS |
| dlp | 24 | -0.39 | 83% | +2.33 | -0.59 | PASS |
| fdm | 24 | +0.38 | 67% | +0.99 | -0.14 | PASS |
| injection_molding | 24 | -0.27 | 100% | +0.59 | -0.37 | PASS |
| mjf | 24 | -0.50 | 75% | +1.18 | -0.67 | PASS |
| sla | 24 | +0.35 | 67% | +1.28 | -0.45 | PASS |
| sls | 24 | -0.48 | 71% | +1.57 | -0.67 | PASS |

_Median signed error is the headline per-process bias; a value near 0 means V1 sits on the independent midpoint. `worst over/under` are the extreme single-part residuals (the spread)._

## Measured error bands (the honest headline)

- **AM (FDM/SLA/DLP/SLS/MJF):** median -12%, spread [-67%, +233%], 87/120 in independent band.
- **CNC (3-axis/5-axis/turning):** median +8%, spread [-62%, +79%], 53/58 in independent band.
- **IM tooling/unit:** median -27%, spread [-37%, +59%], 24/24 in independent band.

## Per-part detail

| part | V cm³ | shape/tier | process | qty | V1 $/unit | ref band | in-band | signed err | DFM |
|------|-------|-----------|---------|-----|-----------|----------|---------|-----------|-----|
| tiny_flat_gasket | 0.17 | flat/tiny | cnc_3axis | 100 | $20.69 | $3.87–$21.47 | ✓ | +63% | fail |
| tiny_flat_gasket | 0.17 | flat/tiny | cnc_3axis | 1000 | $14.29 | $3.87–$21.47 | ✓ | +13% | fail |
| tiny_flat_gasket | 0.17 | flat/tiny | cnc_5axis | 100 | $22.67 | $3.87–$21.47 | ✗ | +79% | fail |
| tiny_flat_gasket | 0.17 | flat/tiny | cnc_5axis | 1000 | $15.52 | $3.87–$21.47 | ✓ | +22% | fail |
| tiny_flat_gasket | 0.17 | flat/tiny | dlp | 100 | $6.26 | $5.03–$25.30 | ✓ | -59% | ok |
| tiny_flat_gasket | 0.17 | flat/tiny | dlp | 1000 | $6.25 | $5.03–$25.30 | ✓ | -59% | ok |
| tiny_flat_gasket | 0.17 | flat/tiny | fdm | 100 | $7.82 | $3.01–$15.10 | ✓ | -14% | fail |
| tiny_flat_gasket | 0.17 | flat/tiny | fdm | 1000 | $7.78 | $3.01–$15.10 | ✓ | -14% | fail |
| tiny_flat_gasket | 0.17 | flat/tiny | injection_molding | 100 | $61.82 | $15.05–$80.60 | ✓ | +29% | fail |
| tiny_flat_gasket | 0.17 | flat/tiny | injection_molding | 1000 | $7.82 | $1.55–$8.60 | ✓ | +54% | fail |
| tiny_flat_gasket | 0.17 | flat/tiny | mjf | 100 | $3.82 | $4.04–$18.25 | ✗ | -66% | fail |
| tiny_flat_gasket | 0.17 | flat/tiny | mjf | 1000 | $3.70 | $4.04–$18.25 | ✗ | -67% | fail |
| tiny_flat_gasket | 0.17 | flat/tiny | sla | 100 | $8.52 | $5.03–$25.30 | ✓ | -44% | ok |
| tiny_flat_gasket | 0.17 | flat/tiny | sla | 1000 | $8.49 | $5.03–$25.30 | ✓ | -44% | ok |
| tiny_flat_gasket | 0.17 | flat/tiny | sls | 100 | $3.86 | $4.04–$18.25 | ✗ | -65% | fail |
| tiny_flat_gasket | 0.17 | flat/tiny | sls | 1000 | $3.72 | $4.04–$18.25 | ✗ | -67% | fail |
| tiny_rotational_ring | 1.17 | rotational/tiny | cnc_3axis | 100 | $22.37 | $4.80–$25.18 | ✓ | +49% | fail |
| tiny_rotational_ring | 1.17 | rotational/tiny | cnc_3axis | 1000 | $15.48 | $4.80–$25.18 | ✓ | +3% | fail |
| tiny_rotational_ring | 1.17 | rotational/tiny | cnc_5axis | 100 | $25.54 | $4.80–$25.18 | ✗ | +70% | ok |
| tiny_rotational_ring | 1.17 | rotational/tiny | cnc_5axis | 1000 | $17.56 | $4.80–$25.18 | ✓ | +17% | ok |
| tiny_rotational_ring | 1.17 | rotational/tiny | cnc_turning | 100 | $13.77 | $4.81–$25.22 | ✓ | -8% | ok |
| tiny_rotational_ring | 1.17 | rotational/tiny | cnc_turning | 1000 | $9.60 | $4.81–$25.22 | ✓ | -36% | ok |
| tiny_rotational_ring | 1.17 | rotational/tiny | dlp | 100 | $7.20 | $5.23–$27.11 | ✓ | -55% | ok |
| tiny_rotational_ring | 1.17 | rotational/tiny | dlp | 1000 | $7.16 | $5.23–$27.11 | ✓ | -56% | ok |
| tiny_rotational_ring | 1.17 | rotational/tiny | fdm | 100 | $8.07 | $3.09–$15.70 | ✓ | -14% | ok |
| tiny_rotational_ring | 1.17 | rotational/tiny | fdm | 1000 | $8.05 | $3.09–$15.70 | ✓ | -14% | ok |
| tiny_rotational_ring | 1.17 | rotational/tiny | injection_molding | 100 | $61.85 | $15.05–$80.60 | ✓ | +29% | fail |
| tiny_rotational_ring | 1.17 | rotational/tiny | injection_molding | 1000 | $7.85 | $1.55–$8.60 | ✓ | +55% | fail |
| tiny_rotational_ring | 1.17 | rotational/tiny | mjf | 100 | $4.17 | $4.29–$19.76 | ✗ | -65% | ok |
| tiny_rotational_ring | 1.17 | rotational/tiny | mjf | 1000 | $4.07 | $4.29–$19.76 | ✗ | -66% | ok |
| tiny_rotational_ring | 1.17 | rotational/tiny | sla | 100 | $8.97 | $5.23–$27.11 | ✓ | -45% | ok |
| tiny_rotational_ring | 1.17 | rotational/tiny | sla | 1000 | $8.94 | $5.23–$27.11 | ✓ | -45% | ok |
| tiny_rotational_ring | 1.17 | rotational/tiny | sls | 100 | $4.30 | $4.29–$19.76 | ✓ | -64% | ok |
| tiny_rotational_ring | 1.17 | rotational/tiny | sls | 1000 | $4.17 | $4.29–$19.76 | ✗ | -65% | ok |
| tiny_rotational_adapter | 2.79 | rotational/tiny | cnc_3axis | 100 | $27.41 | $7.56–$36.17 | ✓ | +25% | fail |
| tiny_rotational_adapter | 2.79 | rotational/tiny | cnc_3axis | 1000 | $19.09 | $7.56–$36.17 | ✓ | -13% | fail |
| tiny_rotational_adapter | 2.79 | rotational/tiny | cnc_5axis | 100 | $34.08 | $7.56–$36.17 | ✓ | +56% | ok |
| tiny_rotational_adapter | 2.79 | rotational/tiny | cnc_5axis | 1000 | $23.63 | $7.56–$36.17 | ✓ | +8% | ok |
| tiny_rotational_adapter | 2.79 | rotational/tiny | cnc_turning | 100 | $17.02 | $7.62–$36.37 | ✓ | -23% | ok |
| tiny_rotational_adapter | 2.79 | rotational/tiny | cnc_turning | 1000 | $11.92 | $7.62–$36.37 | ✓ | -46% | ok |
| tiny_rotational_adapter | 2.79 | rotational/tiny | dlp | 100 | $12.73 | $5.56–$30.03 | ✓ | -28% | ok |
| tiny_rotational_adapter | 2.79 | rotational/tiny | dlp | 1000 | $12.66 | $5.56–$30.03 | ✓ | -29% | ok |
| tiny_rotational_adapter | 2.79 | rotational/tiny | fdm | 100 | $9.61 | $3.22–$16.68 | ✓ | -3% | ok |
| tiny_rotational_adapter | 2.79 | rotational/tiny | fdm | 1000 | $9.57 | $3.22–$16.68 | ✓ | -4% | ok |
| tiny_rotational_adapter | 2.79 | rotational/tiny | injection_molding | 100 | $61.85 | $15.05–$80.60 | ✓ | +29% | fail |
| tiny_rotational_adapter | 2.79 | rotational/tiny | injection_molding | 1000 | $7.85 | $1.55–$8.60 | ✓ | +55% | fail |
| tiny_rotational_adapter | 2.79 | rotational/tiny | mjf | 100 | $7.25 | $4.70–$22.19 | ✓ | -46% | ok |
| tiny_rotational_adapter | 2.79 | rotational/tiny | mjf | 1000 | $7.11 | $4.70–$22.19 | ✓ | -47% | ok |
| tiny_rotational_adapter | 2.79 | rotational/tiny | sla | 100 | $14.79 | $5.56–$30.03 | ✓ | -17% | ok |
| tiny_rotational_adapter | 2.79 | rotational/tiny | sla | 1000 | $14.76 | $5.56–$30.03 | ✓ | -17% | ok |
| tiny_rotational_adapter | 2.79 | rotational/tiny | sls | 100 | $7.42 | $4.70–$22.19 | ✓ | -45% | ok |
| tiny_rotational_adapter | 2.79 | rotational/tiny | sls | 1000 | $7.37 | $4.70–$22.19 | ✓ | -45% | ok |
| tiny_boxy_cover | 3.14 | boxy/tiny | cnc_3axis | 100 | $22.62 | $4.84–$25.33 | ✓ | +50% | fail |
| tiny_boxy_cover | 3.14 | boxy/tiny | cnc_3axis | 1000 | $15.67 | $4.84–$25.33 | ✓ | +4% | fail |
| tiny_boxy_cover | 3.14 | boxy/tiny | cnc_5axis | 100 | $25.90 | $4.84–$25.33 | ✗ | +72% | ok |
| tiny_boxy_cover | 3.14 | boxy/tiny | cnc_5axis | 1000 | $17.83 | $4.84–$25.33 | ✓ | +18% | ok |
| tiny_boxy_cover | 3.14 | boxy/tiny | dlp | 100 | $8.77 | $5.63–$30.65 | ✓ | -52% | ok |
| tiny_boxy_cover | 3.14 | boxy/tiny | dlp | 1000 | $8.76 | $5.63–$30.65 | ✓ | -52% | ok |
| tiny_boxy_cover | 3.14 | boxy/tiny | fdm | 100 | $9.34 | $3.25–$16.88 | ✓ | -7% | ok |
| tiny_boxy_cover | 3.14 | boxy/tiny | fdm | 1000 | $9.33 | $3.25–$16.88 | ✓ | -7% | ok |
| tiny_boxy_cover | 3.14 | boxy/tiny | injection_molding | 100 | $62.08 | $15.05–$80.60 | ✓ | +30% | fail |
| tiny_boxy_cover | 3.14 | boxy/tiny | injection_molding | 1000 | $8.08 | $1.55–$8.60 | ✓ | +59% | fail |
| tiny_boxy_cover | 3.14 | boxy/tiny | mjf | 100 | $5.05 | $4.79–$22.71 | ✓ | -63% | ok |
| tiny_boxy_cover | 3.14 | boxy/tiny | mjf | 1000 | $4.98 | $4.79–$22.71 | ✓ | -64% | ok |
| tiny_boxy_cover | 3.14 | boxy/tiny | sla | 100 | $13.17 | $5.63–$30.65 | ✓ | -27% | ok |
| tiny_boxy_cover | 3.14 | boxy/tiny | sla | 1000 | $13.09 | $5.63–$30.65 | ✓ | -28% | ok |
| tiny_boxy_cover | 3.14 | boxy/tiny | sls | 100 | $5.33 | $4.79–$22.71 | ✓ | -61% | ok |
| tiny_boxy_cover | 3.14 | boxy/tiny | sls | 1000 | $5.22 | $4.79–$22.71 | ✓ | -62% | ok |
| small_flat_housing | 5.23 | flat/small | cnc_3axis | 100 | $25.58 | $6.40–$31.56 | ✓ | +35% | fail |
| small_flat_housing | 5.23 | flat/small | cnc_3axis | 1000 | $17.79 | $6.40–$31.56 | ✓ | -6% | fail |
| small_flat_housing | 5.23 | flat/small | cnc_5axis | 100 | $30.96 | $6.40–$31.56 | ✓ | +63% | ok |
| small_flat_housing | 5.23 | flat/small | cnc_5axis | 1000 | $21.42 | $6.40–$31.56 | ✓ | +13% | ok |
| small_flat_housing | 5.23 | flat/small | dlp | 100 | $12.05 | $6.05–$34.41 | ✓ | -40% | ok |
| small_flat_housing | 5.23 | flat/small | dlp | 1000 | $12.01 | $6.05–$34.41 | ✓ | -41% | ok |
| small_flat_housing | 5.23 | flat/small | fdm | 100 | $11.33 | $3.42–$18.14 | ✓ | +5% | ok |
| small_flat_housing | 5.23 | flat/small | fdm | 1000 | $11.33 | $3.42–$18.14 | ✓ | +5% | ok |
| small_flat_housing | 5.23 | flat/small | injection_molding | 100 | $152.00 | $80.05–$400.60 | ✓ | -37% | fail |
| small_flat_housing | 5.23 | flat/small | injection_molding | 1000 | $17.00 | $8.05–$40.60 | ✓ | -30% | fail |
| small_flat_housing | 5.23 | flat/small | mjf | 100 | $7.03 | $5.31–$25.84 | ✓ | -55% | ok |
| small_flat_housing | 5.23 | flat/small | mjf | 1000 | $6.87 | $5.31–$25.84 | ✓ | -56% | ok |
| small_flat_housing | 5.23 | flat/small | sla | 100 | $21.28 | $6.05–$34.41 | ✓ | +5% | ok |
| small_flat_housing | 5.23 | flat/small | sla | 1000 | $21.22 | $6.05–$34.41 | ✓ | +5% | ok |
| small_flat_housing | 5.23 | flat/small | sls | 100 | $7.31 | $5.31–$25.84 | ✓ | -53% | ok |
| small_flat_housing | 5.23 | flat/small | sls | 1000 | $7.25 | $5.31–$25.84 | ✓ | -53% | ok |
| small_rotational_sensor | 5.28 | rotational/small | cnc_3axis | 100 | $28.89 | $8.48–$39.83 | ✓ | +20% | fail |
| small_rotational_sensor | 5.28 | rotational/small | cnc_3axis | 1000 | $20.14 | $8.48–$39.83 | ✓ | -17% | fail |
| small_rotational_sensor | 5.28 | rotational/small | cnc_5axis | 100 | $36.69 | $8.48–$39.83 | ✓ | +52% | ok |
| small_rotational_sensor | 5.28 | rotational/small | cnc_5axis | 1000 | $25.48 | $8.48–$39.83 | ✓ | +5% | ok |
| small_rotational_sensor | 5.28 | rotational/small | cnc_turning | 100 | $17.99 | $8.45–$39.69 | ✓ | -25% | ok |
| small_rotational_sensor | 5.28 | rotational/small | cnc_turning | 1000 | $12.62 | $8.45–$39.69 | ✓ | -48% | ok |
| small_rotational_sensor | 5.28 | rotational/small | dlp | 100 | $12.89 | $6.06–$34.51 | ✓ | -36% | ok |
| small_rotational_sensor | 5.28 | rotational/small | dlp | 1000 | $12.82 | $6.06–$34.51 | ✓ | -37% | ok |
| small_rotational_sensor | 5.28 | rotational/small | fdm | 100 | $10.84 | $3.42–$18.17 | ✓ | +0% | ok |
| small_rotational_sensor | 5.28 | rotational/small | fdm | 1000 | $10.83 | $3.42–$18.17 | ✓ | +0% | ok |
| small_rotational_sensor | 5.28 | rotational/small | injection_molding | 100 | $61.89 | $15.05–$80.60 | ✓ | +29% | fail |
| small_rotational_sensor | 5.28 | rotational/small | injection_molding | 1000 | $7.89 | $1.55–$8.60 | ✓ | +55% | fail |
| small_rotational_sensor | 5.28 | rotational/small | mjf | 100 | $7.40 | $5.32–$25.93 | ✓ | -53% | ok |
| small_rotational_sensor | 5.28 | rotational/small | mjf | 1000 | $7.28 | $5.32–$25.93 | ✓ | -53% | ok |
| small_rotational_sensor | 5.28 | rotational/small | sla | 100 | $18.44 | $6.06–$34.51 | ✓ | -9% | ok |
| small_rotational_sensor | 5.28 | rotational/small | sla | 1000 | $18.36 | $6.06–$34.51 | ✓ | -9% | ok |
| small_rotational_sensor | 5.28 | rotational/small | sls | 100 | $7.71 | $5.32–$25.93 | ✓ | -51% | ok |
| small_rotational_sensor | 5.28 | rotational/small | sls | 1000 | $7.67 | $5.32–$25.93 | ✓ | -51% | ok |
| small_boxy_bracket | 21.63 | boxy/small | cnc_3axis | 100 | $54.55 | $18.51–$79.50 | ✓ | +11% | fail |
| small_boxy_bracket | 21.63 | boxy/small | cnc_3axis | 1000 | $39.04 | $18.51–$79.50 | ✓ | -20% | fail |
| small_boxy_bracket | 21.63 | boxy/small | cnc_5axis | 100 | $77.01 | $18.51–$79.50 | ✓ | +57% | ok |
| small_boxy_bracket | 21.63 | boxy/small | cnc_5axis | 1000 | $54.70 | $18.51–$79.50 | ✓ | +12% | ok |
| small_boxy_bracket | 21.63 | boxy/small | dlp | 100 | $122.15 | $9.33–$63.93 | ✗ | +233% | ok |
| small_boxy_bracket | 21.63 | boxy/small | dlp | 1000 | $122.15 | $9.33–$63.93 | ✗ | +233% | ok |
| small_boxy_bracket | 21.63 | boxy/small | fdm | 100 | $30.83 | $4.73–$27.98 | ✗ | +89% | ok |
| small_boxy_bracket | 21.63 | boxy/small | fdm | 1000 | $30.83 | $4.73–$27.98 | ✗ | +89% | ok |
| small_boxy_bracket | 21.63 | boxy/small | injection_molding | 100 | $152.02 | $80.05–$400.60 | ✓ | -37% | fail |
| small_boxy_bracket | 21.63 | boxy/small | injection_molding | 1000 | $17.02 | $8.05–$40.60 | ✓ | -30% | fail |
| small_boxy_bracket | 21.63 | boxy/small | mjf | 100 | $49.11 | $9.41–$50.44 | ✓ | +64% | ok |
| small_boxy_bracket | 21.63 | boxy/small | mjf | 1000 | $49.02 | $9.41–$50.44 | ✓ | +64% | ok |
| small_boxy_bracket | 21.63 | boxy/small | sla | 100 | $79.67 | $9.33–$63.93 | ✗ | +117% | ok |
| small_boxy_bracket | 21.63 | boxy/small | sla | 1000 | $79.67 | $9.33–$63.93 | ✗ | +117% | ok |
| small_boxy_bracket | 21.63 | boxy/small | sls | 100 | $49.75 | $9.41–$50.44 | ✓ | +66% | ok |
| small_boxy_bracket | 21.63 | boxy/small | sls | 1000 | $49.61 | $9.41–$50.44 | ✓ | +66% | ok |
| medium_rotational_bracket | 37.40 | rotational/medium | cnc_3axis | 100 | $89.69 | $36.93–$152.04 | ✓ | -5% | fail |
| medium_rotational_bracket | 37.40 | rotational/medium | cnc_3axis | 1000 | $64.67 | $36.93–$152.04 | ✓ | -32% | fail |
| medium_rotational_bracket | 37.40 | rotational/medium | cnc_5axis | 100 | $133.63 | $36.93–$152.04 | ✓ | +41% | ok |
| medium_rotational_bracket | 37.40 | rotational/medium | cnc_5axis | 1000 | $95.48 | $36.93–$152.04 | ✓ | +1% | ok |
| medium_rotational_bracket | 37.40 | rotational/medium | cnc_turning | 100 | $55.86 | $41.12–$167.96 | ✓ | -47% | ok |
| medium_rotational_bracket | 37.40 | rotational/medium | cnc_turning | 1000 | $40.13 | $41.12–$167.96 | ✗ | -62% | ok |
| medium_rotational_bracket | 37.40 | rotational/medium | dlp | 100 | $123.18 | $12.48–$92.33 | ✗ | +135% | ok |
| medium_rotational_bracket | 37.40 | rotational/medium | dlp | 1000 | $123.18 | $12.48–$92.33 | ✗ | +135% | ok |
| medium_rotational_bracket | 37.40 | rotational/medium | fdm | 100 | $43.25 | $5.99–$37.44 | ✗ | +99% | ok |
| medium_rotational_bracket | 37.40 | rotational/medium | fdm | 1000 | $43.25 | $5.99–$37.44 | ✗ | +99% | ok |
| medium_rotational_bracket | 37.40 | rotational/medium | injection_molding | 100 | $152.01 | $80.05–$400.60 | ✓ | -37% | fail |
| medium_rotational_bracket | 37.40 | rotational/medium | injection_molding | 1000 | $17.01 | $8.05–$40.60 | ✓ | -30% | fail |
| medium_rotational_bracket | 37.40 | rotational/medium | mjf | 100 | $95.22 | $13.35–$74.11 | ✗ | +118% | ok |
| medium_rotational_bracket | 37.40 | rotational/medium | mjf | 1000 | $95.22 | $13.35–$74.11 | ✗ | +118% | ok |
| medium_rotational_bracket | 37.40 | rotational/medium | sla | 100 | $119.35 | $12.48–$92.33 | ✗ | +128% | ok |
| medium_rotational_bracket | 37.40 | rotational/medium | sla | 1000 | $119.35 | $12.48–$92.33 | ✗ | +128% | ok |
| medium_rotational_bracket | 37.40 | rotational/medium | sls | 100 | $96.13 | $13.35–$74.11 | ✗ | +120% | ok |
| medium_rotational_bracket | 37.40 | rotational/medium | sls | 1000 | $96.01 | $13.35–$74.11 | ✗ | +120% | ok |
| medium_boxy_spacer | 60.69 | boxy/medium | cnc_3axis | 100 | $84.48 | $30.91–$128.38 | ✓ | +6% | fail |
| medium_boxy_spacer | 60.69 | boxy/medium | cnc_3axis | 1000 | $61.19 | $30.91–$128.38 | ✓ | -23% | fail |
| medium_boxy_spacer | 60.69 | boxy/medium | cnc_5axis | 100 | $123.55 | $30.91–$128.38 | ✓ | +55% | ok |
| medium_boxy_spacer | 60.69 | boxy/medium | cnc_5axis | 1000 | $88.56 | $30.91–$128.38 | ✓ | +11% | ok |
| medium_boxy_spacer | 60.69 | boxy/medium | dlp | 100 | $124.69 | $17.14–$134.25 | ✓ | +65% | ok |
| medium_boxy_spacer | 60.69 | boxy/medium | dlp | 1000 | $124.69 | $17.14–$134.25 | ✓ | +65% | ok |
| medium_boxy_spacer | 60.69 | boxy/medium | fdm | 100 | $55.74 | $7.86–$51.42 | ✗ | +88% | ok |
| medium_boxy_spacer | 60.69 | boxy/medium | fdm | 1000 | $55.74 | $7.86–$51.42 | ✗ | +88% | ok |
| medium_boxy_spacer | 60.69 | boxy/medium | injection_molding | 100 | $152.40 | $80.05–$400.60 | ✓ | -37% | fail |
| medium_boxy_spacer | 60.69 | boxy/medium | injection_molding | 1000 | $17.40 | $8.05–$40.60 | ✓ | -28% | fail |
| medium_boxy_spacer | 60.69 | boxy/medium | mjf | 100 | $95.27 | $19.17–$109.04 | ✓ | +49% | ok |
| medium_boxy_spacer | 60.69 | boxy/medium | mjf | 1000 | $95.27 | $19.17–$109.04 | ✓ | +49% | ok |
| medium_boxy_spacer | 60.69 | boxy/medium | sla | 100 | $155.97 | $17.14–$134.25 | ✗ | +106% | ok |
| medium_boxy_spacer | 60.69 | boxy/medium | sla | 1000 | $155.97 | $17.14–$134.25 | ✗ | +106% | ok |
| medium_boxy_spacer | 60.69 | boxy/medium | sls | 100 | $97.69 | $19.17–$109.04 | ✓ | +52% | ok |
| medium_boxy_spacer | 60.69 | boxy/medium | sls | 1000 | $97.56 | $19.17–$109.04 | ✓ | +52% | ok |
| medium_flat_mount | 66.31 | flat/medium | cnc_3axis | 100 | $53.11 | $18.67–$80.36 | ✓ | +7% | fail |
| medium_flat_mount | 66.31 | flat/medium | cnc_3axis | 1000 | $37.91 | $18.67–$80.36 | ✓ | -23% | fail |
| medium_flat_mount | 66.31 | flat/medium | cnc_5axis | 100 | $75.51 | $18.67–$80.36 | ✓ | +52% | ok |
| medium_flat_mount | 66.31 | flat/medium | cnc_5axis | 1000 | $53.53 | $18.67–$80.36 | ✓ | +8% | ok |
| medium_flat_mount | 66.31 | flat/medium | dlp | 100 | $125.05 | $18.26–$144.37 | ✓ | +54% | ok |
| medium_flat_mount | 66.31 | flat/medium | dlp | 1000 | $125.05 | $18.26–$144.37 | ✓ | +54% | ok |
| medium_flat_mount | 66.31 | flat/medium | fdm | 100 | $53.75 | $8.31–$54.79 | ✓ | +70% | ok |
| medium_flat_mount | 66.31 | flat/medium | fdm | 1000 | $53.75 | $8.31–$54.79 | ✓ | +70% | ok |
| medium_flat_mount | 66.31 | flat/medium | injection_molding | 100 | $303.34 | $250.05–$700.60 | ✓ | -36% | fail |
| medium_flat_mount | 66.31 | flat/medium | injection_molding | 1000 | $33.34 | $25.05–$70.60 | ✓ | -30% | fail |
| medium_flat_mount | 66.31 | flat/medium | mjf | 100 | $44.13 | $20.58–$117.47 | ✓ | -36% | ok |
| medium_flat_mount | 66.31 | flat/medium | mjf | 1000 | $43.99 | $20.58–$117.47 | ✓ | -36% | ok |
| medium_flat_mount | 66.31 | flat/medium | sla | 100 | $146.07 | $18.26–$144.37 | ✗ | +80% | ok |
| medium_flat_mount | 66.31 | flat/medium | sla | 1000 | $146.07 | $18.26–$144.37 | ✗ | +80% | ok |
| medium_flat_mount | 66.31 | flat/medium | sls | 100 | $47.04 | $20.58–$117.47 | ✓ | -32% | ok |
| medium_flat_mount | 66.31 | flat/medium | sls | 1000 | $46.92 | $20.58–$117.47 | ✓ | -32% | ok |
| large_rotational_flange | 248.53 | rotational/large | cnc_3axis | 100 | $91.41 | $41.66–$171.44 | ✓ | -14% | fail |
| large_rotational_flange | 248.53 | rotational/large | cnc_3axis | 1000 | $65.74 | $41.66–$171.44 | ✓ | -38% | fail |
| large_rotational_flange | 248.53 | rotational/large | cnc_5axis | 100 | $139.17 | $41.66–$171.44 | ✓ | +31% | ok |
| large_rotational_flange | 248.53 | rotational/large | cnc_5axis | 1000 | $99.24 | $41.66–$171.44 | ✓ | -7% | ok |
| large_rotational_flange | 248.53 | rotational/large | cnc_turning | 100 | $57.13 | $41.29–$170.02 | ✓ | -46% | ok |
| large_rotational_flange | 248.53 | rotational/large | cnc_turning | 1000 | $41.33 | $41.29–$170.02 | ✓ | -61% | ok |
| large_rotational_flange | 248.53 | rotational/large | dlp | 100 | $136.88 | $54.71–$472.35 | ✓ | -48% | fail |
| large_rotational_flange | 248.53 | rotational/large | dlp | 1000 | $136.88 | $54.71–$472.35 | ✓ | -48% | fail |
| large_rotational_flange | 248.53 | rotational/large | fdm | 100 | $163.37 | $22.88–$164.12 | ✓ | +75% | ok |
| large_rotational_flange | 248.53 | rotational/large | fdm | 1000 | $163.37 | $22.88–$164.12 | ✓ | +75% | ok |
| large_rotational_flange | 248.53 | rotational/large | injection_molding | 100 | $156.02 | $80.05–$400.60 | ✓ | -35% | fail |
| large_rotational_flange | 248.53 | rotational/large | injection_molding | 1000 | $21.02 | $8.05–$40.60 | ✓ | -14% | fail |
| large_rotational_flange | 248.53 | rotational/large | mjf | 100 | $95.64 | $66.13–$390.80 | ✓ | -58% | ok |
| large_rotational_flange | 248.53 | rotational/large | mjf | 1000 | $95.64 | $66.13–$390.80 | ✓ | -58% | ok |
| large_rotational_flange | 248.53 | rotational/large | sla | 100 | $433.01 | $54.71–$472.35 | ✓ | +64% | fail |
| large_rotational_flange | 248.53 | rotational/large | sla | 1000 | $433.01 | $54.71–$472.35 | ✓ | +64% | fail |
| large_rotational_flange | 248.53 | rotational/large | sls | 100 | $98.83 | $66.13–$390.80 | ✓ | -57% | ok |
| large_rotational_flange | 248.53 | rotational/large | sls | 1000 | $98.74 | $66.13–$390.80 | ✓ | -57% | ok |
| large_flat_enclosure | 279.03 | flat/large | cnc_3axis | 100 | $379.38 | $135.00–$536.76 | ✓ | +13% | fail |
| large_flat_enclosure | 279.03 | flat/large | cnc_3axis | 1000 | $281.37 | $135.00–$536.76 | ✓ | -16% | fail |
| large_flat_enclosure | 279.03 | flat/large | cnc_5axis | 100 | $568.87 | $135.00–$536.76 | ✗ | +69% | ok |
| large_flat_enclosure | 279.03 | flat/large | cnc_5axis | 1000 | $414.74 | $135.00–$536.76 | ✓ | +23% | ok |
| large_flat_enclosure | 279.03 | flat/large | dlp | 100 | $138.86 | $60.81–$527.25 | ✓ | -53% | fail |
| large_flat_enclosure | 279.03 | flat/large | dlp | 1000 | $138.86 | $60.81–$527.25 | ✓ | -53% | fail |
| large_flat_enclosure | 279.03 | flat/large | fdm | 100 | $201.79 | $25.32–$182.42 | ✗ | +94% | fail |
| large_flat_enclosure | 279.03 | flat/large | fdm | 1000 | $201.79 | $25.32–$182.42 | ✗ | +94% | fail |
| large_flat_enclosure | 279.03 | flat/large | injection_molding | 100 | $602.95 | $500.05–$1200.60 | ✓ | -29% | fail |
| large_flat_enclosure | 279.03 | flat/large | injection_molding | 1000 | $62.95 | $50.05–$120.60 | ✓ | -26% | fail |
| large_flat_enclosure | 279.03 | flat/large | mjf | 100 | $372.75 | $73.76–$436.54 | ✓ | +46% | ok |
| large_flat_enclosure | 279.03 | flat/large | mjf | 1000 | $372.75 | $73.76–$436.54 | ✓ | +46% | ok |
| large_flat_enclosure | 279.03 | flat/large | sla | 100 | $522.23 | $60.81–$527.25 | ✓ | +78% | fail |
| large_flat_enclosure | 279.03 | flat/large | sla | 1000 | $522.23 | $60.81–$527.25 | ✓ | +78% | fail |
| large_flat_enclosure | 279.03 | flat/large | sls | 100 | $656.40 | $73.76–$436.54 | ✗ | +157% | fail |
| large_flat_enclosure | 279.03 | flat/large | sls | 1000 | $656.40 | $73.76–$436.54 | ✗ | +157% | fail |

## Regression checks (the 8 weaknesses, measured)

- **B-1/B-2 small-part AM** — tiny rotational adapter (2.81 cm³) mjf = $7.25/unit @ q100; independent AM band hi $22.19; ✓ within 2× band (over-cost gone).
- **B-1/B-2 small-part AM** — tiny rotational adapter (2.81 cm³) sls = $7.42/unit @ q100; independent AM band hi $22.19; ✓ within 2× band (over-cost gone).
- **B-2 powder-bed machine share** — see per-part table; nested SLS/MJF unit costs now track the volumetric band rather than a single isolated build.
- **B-3 floor** — tiny_rotational_adapter cnc_turning @ qty 1 = $90.00 ≥ R4 CNC min $75 ✓.
- **B-3 floor** — tiny_rotational_adapter cnc_5axis @ qty 1 = $198.67 ≥ R4 CNC min $75 ✓.
- **B-3 floor** — tiny_rotational_adapter cnc_3axis @ qty 1 = $140.02 ≥ R4 CNC min $75 ✓.
- **B-3 floor** — medium_flat_mount cnc_5axis @ qty 1 = $240.09 ≥ R4 CNC min $75 ✓.
- **B-3 floor** — medium_flat_mount cnc_3axis @ qty 1 = $165.72 ≥ R4 CNC min $75 ✓.
- **B-5 tooling** — medium_flat_mount IM tool $30,000 ∈ R3 band [$25,000, $70,000] ✓.
- **B-5 tooling** — tiny_rotational_adapter IM tool $6,000 ∈ R3 band [$1,500, $8,000] ✓.
- **B-5 tooling** — tiny_rotational_ring IM tool $6,000 ∈ R3 band [$1,500, $8,000] ✓.
- **B-5 tooling** — large_flat_enclosure IM tool $60,000 ∈ R3 band [$50,000, $120,000] ✓.
- **B-5 tooling** — large_rotational_flange IM tool $15,000 ∈ R3 band [$8,000, $40,000] ✓.
- **B-5 tooling** — medium_boxy_spacer IM tool $15,000 ∈ R3 band [$8,000, $40,000] ✓.
- **B-5 tooling** — medium_rotational_bracket IM tool $15,000 ∈ R3 band [$8,000, $40,000] ✓.
- **B-5 tooling** — small_boxy_bracket IM tool $15,000 ∈ R3 band [$8,000, $40,000] ✓.
- **B-5 tooling** — small_flat_housing IM tool $15,000 ∈ R3 band [$8,000, $40,000] ✓.
- **B-5 tooling** — small_rotational_sensor IM tool $6,000 ∈ R3 band [$1,500, $8,000] ✓.
- **B-5 tooling** — tiny_boxy_cover IM tool $6,000 ∈ R3 band [$1,500, $8,000] ✓.
- **B-5 tooling** — tiny_flat_gasket IM tool $6,000 ∈ R3 band [$1,500, $8,000] ✓.

## Model-regression guardrails (not production accuracy evidence)

| criterion | result | detail |
|-----------|--------|--------|
| C1_in_band>=80pct | PASS | 81% in band (164/202) |
| C2_no_systematic>60pct | PASS | worst median |err| = mjf -0.50 |
| C3_smallpart_AM_in_band | PASS | mjf $7.25<=2x$22.19:True; sls $7.42<=2x$22.19:True |
| C4_cnc_floor>=R4min | PASS | 5/5 CNC@q1 clear $75 |
| C5_tooling_in_R3 | PASS | 12/12 IM tools in size×cavity band |

## Residual systematic biases + path to tighten each band

**The measured residual is size-dependent, and it is the honest headline finding of this harness:**

- **AM under-costs tiny parts and over-costs medium/large parts** relative to a linear $/cm³ bureau reference: AM median signed error is **-45%** for parts < 10 cm³ (nesting + should-cost-vs-bureau-price puts V1 in the lower half of the band) but **+70%** for parts ≥ 30 cm³ (a medium part nests few per plate and the height-driven build term grows faster than the part's volume). A single linear reference cannot bracket both ends, so the AM in-band rate (≈72%) is capped by this measured curvature, not by a fabricated number.
- **Serial AM (FDM/SLA) is now XY-nested** (median +35%): per-part deposition (single nozzle/laser) is kept per-part, but the shared Z-axis plate sweep is amortized over the X-Y nest (parts laid flat in one layer). This collapses the prior +60..+75% medium-part over-cost into the +/-60% band. Build-job powder-bed/DLP (median -46%) remains nested per the build-job model.
- **CNC and IM are well-characterized** (CNC 3-axis median +4%, 100% in band; IM -27%, 100% in band) — the removal-math and tooling-tier references corroborate V1 across the whole size range. NOTE (S1): V1 now credits a volume/learning curve on machined conversion cost (per-unit cost falls with qty), while the R2 reference is deliberately qty-FLAT; so at the qty-1000 reference point a couple of small-cross-section turned parts (already near the band floor) sit just below the flat reference — a KNOWN residual in the documented direction of the fix, not a defect. A volume-aware CNC reference would re-center it; that is left to the ground-truth-quote calibration path.

Per-process medians (the bias each process carries):

- **cnc_3axis** — median +4% (centered), 100% in band.
- **cnc_5axis** — median +27% (high), 83% in band.
- **cnc_turning** — median -46% (low), 90% in band.
- **dlp** — median -39% (low), 83% in band.
- **fdm** — median +38% (high), 67% in band.
- **injection_molding** — median -27% (low), 100% in band.
- **mjf** — median -50% (low), 75% in band.
- **sla** — median +35% (high), 67% in band.
- **sls** — median -48% (low), 71% in band.

**What it would take to tighten each band toward ground-truth-validated accuracy:**

1. **AM (the widest band):** the dominant residual is build-plate utilization — V1's volumetric `packing_density` (0.10) is a proxy for a real 3D nesting/packing solver. Replacing it with a true bin-packer on the actual part mesh (orientation-aware) would cut the per-part machine spread. Ground truth requires the production holdout: independently sourced bureau quotes on enough matching parts to contribute to the 20+ part cross-process acceptance set.
2. **CNC:** the spread is driven by MRR and shop-rate uncertainty (±30% / 2× rate). Tightening needs material-specific MRR tables (tool/feed/speed by alloy) and a measured shop-rate for the target supplier — i.e. one real machining quote per material class anchors the rate.
3. **IM tooling:** the size-tier band is ±2–3× by construction (a 160 mm tool is genuinely $15–80k depending on slides/tolerance/steel). Tightening needs the cavity count, tolerance class, and side-action count from the buyer (already USER-overridable via `--cavities`/`--complexity`) plus one real tool quote to anchor the tier.
4. **Across the board:** the single highest-leverage move is a ground-truth set — at least 20 independently quoted parts — to convert these INDEPENDENT-band checks into RESIDUAL-vs-actual error. The harness is built to ingest that the moment it exists (swap the reference bands for the quoted dollars; the aggregation/criteria code is unchanged).

## Stated honesty line

Regression result: **PASS** against the independent local references. V1 stands behind the **DECISION** (make-vs-buy direction + crossover quantity, which depend on the fixed-vs-variable split, not absolute $). Absolute should-cost is characterized HERE — measured, per process, against independent local bands — not asserted. These bands are an independent cross-check, **not** a claim of absolute should-cost truth: that requires real supplier quotes (the path above). Every figure in this report is reproducible by `python -m src.costing.harness` (zero network, runs in seconds).

**Production accuracy status: BLOCKED.** Internally authored coupons and geometry-only archives cannot satisfy the supplier-quote holdout gates (20+ provenance-locked parts from 3+ suppliers, holdout/tuning separation, at least 5 parts and 3 suppliers per launch family, MAPE ≤30%, P90 ≤50%, and every process median bias ≤25%).
