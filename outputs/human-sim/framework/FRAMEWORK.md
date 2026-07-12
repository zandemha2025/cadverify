# CadVerify — Human-Simulation E2E Validation Framework

**Standing goal.** This is the operating definition of "done." Not "the code compiles"
and not "unit tests pass" — this framework proves the *product* behaves exactly as a
real user expects, measured across every category, driven by simulated humans on the
real web app, with a repair loop that runs until every measurable category is a real
100/100 or an honestly-labeled external gate.

**Honesty is the first invariant.** A score is only ever posted with real evidence
(a screenshot, a captured value, a measured latency). We never fabricate a 100. A found
bug is a WIN recorded permanently, not something hidden. Fabricated praise is the only
true failure.

---

## The eight phases (how the loop runs)

1. **Understand** — a living behavioral map (`SPEC.md`): every page, flow, button, form,
   modal, API the user touches, role, setting, and *product promise*. Nothing undocumented.
2. **Enumerate flows** — the branching tree per screen: happy path, mistakes, invalid
   input, missing data, permission changes, API failures, interrupt/resume. Behavioral
   coverage, not page coverage.
3. **Personas** — each realistic user (below) runs every applicable flow.
4. **Rubric** — the 12 categories below, each scored 0–100 independently, with evidence.
5. **Human-sim** — agents drive the REAL app (Playwright + vision). They click, type,
   upload, scroll, refresh, go back, switch tabs, paste junk, behave imperfectly. They do
   NOT call internal APIs a human wouldn't. They screenshot and LOOK.
6. **Score** — every run emits a structured scorecard (schema below) into `scorecards/`.
7. **Repair** — any category < 100 → root-cause → fix (gated + re-verified) → re-run the
   affected + dependent + regression flows. Loop until real 100 or honest gate.
8. **Regression expand** — every bug becomes a permanent scenario in `regressions/`. Every
   future run replays the whole registry plus new flows. The benchmark only grows.

---

## Personas (each runs every applicable flow)

- **P1 EPC design engineer** (Aramco/Exxon vendor) — real NIST PMI STEP parts, sour service.
- **P2 Sourcing / procurement lead** — bulk manifest, portfolio triage, make-vs-buy, provenance.
- **P3 Shop owner / in-house mfg** — machine inventory, per-machine makeability, gap analysis.
- **P4 Org admin / IT** — org setup, invites, SSO group→role, SCIM, health, permissions.
- **P5 Skeptical CFO / exec** — glass-box cost + provenance; trusts only what shows its work.
- **State personas** — brand-new (empty workspace), returning, power user, read-only,
  org-owner vs member (permission isolation), large workspace, slow network, desktop.

---

## The 12 scoring categories (0–100 each, evidence required)

| # | Category | The question | Evidence |
|---|---|---|---|
| 1 | **Functional correctness** | Did every action produce the expected outcome; did state update right? | screenshot of before/after state |
| 2 | **Data fidelity** | Is every displayed value correct, lineage/provenance preserved, math accurate, permissions respected? | value vs source, provenance chip |
| 3 | **AI fidelity** | Right question answered, reasoning correct, uncertainty & citations honest, no hallucination, nothing omitted? | the answer + its cited basis |
| 4 | **Interaction fidelity** | Buttons/forms/search/sort/upload/keyboard/nav behave as a user expects? | interaction capture |
| 5 | **Visual fidelity** | No overlap, clipping, broken layout, missing icons, bad contrast, responsive breaks? | screenshot judged by vision |
| 6 | **Performance** | page load, interaction latency, parse/search/API latency, animation smoothness | measured ms, not asserted |
| 7 | **Reliability** | repeat N× → same result; no flakiness, no race, no intermittent failure | N-run consistency log |
| 8 | **Conversational quality** | (where chat/AI exists) intent, context retention, caveats, recovery | transcript |
| 9 | **Error recovery** | network loss, timeout, expired session, bad auth, corrupted/large/malformed upload, refresh, back button, multi-tab, dup submit → graceful | failure-injection capture |
| 10 | **Security** | permission enforcement, role/data isolation, cross-tenant, auth/authz/session | denied-when-should-be probe |
| 11 | **Accessibility** | keyboard reachable, focus visible, contrast, semantic structure | a11y check + screenshot |
| 12 | **Regression** | every historical scenario in `regressions/` still passes | registry replay result |

**Category score rule:** 100 only when every flow×persona in that category passes with
evidence. Any confirmed defect caps the category below 100 until fixed. **Overall score =
the minimum across categories** (a product is only as trustworthy as its weakest gate) —
reported alongside the per-category vector, never as a flattering average.

---

## Structured evidence schema (every finding)

```
{ persona, flow, branch, category,
  observed,            // what actually happened (with screenshot path)
  expected,            // what a real user expects
  evidence,            // screenshot(s) / captured value / measured ms
  failure_reason,      // root cause once known
  severity,            // blocker | major | minor | polish
  confidence,          // how sure we are it's real
  recommended_fix,     // concrete next action
  status }             // open | fixed | honest-gate
```

Scorecards are written to `scorecards/<date>-<scope>.md` (human-readable) with the raw
finding objects. Screenshots live beside them — they are the evidence, not decoration.

---

## Two buckets — so "gate" can never hide "broken"

The score is reported in TWO separate ledgers. This exists so an external-systems
excuse can never be smuggled in front of a product that doesn't work.

### Bucket A — PRODUCT (must work; target a real 100; NO gate allowed)
All 12 categories above. This is: does the product do what it promises for a user —
render, DFM, cost, provenance, environment gate, assembly, identity, auth, permissions,
the UI. Every point needs in-container evidence (a screenshot / a value / a measured ms).
**If anything about the product working scores < 100, it is a bug to fix — never a gate.**
Overall Product score = the MINIMUM across the 12 categories. No averaging, no rounding up.
If something that is really "the product is broken" ever appears in Bucket B, that is
cheating and must be called out.

### Bucket B — ENTERPRISE ATTESTATIONS (separate ledger; honestly gated; does NOT touch the Product score)
A short, explicit list of things that genuinely require real third-party systems this
container cannot contain. They are NOT part of the 12-category Product score — a user gets
full product value without any of them. Each is labeled: in-container conformance proven +
the exact external input needed to close it. Never rounded to 100.
- **Live SSO/SCIM cert** vs a real Okta/Entra/Ping *tenant* (in-container proves RFC
  conformance vs a mock IdP, not a live tenant sign-off).
- **Live enterprise systems**: SAP S/4HANA, Windchill/Teamcenter *tenants*.
- **Security posture**: SOC 2, independent penetration test. (Note: in-container
  authz / cross-tenant isolation IS product and lives in Bucket A — it must be 100.)
- **AI / data accuracy vs real ground truth**: the cost/routing accuracy harness is
  leakage-safe but reads `validated=false` until fed real customer quotes/labels. This is a
  limit on *certainty*, not a license to ship a broken answer — the product already discloses
  it (provenance + error bands). Reported as "method proven, number gated," never as "works".

---

## Registry (Phase 8)

`regressions/REGISTRY.md` — every confirmed bug, permanently: id, discovery date, persona,
flow, repro steps, expected, actual, the fixing commit, and the replay assertion. Prior
finds already logged as scenarios: periodic-surface STEP parse, mesher rung-0 grind >60s,
preview-mesh 504 cold, material-blind best_process, COTS engine-only (unrendered),
fab fastener mis-model, ≈M16-bolt-into-≈M12-nut mate incoherence. Each future run replays
all of them.
