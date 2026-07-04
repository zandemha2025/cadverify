# CadVerify — Design System Decisions (binding for this project)

## Thesis (PLATFORM-DNA.md is canonical)
CadVerify is a **makeability verification engine**. North star: "Every part arrives with a question: can this be made — on your machines, in materials that survive its world — and what will it really take?" The should-cost card is ONE artifact inside The Verdict, never the destination. Resource cost (hours × your rates, mass × your prices, owned→marginal / not-owned→acquisition) beats market price.

## Register (decided)
**The split is blessed: dark theater outside, light instrument inside.**
- Marketing site: cinematic near-black `#050506`, Helvetica Neue light, mono evidence.
- Product: light editorial `#f6f6f7` bg / `#ffffff` panels / `#17181a` ink.
- Never a third identity. The TSX stubs' "Bold Industrial Confidence" (datum blue / limestone / graph paper) is dead — do not port it.

## Provenance tokens (canonical pair — light / dark)
- MEASURED: `#3b7bb8` / `#6aa5d8`
- SHOP: `#b06a35` / `#c9834f`
- USER: `#7a63c9` / `#a08ad8`
- DEFAULT: `#6b7280` hollow ring (both)
- MODEL (computed from assumptions): `#6b7280` `○ MODEL` — hours are MODEL, never MEASURED
- pass/validated `#1f8a5b` / `#55b880` · conditional `#b07818` / `#d9a856` · fail `#c2453a` / `#c96a5e`
- Encodings: filled dot = grounded; hollow = default. Hatched band = assumption (n=0); solid = measured. Withheld ≠ zero.

## Honesty rules (violations are bugs)
- Never print an accuracy/residual that wasn't measured; validation claims stay schematic until real.
- Fabricated example figures carry `[illustrative]` or ILLUSTRATIVE DATA tags — never ● SHOP chips.
- Unshipped features carry IN DEVELOPMENT chips. No compliance badges before reality (pen test, SOC 2).
- The real fixture (object.stl · $14.14 · drivers 6.39/3.89/3.82/0.04 · band 8.49–19.80 ±40% n=0 · crossover 1,962 · routing cnc_turning 0.80 · DFM 423 faces / 1 sidewall <1.0°) is the only data presented as engine output.
- The walk stops at a failed gate; downstream numbers are never faked.

## File status
- CURRENT: `Product - Verify.dc.html` (product) · `Direction - Cinematic.dc.html` + Method/Platform/Teams/Security/Developers/Company + five `For *` persona pages (site).
- SUPERSEDED (banners applied): `Product - CadVerify App`, `Product - Six Signature Moments`, `New Directions` (1a/1b contain arithmetic errors — never port numbers), `design_handoff_cadverify_site/` (stale; regenerate post-re-thesis).
- REFERENCE-ONLY: `CadVerify - Current App/Homepage` (captures of shipped app), `frontend/src` TSX (keep `glass-box/provenance.tsx` + `confidence.tsx` as reference implementations; rest re-derive).
