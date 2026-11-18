# For review by a practicing fabrication estimator

**Status: UNREVIEWED BY A PRACTITIONER.** The weldment payload carries
`review: unreviewed_by_practitioner` until this review lands and objections
are incorporated. Review time: ~15 minutes.

## What we built

Weldment dollars for an uploaded frame (the geometry layer already
recognizes stock profiles, cut lists, and a weld-length estimate from
contact-patch outlines). The price is: member stock at list $/kg + plate
blanks on the sheet route + member saw cutting + weld deposition +
handling/setup, with the house learning curve on touch labor and a wide
±60% assumption band that is labeled **assumption-based, not yet
validated** in every response. The only remaining not-priced line is
finishing.

## Fillet sizing — CITED, please check the application

AWS D1.1 **Table 5.7** (2025: Table 7.7) minimum leg by the **thicker**
member: 3/5/6/8/10/13 mm at ≤6/6–12/12–20/20–38/38–63/>63 mm. We size the
whole frame's fillets off the file's **thickest member** (conservative for
mixed frames — every joint gets the biggest leg). Weld metal = length ×
leg²/2 × 7850 kg/m³.

**Is file-max thickness the right conservative choice, or is per-joint
sizing worth the complexity before this goes further?**

## The uncalibrated rates (every one overridable; quotes tighten them)

| Rate | Default | Where it sits |
|---|---|---|
| Deposition | 1.8 kg/arc·h (4 lb/h) | low end of published 4–8.5 lb/h GMAW |
| Operator factor | 0.35 | published 30–40% semi-auto |
| Weld station | $85/h | published calculator example |
| Consumables | $6/kg | wire+gas order-of-magnitude |
| Saw | 1935 mm²/min (3 in²/min) | LENOX A36 structural family |
| Setup / handling / min | 0.75 h / 0.05 h·member / $75 | shop-specific |

**Which of these defaults is most wrong for a typical structural fab job,
and what would you use?** (A governed rate card can carry your shop's row
tomorrow; the model reads overrides.)

## What we know we don't know

- Weld length is a contact-patch outline estimate — "as if welded all
  round". On a 40×40×3 tube frame we measure 560–680 mm across 4 joints.
  **How far off is that on real frames, and does it overcount?**
- Edge prep is folded into the weld joint factor, not priced separately.
- Our ±60% band is the house's widest stated tier. **Is that wide enough
  to be honest for a first cut, or should weldment v1 be wider still?**

## Worked sample (hand-check against your numbers)

600×400 frame, 4 members of 40×40×3 tube (blade sweeps 480 mm² each),
material $42, 640 mm of 3 mm fillet:
weld metal 0.0226 kg → arc 0.0125 h → clock 0.0358 h (÷0.35) → labor
**$3.05** + consumables $0.14; cutting 1920 mm² ÷ 1935 ≈ 1 min → **$1.41**;
handling 4 × 0.05 h = 0.2 h → $17.00; setup 0.75 h → $63.75. One-off ≈
**$127** against ~$42 of steel, floored at $75.

**Does the SHAPE of this breakdown match how your shop quotes a frame —
not the absolute dollars, the structure?**

*Reply inline here or annotate `backend/src/costing/weldment.py`;
objections become test cases. Vendor quotes on weldment share links land as
ground truth (process `weldment_fab`) and are the intended tightener.*
