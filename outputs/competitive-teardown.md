# CadVerify — Brutal Competitive Teardown (final)

*5-agent red-teamed read. Self-audit ran the live product; giants/direct intel sourced + 2026-verified;
red-team passed 0 revisions and reproduced the four worst findings live. No flattery, no pedantry.*

## BOTTOM LINE (up front, brutal)
**The engine is real software. The buyable *product* is a demo.** The wedge is currently a slide, not
software — the one thing that's supposed to be different (per-shop calibration) isn't in the live app at
all. So yes: CadVerify must **look and work like real software before any wedge matters.** The good news
hiding in that: the four most damaging problems are **wiring + hygiene over a genuinely working, honest
engine** — not deep capability gaps. **The one structural bet:** own the *neutral + per-shop-calibrated +
glass-box + zero-egress should-cost-as-a-decision* intersection. Its two unlocks are **data/trust moves,
not code**: validate the number (Zoox real-quote session) and wire calibration into the product.

---

## WHAT THEY'D LAUGH AT (organized by axis; most damaging first)

### Correctness / Trust
1. **The marquee wedge doesn't exist in the live product. [TABLE-STAKES · existential]** The cost API has
   no `shop` param (`routes.py:585-615`); a signed-in buyer sees `Not calibrated — generic defaults`;
   swapping shops just toasts "build gap." The marketing `$14.14 / Midwest Precision CNC` hero is a
   **hardcoded fixture** — the engine returns **$64.63** on a real part. Calibration only works in the
   CLI. *A buyer sees exactly what aPriori/3D Spark already ship — minus their data and customers.*
2. **The router recommends a process its own DFM hard-fails, in the same panel. [TABLE-STAKES]** RoutingCard
   headlines `cnc_turning (rotational, 0.80)` while the DFM matrix directly below flags `cnc_turning: FAIL —
   lacks rotational symmetry`. Two disagreeing definitions of "rotational" (`routing.py` bbox-squareness vs
   `checks.py` inertia-eigenvalue). Systematic on 4/5 printed parts. Same bug *class* as the sheet-metal one
   just fixed — still live for turning. A manufacturing engineer loses trust on the first real part.
3. **"Override → re-runs" is false. [TABLE-STAKES]** The central glass-box interaction (edit an assumption,
   re-cost) only relabels client-side and toasts "Server re-cost is a build gap" (`PartWorkspace.tsx:189-210`).
   The number never moves; "Save as scenario" doesn't persist. The core "make the numbers yours" loop is cosmetic.
4. **Zero validation, not the error band. [DEEPER · needs data not code]** ±40-60% is *category-correct*
   framing (aPriori itself concedes should-cost ±30%, quotes ±40%). The laugh that lands is **n=0** — no
   real part has ever been checked against a real cost. The receipt is the pending Zoox session.

### Credibility / Polish
5. **Hygiene that screams "dev build." [TABLE-STAKES]** Internal tools (`Parts (Label)` corpus annotator,
   `Design system` — its own header calls it "the build proof") ship in the **customer sidebar**. Marketing
   renders **static fixtures captioned "real output, not screenshots"**, and the flagship fixture
   self-contradicts (routing "round metal, rarely powder-bed" vs headline "Make by MJF"). Local-dev, seeded
   login, **no SOC2/ITAR** — while **Zoo shipped public SOC2 Type II + a Trail of Bits review** on the exact
   trust ground CadVerify claims.

### Capability / Depth · UX / Ease
6. The live "re-cost" is 5 coarse dropdowns; `material_class` is a manual input the engine never infers.
   The output can read as a wall of numbers. (Material to ease-of-use, not existential.)

---

## WHAT WOULD MAKE THEM SHIT THEIR PANTS (after killing the copyable ones)

**Killed as NOT moats (honesty both ways):** glass-box *alone* = table-stakes (SOLIDWORKS Costing
half-does it); decision/crossover = copyable-in-a-sprint by aPriori/3D Spark; design-engineer-on-the-web =
structural only vs SolidWorks, **half-stale** vs aPriori **aP Design** + Protolabs **ProDesk**.

**The surviving moat is the INTERSECTION — not any single feature:**
> **A neutral, per-shop-calibrated, glass-box should-cost-as-a-decision that runs with zero egress.**

Hard for *them specifically* because each can hold only one or two corners, and the combination
contradicts their business model:
- **Marketplaces (Xometry/Protolabs/Fictiv) are economically *barred* from a neutral, no-margin should-cost** — it exposes their markup. Structural.
- **aPriori** owns the cost-data moat but is cost-engineer-shaped + heavyweight; a tool that takes *your* shop rates (not their library) is a posture they won't cannibalize toward.
- **Zoo.dev** has the distribution + engine + the *transparency* credential — but **zero should-cost / quoting / DFM-rules / calibration today.** The threat is their roadmap, not their product. The clock is real.
- **Zero-egress / CAD-never-leaves** is a genuine wedge for ITAR / aerospace / Aramco where cloud cost tools and marketplaces structurally can't go.

---

## THE FIX LIST (what "real software first" actually means)
The four most damaging items are wiring/hygiene over a working engine:
1. Wire per-shop calibration into the API + UI (the differentiator must be *in the product*).
2. Reconcile routing ↔ DFM (one definition of "rotational"); never headline a process DFM fails.
3. Make override actually re-cost server-side (the glass-box loop must be real).
4. Hygiene: remove dev tools from the customer nav; make marketing run the real engine; ship the trust story (path to SOC2).
Then the two non-code unlocks: **validate the number (Zoox)** and **earn the trust credential**.

*Sources: outputs/self-audit.md, giants.md, direct-competitors.md, read-draft.md, red-team.md.*
