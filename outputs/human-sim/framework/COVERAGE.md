# CadVerify — Honest Coverage & Partials Ledger

Two things this file makes visible instead of hand-waved: (A) how much of the product
has actually been HUMAN-DRIVEN e2e vs merely mapped, and (B) every part of the product
that is partial / deferred / gated. Updated as coverage grows. No inflation.

---

## A. E2E coverage — DRIVEN (with screenshot evidence) vs MAPPED

The framework maps ~115 routes / 48 screens / **12 workflows**. Actual human-driven
coverage as of the 2026-07-09 baseline + 2026-07-10 re-score:

| Workflow | Driven? | Evidence |
|---|---|---|
| W1 Verify → cost hero loop | **deep** | baseline + rescore shots |
| W2 Environment survival gate (sour/H₂S) | **deep** | before/after material strikes |
| W3 Assembly per-part in context (AS1) | **deep** | 18 parts, bolt/nut ≈M12 |
| W11 Part identity (onboard→match→confirm) | **deep** | rescore identity card |
| W12 Auth (signup/login) | **deep** | signup 200 + landing |
| W4 Bulk manifest → triage at scale | **not driven** | — |
| W5 Machines → per-machine makeability + gap | **not driven** | — |
| W6 Portfolio exposure / sourcing triage | **not driven** | — |
| W7 Ground-truth flywheel / calibration | **not driven** | — |
| W8 Save / export / share / PDF | **not driven** | — |
| W9 RFQ supplier package | **not driven** | — |
| W10 Org → invite → SSO/SCIM admin | **not driven** | — |

**Workflow coverage: 5/12 deep-driven (~42%). 7/12 mapped but not yet driven.**

**Category coverage (Bucket A):** Functional / Data / AI / Interaction / Visual /
Performance / Reliability / Regression — scored on the driven flows. **Security,
Error-recovery, Accessibility — PARTIAL** (spot-checks only; need dedicated runs:
failure-injection, multi-user cross-tenant + non-admin, full a11y audit).
Conversational — N/A (no chat surface exercised).

**Persona coverage:** one design-engineer/exec (P1/P5) blend on a fresh empty org.
**Not driven:** read-only user, org admin/owner vs member (permission isolation live),
returning/power user, empty-vs-million-record workspace, slow-network, mobile.

**Honest bottom line:** the baseline score is over the CORE SLICE, not the whole
product. Genuine e2e, not yet exhaustive. Reaching the /goal = the full matrix
(12 workflows × personas × 12 categories) systematically driven — many more runs.

---

## B. Product partials / deferred / gated (what's not-yet-whole)

### Being built now
- **BOM hierarchy** (handle → door → car from customer data): persist the assembly
  tree, resolve part ancestry, feed real annual volume into cost/crossover. *In progress.*

### Real product gaps (fixable — on the list, not gated)
- **Material is never read from the CAD file** — always declared or a DEFAULT
  (cheapest-in-class). The single biggest labeling gap; AP242 material extraction would
  shrink it.
- **Feature detection missing:** threads, pockets, fillets, chamfers, ribs are not
  detected (enum values, no detector). "No threads" means *not looked for*.
- **Fastener geometry-only COTS path** was effectively dead (recognition is name-driven);
  Layer-A across-flats ID now covers hex hardware, but unnamed threaded parts can be missed.
- **Routing thresholds** are hand-tuned; a flat prismatic bar over-selects CNC 5-axis
  (finding #40, deferred) — no "long bar → saw/turn" archetype yet.
- **Environment auto-derivation** from a part's assembly position is deferred (service
  world is user-declared only).
- **ManifestPart name-only retrieval fusion** deferred (feeder §2) — declared parts with
  no geometry aren't yet matched by name in retrieval.
- **DFM heuristics** (thin-wall ray-cast, single-direction undercut, edge-length "small
  features") are directional proxies, not exact — can misfire.

### Honestly gated (need real external systems — Bucket B, never faked)
- **Accuracy vs real ground truth**: harness is leakage-safe but `validated=false` until
  fed real customer quotes/labels. A limit on certainty, disclosed in-product.
- **Native CAD** (.SLDASM/.prt/.CATPart) + **mates/GD&T/PMI** + **AP242 tolerance stack**:
  need a licensed reader / heavier kernel — labeled gated tier.
- **Live SSO/SCIM cert** vs a real Okta/Entra tenant; **live SAP/Windchill** tenant;
  **SOC 2 / pen-test**: external sign-offs, not container-provable.
- **Full-vehicle single STEP**: exceeds the assembly size caps (parts/faces) — honest limit.
