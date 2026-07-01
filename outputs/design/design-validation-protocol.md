# CadVerify — Design Validation Protocol (real users)

**Role:** Validation-Auditor. **Date:** 2026-06-29.
**Purpose:** how to validate the *design* with real users — the **Zoox Head of Manufacturing** plus
**one user per segment** — before GA. This tests whether the thesis actually lands: *can they reach a
decision, do they trust the numbers, does each role find its view, does the glass box read as the
hero?* It is the design counterpart to the engine-side
[`zoox-calibration-protocol.md`](../zoox-calibration-protocol.md) (which measures the first real
accuracy number). **Run the calibration session and this design session in the same visit** — the
calibrated output is also the most persuasive thing to put in front of the design test.

> The sentence the *design* is trying to earn the right to hear, unprompted, from the buyer:
> *"I can see exactly how this number was built, I'd trust it in a design review, and I know which
> view is mine."*

---

## 0. Pre-flight — do NOT skip (the live-API caveat from the critique)

The live `/cost` upload flow currently runs against a **stale API process** that omits
`routing` / per-estimate `confidence` / shop `calibration` (see `design-critique.md` §"live-API
caveat"). If a buyer judges the glass box on that, **routing reasoning, the confidence band, and the
SHOP tags are missing** — the hero is accidentally half-buried. Two ways to prevent it, do at least one:

- [ ] **Refresh the API** so `POST /api/v1/validate/cost(/demo)` serves `routing` + `confidence`
      (+ a `shop` param for calibration). Then the live upload shows the full glass box. *(Build harness.)*
- [ ] **Drive the test off the fixture-backed full experience** — the `/design-system` showcase and the
      `/` + `/method` marketing pages render the *complete* engine output (routing, confidence,
      calibration, the shop A/B) today, green build. Use these as the "this is the product" surfaces and
      the live upload only to prove "it's real / your CAD never leaves the box".

Other pre-flight:
- [ ] `cd frontend && npm run build` → exit 0 (verified 2026-06-29: 16/16 pages).
- [ ] Engine smoke: CLI on `object.stl --qty 10,1000 --shop "Midwest Precision CNC"` returns routing +
      confidence + crossover (verified this session).
- [ ] Stage **the participant's own part** if they'll bring one (most persuasive); otherwise use
      `object.stl` (the part every fixture is built on) so the numbers on screen match the demo.
- [ ] Have **light and dark** ready (toggle in the showcase) — the buyer's environment may be either.
- [ ] Recording/notes template (§5) open; one facilitator + one silent note-taker.
- [ ] Decide **mode**: in-person preferred for the Zoox session (ITAR/CAD-as-IP — local, zero egress is
      part of the pitch); screen-share acceptable for the per-segment users.

---

## 1. Who to test, and why each

**The anchor: Zoox Head of Manufacturing (automotive/AV).** The economic buyer. He validates the whole
thesis at once — make-vs-buy decision, trust in the numbers, IP-stays-local posture. Pair his design
session with his calibration session so he sees the glass box *on his own parts and rates*.

**One user per segment** (the five lenses each need a real occupant):

| Segment | Recruit (1) | The view it must validate | The job to watch them do |
|---|---|---|---|
| **Design engineer** | A mechanical/design eng who iterates geometry | Decision lens + quantity slider | Drop a part → read the make-vs-buy answer → drag quantity → see the process flip at the crossover |
| **Cost / value engineer** | A should-cost / DTC engineer (aPriori-literate ideal) | Glass Box lens | Open a driver → read its source → **override an assumption** → expect a re-cost |
| **Sourcing / procurement** | A buyer who runs RFQs | Compare lens | Read the process × shop board → find the rate driving the gap → name the negotiation lever |
| **Manufacturing engineer** | A process/DFM engineer | Routing & DFM lens | Read the routing reasoning → click a DFM blocker → see the faces light up on the part |
| **Buyer / approver (exec)** | The Zoox HoM himself, or a peer | Decision + "Why trust this" | Reach an approve/don't-approve stance and say what made it trustworthy |

Recruit for **domain reality over polish tolerance** — these are skeptical aerospace/automotive buyers;
their default is distrust, which is exactly what the glass box must overcome.

---

## 2. Format (≈45–60 min each, task-based, think-aloud)

Task-based usability test with concurrent think-aloud. **No leading.** Never say "glass box",
"provenance", or "confidence" first — see if *they* reach for the receipts. Sequence per participant:

1. **Cold open (2 min).** One sentence: *"This estimates what a CAD part should cost to manufacture and
   helps decide how to make it. Think aloud."* Show the surface for their segment. **Don't explain the
   UI.**
2. **First-impression (3 min).** "What is this telling you? Would you trust this number? Why / why not?"
   → captures the trust reflex *before* they're taught the glass box.
3. **Segment tasks (20–25 min).** The role's job from §1, plus the two universal tasks in §3.
4. **Cross-role probe (5 min).** Switch the Role Lens to a *different* role. "If you handed this to
   <that role>, would they get what they need? Is anything you need now missing?" → tests "serves
   opposing roles without drowning anyone."
5. **Trust interrogation (8 min).** §4 — push hard on the honesty rail and the incumbents.
6. **Wrap (5 min).** Single hardest question: *"Would you put a PO behind this, or what's missing
   before you would?"* + the one-word brand read.

---

## 3. The two universal tasks (every participant, regardless of role)

These test the two load-bearing thesis claims directly.

**Task A — Reach a decision and defend it.**
> "At 50 units, how should this part be made, and what would it cost? Now at 5,000 units. When does that
> change?"
- **Pass:** reaches "make by MJF now, tool up above ~1,962" by reading the headline + dragging the
  quantity slider; states the cost **as a band**, not a point.
- **Watch for:** Do they trust the slider's live flip? Do they treat `$14.14` as exact (bad — the band
  isn't landing) or as "~$14, ±40%" (good)?

**Task B — Open the box on one number.**
> "You don't believe the $14.14. Convince yourself — or catch us being wrong."
- **Pass:** without prompting, clicks a driver → reads the `source` string → notices the `Σ = unit cost`
  check → spots a **hollow `DEFAULT`** dot and says "that one's a guess." That sentence = the thesis
  landing.
- **Watch for:** Do they understand fill vs hollow without being told? Do they find the
  hatched-vs-solid confidence meaningful? Do they try to **edit** a number (cost/value eng especially)?

---

## 4. Trust interrogation — the honesty rail (the moat, push hard)

The differentiator is *honesty under pressure*. Probe it adversarially:

- **The accuracy trap.** *"How accurate is this — what's your error rate?"*
  **Correct product behavior:** it says **"assumption-based, not yet validated"** and explains the band
  flips solid only on *their* held-out real parts. **Red flag if the participant comes away believing we
  claimed a measured accuracy** — that means the honest framing read as a hedge, or (worse) a surface
  implied a number. Capture verbatim.
- **The incumbent frame.** *"aPriori already gives me a should-cost. Xometry gives me a price in
  seconds. Why this?"* Watch whether the **black-box-vs-glass-box** hero and the differentiation table
  give them the wedge in their *own* words ("I can see the drivers / I can edit it / it tells me the
  decision, not just a price").
- **The IP question (Zoox-critical).** *"Where does my CAD go?"* The "parsed in-process and discarded,
  zero egress on the local path" + ITAR/AS9100-path framing must land as **credible and specific**, not
  marketing. If it reads as a claim they'd need legal to verify, note it.
- **The redesign honesty.** On the molding crossover: does the **"if redesigned, not a current quote"**
  banner read as *trustworthy candor* (good) or *a dodge* (bad)? This is a direct test of "never assert
  a process the part currently fails."
- **The DEFAULT gaps.** *"Where is this still guessing?"* Can they find the hollow `DEFAULT` rows? The
  thesis is that **showing the gaps builds more trust than hiding them** — verify that reflex directly.

---

## 5. What to capture (scorecard — one row per participant)

| Dimension | Signal of PASS | Capture |
|---|---|---|
| **Reaches a decision** | States make-now + crossover + banded cost unaided (Task A) | time-to-decision; did they trust the slider flip? |
| **Trusts the number** | Trust *rises* after opening the box; treats cost as a band | first-impression trust (1–5) → post-glass-box trust (1–5) |
| **Glass box reads as hero** | Opens a driver / reads a source / names a DEFAULT **unprompted** (Task B) | did they self-discover it, or need a nudge? |
| **Provenance legible** | Understands fill=grounded / hollow=guess without being told | yes/no + quote |
| **Confidence honest, not weak** | "Not yet validated" reads as integrity, not a dodge | quote; did anyone hear a fabricated accuracy? (must be **no**) |
| **Role view fits** | "This is the view I'd live in" for their lens | yes/no + what they'd add/remove |
| **Doesn't drown them** | The other roles' depth doesn't bury *their* job | density complaints, if any |
| **Beats the incumbent frame** | Articulates the wedge in their own words | the sentence they used |
| **Not flashy / appropriate** | Reads as "serious instrument", not consumer app | one-word brand read |
| **Would act** | Would pilot / put a PO behind it, or names the blocker | the blocker |

**Headline metrics across the cohort:**
- **Decision reach rate** — % who complete Task A unaided. *Target: 5/6.*
- **Glass-box self-discovery rate** — % who open the box in Task B **without** a nudge. *Target: ≥4/6;
  this is the single most important number — it tells you the hero is actually the hero.*
- **Trust delta** — mean(post) − mean(first-impression). *Target: positive; the box should* increase
  *trust, not just satisfy curiosity.*
- **Fabricated-accuracy incidents** — count of participants who left believing we claimed a measured
  accuracy. *Target: 0. Any > 0 is a release blocker* (it means the honesty rail mis-fired).
- **Role-fit** — each of the five lenses gets ≥1 occupant saying "this is my view." *Target: 5/5.*

---

## 6. Decision gate (what the results mean for ship)

- **GREEN (ship):** decision-reach ≥5/6, glass-box self-discovery ≥4/6, trust delta positive,
  **zero** fabricated-accuracy incidents, all five lenses fit their occupant, and the Zoox HoM would
  pilot. → the thesis is validated on real users.
- **YELLOW (iterate, don't re-architect):** one segment's lens needs work, or self-discovery is 3/6
  (the box is good but not *findable* enough — strengthen the "View glass box" affordance / the drill
  cue), or the differentiation didn't land for one participant. Targeted fixes, re-test that slice.
- **RED (re-open the design):** anyone leaves believing a fabricated accuracy was claimed; or the
  decision is unreachable for most; or trust *drops* after opening the box (the glass box read as
  confusing/overwhelming rather than reassuring); or a whole segment finds no usable view. → back to the
  responsible designer (system / platform / marketing) before GA.

---

## 7. Logistics

- **Order:** run the **Zoox calibration session first** (per `zoox-calibration-protocol.md`) so the
  design session can put his *own* calibrated, validated-on-his-parts output in front of him — the
  strongest possible trust artifact. The same visit then does this design test.
- **Materials per session:** the surface for their segment (live `/cost` *if* the API is refreshed,
  else `/design-system` + `/method`), a part (theirs or `object.stl`), light+dark ready, the §5
  scorecard, recording consent.
- **Per-segment users** can be remote screen-share; **Zoox** in-person (the local/zero-egress story is
  part of what's being tested and is more credible demonstrated on his machine).
- **Synthesize** into a one-page gate result against §6, with verbatim quotes for every RED/YELLOW
  signal and the prioritized fix list routed to the owning design surface.

---

## Appendix — quick reference: what each surface is for in the test

- **`/` (marketing)** — tests the *wedge*: black-box vs glass-box hero, the decision-not-dollar section,
  the honesty rail, the incumbent differentiation table. Use for the trust interrogation (§4).
- **`/method`** — tests whether "shows its work" is believable: the five stages rendered with real
  components. Use when a skeptic asks "but how is the number actually built?"
- **`/cost` / `/analyze` (live product)** — tests the real upload→decision loop and the IP/zero-egress
  story. **Only the full glass-box hero if the API is refreshed** (pre-flight §0).
- **`/design-system`** — the canonical full render of every glass-box component against real engine
  output, light/dark, role-lens live. The reliable fallback that shows routing + confidence + the shop
  A/B **today**, regardless of API state. Use this to demo the complete experience if the live API can't
  be refreshed before the session.
</content>
