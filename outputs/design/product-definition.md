# CadVerify — Product Definition (D1)

**Status:** Approved by founder 2026-07-02 (via the reset plan). This is the tiebreak document — every design and build decision defers to it. Supersedes all prior design-direction docs.

## The sentence

CadVerify is a deterministic manufacturing-decision engine that inspects any part, tells you what's wrong with it and what it should cost — with every finding pinned to the exact geometry and every dollar pinned to its source — from one part to a million.

## The personas (three, co-equal at the front door)

1. **Design/mfg engineer** (Zoox-style) — has a part, needs the inspection + make/buy answer in minutes. Door: part-first drop.
2. **Cost/sourcing engineer** — lives in drivers, rates, calibration, negotiations. Door: the catalog grid.
3. **Portfolio/MRO owner** (Aramco-style) — millions of parts; triage, risk, savings pipeline. Door: exception-first queue.

Co-equal in **entry** (three real doors, three hero objects, three first verbs). Sequenced in **depth** by what the backend honestly powers.

## The four workflows of v1

1. **Part → decision → keepable artifact** (full-depth; engine real)
2. **FINDINGS** — on drop, the system surfaces what you missed: vulnerabilities, caveats, issues — each pinpointed to its locus (a face, a driver, an assumption) and its source (a rule, a tag, a threshold). Full-depth; co-equal with cost, never a tab under it.
3. **Portfolio → triage → savings** (findings-triage lit in v1; savings-ranking honest-thin until W3)
4. **Quote → compare → negotiate** (Compare real in v1; RFQ/award honest "coming" states until W2/W5)

## The truths (never violated, in any design)

1. **The part is the evidence.** Findings and costs attach to geometry, not abstract rows.
2. **Everything has a source.** Rules for findings; provenance for dollars. Hollow = admitted guess · hatched = unvalidated · solid/brass = validated by a real quote.
3. **The engine answers without being asked.** Triage precedes conversation at every scale. Asking is optional; being told is default.
4. **Three personas, one spine.** Role lenses over shared objects — never three apps.

## Register

Apple-cinematic: the part as staged hero, orchestrated motion, one light source. Fixed; applied only after structure is approved (D2 gate).

## Standing design-review gates

- A design where findings are reachable only via a tab **fails review**.
- A UI element with no real engine field behind it **fails review** (gaps become scoped backend items, never faked UI).
- Empty zones state honestly what's coming; no stub masquerades as real.
