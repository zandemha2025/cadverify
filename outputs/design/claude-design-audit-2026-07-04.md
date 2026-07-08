# Claude Design — full-coverage audit (2026-07-04)

**Scope:** every file in the Claude Design project "Custom Enterprise Product Design" — 15 design files, the handoff bundle, and the TSX implementation stubs. **Method:** orchestrator line-audits (Product - Verify, Method, Platform, Company, Developers, Security, homepage) + six parallel adversarial auditors, all judged against `PLATFORM-DNA.md` and `DESIGN-MISSION.md` (binding). **For the design session: treat this file as the work queue.**

## Verdict map

| File | Thesis | Verdict |
|---|---|---|
| Product - Verify.dc.html | **new-verification** | **needs-work** (best file; punch list §4) |
| Direction - Cinematic.dc.html (homepage) | old-should-cost | re-thesis |
| Method.dc.html | old-should-cost | re-thesis (in place — keep the walk) |
| Platform.dc.html | **mixed — migration already begun** | needs-work (reconcile old spine) |
| Company.dc.html | old-should-cost | re-thesis |
| Developers.dc.html | old-should-cost | re-thesis + fix API shape |
| Security.dc.html | old-should-cost | re-thesis + fix pen-test claim |
| Teams.dc.html | old-should-cost | re-thesis (it's personas, not teams) |
| For Cost Engineering.dc.html | old-should-cost | re-thesis |
| For Design Engineering.dc.html | mixed | re-thesis (body is close) |
| For Shop Owners.dc.html | old-should-cost | re-thesis (blocker: quote-price spine) |
| For Sourcing.dc.html | old-should-cost | re-thesis (blocker: killed RFQ frame) |
| New Directions.dc.html | old-should-cost | **superseded-archive** |
| Product - Six Signature Moments.dc.html | old-should-cost | **superseded-archive** (salvage §6) |
| Product - CadVerify App.dc.html (dark) | old-should-cost | **superseded-archive** (salvage §6) |
| CadVerify - Current App / Current Homepage | old (captures) | reference-only — label as such |
| design_handoff_cadverify_site/* | old (stale snapshot) | **superseded-archive** (Platform diverged) |
| frontend/src TSX stubs | mixed | see §7 (2 keep-as-is, rest re-point/discard) |

## 1. The five headline findings

1. **Site vs product thesis split.** The product (Verify) speaks the verification thesis; the site still sells should-cost end to end ("Every part knows what it should cost", footer "should-cost, made of glass", SHOULD-COST climax cards). Platform.dc.html has ALREADY begun migrating (footer now "verification, made of glass", a Your-Machines/Environment-Gate/Triage moats band) — finish the job everywhere; a half-migrated canonical set is worse than either whole.
2. **The DNA's three structural pillars are absent from every old-thesis surface:** machine inventory ("can YOU make it — on your Machine X"), the environment gate (materials struck with NACE/HDT reasons), triage at scale. They exist only in Product - Verify and Platform's new moats band.
3. **The missing persona is the primary buyer.** Cost Eng / Design Eng / Shop Owners / Sourcing exist; the in-house manufacturing / MRO operator ("can WE make it on OUR machines") has no page — and Sourcing is built on the explicitly-killed RFQ/negotiation frame.
4. **Honesty bugs in a product whose promise is honesty** (full list §3) — worst: the homepage crossover dial claims "same curves the engine computed" over hardcoded constants; Security claims an annual pen test that has never happened; New Directions prints derivations that don't arithmetic (0.082 × $52 ≠ $6.39); Six Moments shows Σ-reconciles-✓ over numbers that don't sum ($1.56+$0.92+$5.41 ≠ $8.01); fabricated marketing numbers wear ● SHOP provenance chips.
5. **A third design identity is loose in the TSX stubs** ("Bold Industrial Confidence" — datum blue, warm limestone, graph-paper/drafting material metaphors) matching neither the dark site nor the light product, plus the handoff README mandates fidelity-locking to the superseded thesis. Kill the third identity; declare the register decision (see §5).

## 2. Site re-thesis work list (per page)

- **Homepage:** hero → the north-star question ("Every part arrives with a question…"); climax → THE VERDICT (should-cost card demoted inside it); add machines/environment/triage beats; fix the dial honesty bug (either drive it from captured engine curve data and say so, or label it schematic); drop the MEASURED chip from decorative HUD dims.
- **Method:** keep the five-stage walk, Σ-assembly, honesty rail, and the "±40%?" objection section verbatim — re-frame stages to the question hierarchy (envelope → environment materials → physics → time/resources → resource cost); fix stage-2's "before a dollar is computed" framing; footer tagline.
- **Platform:** reconcile — the new moats band is the seed; rewrite the seven old capabilities under it; apply ILLUSTRATIVE tags to the moats sample numbers (portfolio table has them, moats band doesn't).
- **Company:** mission re-led with verification; pilot Week 1 adds "bring your machine list", Week 3 validates HOURS (machine-time accuracy) not just paid prices.
- **Developers:** show the REAL API split (/validate vs /validate/cost — "nothing withheld from the API" requires the endpoint shown to be real); the response fields (drivers/provenance/validated/n_samples) are correct — keep.
- **Security:** remove "Pen test — annual, summary shareable" (none exists — state it like SOC 2: planned, no early badge); verify "SOC 2 in progress" is factually true; the zero-egress claims are real (verified in backend) — keep.
- **Teams:** either make it actually Teams (roles, shared records, governed libraries with propose→review→approve — real shipped backend now) or rename to "Who it's for"; add the operator persona; keep the "four lenses on one truth" structure.
- **For Cost Engineering:** climax must become the Verdict; introduce resource cost (marginal-vs-acquire — this persona is where it belongs); remove ● SHOP chips from invented figures; soften present-tense holdout-accuracy claims.
- **For Design Engineering:** closest to salvage — body is makeability; hero ("Cost is a dimension. Design to it.") must become the verdict-while-you-design; ADD the environment gate (a design engineer choosing materials is its exact audience); label illustrative engine outputs.
- **For Shop Owners:** re-spine from "quote every RFQ" (price = red-headed stepchild) to the shop's native verification story: their machines ARE the inventory; envelope-fit + marginal cost on their floor; keep the chuck/3-jaw choreography and "It's an afternoon, not an implementation."
- **For Sourcing:** rebuild off the killed RFQ frame → the sourcing-native verdict: make in-house / make outside / acquire; keep "banded-not-fake-exact" and the three-quote-ghosts visual.
- **NEW PAGE — For Manufacturing/Operations (the operator):** the Aramco story — declare your floor once, triage a legacy catalog at scale, resource cost on owned equipment, capability-investment ranking.

## 3. Honesty bugs (fix in ANY file that survives)

1. Homepage dial: "Same curves the engine computed" over hardcoded analytic constants → drive from real captured curves or label schematic. **This is the page's central proof.**
2. Security: fabricated pen-test badge. Company/homepage/Current-Homepage: verify ITAR/AS9100-path phrasing against reality before shipping.
3. New Directions 1a/1b: derivations that don't compute (labor 0.082×52≠6.39; machine math off) inside artifacts promising traceability.
4. Six Moments 1a: Σ green-✓ over non-summing drivers ($8.01 vs 7.89).
5. ● SHOP provenance chips on invented marketing figures (Cost Eng, Shop Owners, dark App) → ILLUSTRATIVE label or hollow chip; Sourcing does this correctly — copy its pattern.
6. Shop Owners: engine-uncomputable lead-time claim presented as output.
7. decision-plate.tsx: caption "real cost-truth-engine output" over a typed fixture; always-hatched band with no validated branch (honesty as decoration).
8. Teams: "product ships with role lenses" — verify or soften.
9. Verify product: step-4 "every figure above is MEASURED or SHOP" contradicts its own ±40% assumption band; queue-based lead time needs a source chip.

## 4. Product punch list (Product - Verify.dc.html — the file to build on)

Missing moments: (1) the NEGATIVE verdict + the UNKNOWN/no-inventory verdict (all current variants are "makeable"); (2) org-level empty states (machines/records/triage zero-states as designed first-run moments); (3) the Hallmark as a ceremony, not a demo toggle; (4) provenance disclosure surface (tap number → derivation); (5) the context zoom-out on the hero stage + lineage strip on Verify; (6) the crossover scrub + quantity/annual-volume input (inherit from program); (7) triage drill-down + capability-investment ranking ("which ONE machine acquisition unlocks the most parts"); (8) ask-the-engine ANSWER state + honest refusal; (9) record detail + read-only shared view; (10) machine CRUD + CSV import; (11) one governed-change frame (propose→review→approve — backend exists); (12) acquire-capability destination (capex-vs-marginal breakeven, parts unlocked).
Missing screens vs DESIGN-MISSION inventory: (13) sign-in/first-run; (14) catalog explorer (iso hero thumbnails, facets, saved views — Records table ≠ catalog); (15) compare; (16) part detail (a part's standing page: history of verifications + decisions); (+ org settings members/roles/webhooks).

## 5. The register decision (founder call — then enforce everywhere)

Site = cinematic near-black (#050506); product = light editorial (#f6f6f7); TSX stubs = a third identity. Either bless **dark theater outside / light instrument inside** and codify it in PLATFORM-DNA, or re-render the site light. Then: unify provenance color tokens (MEASURED #6aa5d8 vs #3b7bb8; SHOP #c9834f vs #b06a35 drift), and kill the third identity in globals.css.

## 6. Salvage index (port before archiving)

From **dark Product - CadVerify App**: X-ray toggle revealing the actual DFM-flagged faces; the 3-state context module with seat-on-stage zoom-out (this IS product punch item 5); ask-the-engine chat with "ENGINE OUTPUT — COMPUTED, NOT GENERATED" bubble (punch item 8); live iso thumbnails in every list; "withheld ≠ zero".
From **Six Signature Moments**: the honest-states quartet (crown jewel); the 3-state context module; rail/stage/inspector with in-canvas rendered thumbnails; the CUI shell. (Fix its Σ bug wherever ported.)
From **New Directions**: 1b's live compute-trace reveal (staggered engine-op lines) — promote into the Verdict walk; 1c's band-as-dimension-line device; the honesty-band copy. Archive the rest (1a is the assay/wax-seal hard-NO; 1b's skin is graphite+phosphor hard-NO).
From **Current App/Homepage captures**: the shipped anatomy + honesty labeling as ground truth; the black-box→glass-box clip-away mechanic; "We won't quote an accuracy we haven't earned."
From the **site**: Σ scroll-assembly; "±40%?" objection section; pilot-as-measurement; security beam + "what we don't do"; the recurring real part (object.stl · $14.14) device; IN DEVELOPMENT chips.

## 7. TSX stubs disposition

- `glass-box/provenance.tsx` + `glass-box/confidence.tsx`: **keep-as-is** — reference implementations (real prop-driven fill-vs-hollow and hatched-vs-solid; refuses fabricated accuracy). Re-point confidence at resource cost when wiring.
- `decision-plate.tsx`: needs-work (honesty bugs §3.7; the plate is the demoted should-cost card — re-derive as the Verdict plate).
- `app-shell.tsx`: non-compiling (imports 3 nonexistent components); old IA (/analyze, /cost). Reference-only.
- `globals.css` + `page.tsx`: the third identity + old hero. Re-thesis; keep the .cv-hatch token, the two-number-voice idea, the runtime theming architecture.
- The handoff bundle (`design_handoff_cadverify_site/`): **stale frozen export** (its Platform predates the live one; Method is byte-identical). Top-level files are canonical. Archive the bundle; regenerate handoffs only after re-thesis. Its README's honesty rules (schematic validation, ILLUSTRATIVE/IN-DEVELOPMENT labels) are worth carrying into the new README.

## 8. Already right — do not regress

The light Verify file's interactive verdict (environment chips genuinely recompute materials/verdict with NACE/HDT reasons); hatched n=0 bands everywhere; withheld-not-extrapolated; "the gaps are governance, not shame"; visible-DEFAULT rate chips; the one-real-part device; the honesty vocabulary (it is thesis-agnostic and transfers unchanged).
