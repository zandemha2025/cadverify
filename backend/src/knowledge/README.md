# The CadVerify Knowledge Corpus

The domain knowledge the engine is allowed to know: process physics, design
rules, service environments, audit regimes, CAD practice, and the catalogue of
what good and bad actually look like.

It ships **inside the backend image** (`backend/` is the Docker build context)
so the API can load, cite, and serve it at runtime. It is not documentation
about the product — it is *the product's grounding layer*.

---

## Why this exists

`PLATFORM-DNA.md` commits to a copilot that **structurally cannot hallucinate
numbers**. That commitment is only keepable if every number the engine can say
comes from somewhere inspectable. The analyzers already do this for the numbers
they compute. This corpus does it for the numbers they *assume* — the 45°
overhang limit, the 22 HRC sour-service cap, the 60%-of-nominal rib rule — and
for the qualitative knowledge that has no number at all: what an API 6A auditor
opens first, why a CAD model with 400 rollback errors is a cost signal, what a
good chamfer scheme looks like versus a bad one.

Two consumers:

1. **The engine.** `packs/*.yaml` is machine-readable. Design rules, environment
   constraints, and audit checklists load through `loader.py` and can back DFM
   checks, environment filtering, and verdict narration — each carrying a
   `source_id` that resolves to a real citation.
2. **People.** `library/**/*.md` is the written knowledge — the 101s, the expert
   heuristics, the auditor playbooks. Written for a competent engineer who is
   not a specialist in *this* process, which is exactly the reader the product
   has.

---

## The provenance contract

**Every number in this corpus is `DEFAULT` provenance in the platform's sense.**
Nothing here is MEASURED. Nothing here is SHOP-validated. A number from this
corpus that reaches a user must render as an assumption, with its source, and
must lose to any real measurement.

Within that, sources are tiered by how much authority they carry:

| Tier | Meaning | Example |
|---|---|---|
| `standard` | Published consensus standard, citable to a clause | ASME Y14.5-2018, NACE MR0175/ISO 15156, API 6A |
| `vendor` | A machine or material vendor's published capability | Haas VF-2 envelope, EOS M 290 layer range |
| `handbook` | Established engineering reference; consensus, no clause | Machinery's Handbook, ASM Handbook, NADCA guide |
| `practice` | Widely-taught shop practice with no single authority | "3:1 pocket depth-to-tool-diameter" |
| `contested` | Reputable sources materially disagree | minimum sheet-metal flange: 3×t or 4×t |

`contested` is a first-class tier, not a failure. When the field disagrees, the
corpus records **the range and the disagreement** rather than picking a winner
and pretending. A rule marked `contested` must carry `disagreement:` explaining
who says what. This is the honesty rule applied to knowledge itself.

### Rules for contributors

1. **No orphan numbers.** Every numeric rule carries a `source_id` present in
   `packs/sources.yaml`. The loader fails validation otherwise.
2. **Ranges over false precision.** `0.5–1.0 mm depending on alloy` beats
   `0.7 mm`. Encode `typical`, `min`, `max` — not a single invented figure.
3. **Say the physics.** Every rule has a `why`. A rule you cannot explain is a
   rule you cannot defend to an auditor, and the copilot cannot narrate it.
4. **Never upgrade a tier to sound confident.** A shop rule of thumb is
   `practice`, even when everyone believes it. Promoting `practice` to
   `standard` because it feels solid is the exact failure this corpus exists to
   prevent.
5. **Prefer the constraint that binds.** Where a material limit and a process
   limit collide, record both and say which governs.

---

## Layout

```
knowledge/
  README.md            this contract
  INDEX.md             the full map of what is here
  models.py            typed records (Source, DesignRule, Environment, …)
  loader.py            load + validate + resolve citations; caches in memory
  packs/
    sources.yaml            the citation registry — every source, defined once
    design_rules.yaml       process design rules, numeric, per ProcessType
    environments.yaml       service environments → material/process constraints
    audit_checklists.yaml   what expert auditors actually look for, per regime
    red_flags.yaml          anti-patterns: what bad looks like, and the tell
    glossary.yaml           the vocabulary, defined once
  library/
    foundations/       manufacturing, DFM, GD&T, materials, environments, cost, QA
    processes/         per process family: physics, good, bad, expert heuristics
    cad/               modelling quality, interop, mesh, MBD, PDM, CAD development
    audit/             the auditor playbooks, per industry regime
    exemplars/         good-vs-bad gallery and the red-flag catalogue
```

---

## Using it from the engine

```python
from src.knowledge import load_knowledge

kb = load_knowledge()

# Design rules for a process, each with a resolved Citation
for rule in kb.rules_for("cnc_3axis"):
    print(rule.rule_id, rule.value_typical, rule.citation.standard)

# Environment gate: which materials survive this world?
env = kb.environment("sour_service_nace")
env.max_hardness_hrc                # 22.0
env.requires_flags                  # ("nace_mr0175",)
env.admits_hardness(30.0)           # False — and None when hardness is unknown

# What an auditor will open first
for item in kb.checklist("api_6a_psl3"):
    print(item.trigger, item.evidence_expected)
```

Every returned record carries `.citation`, which is the same
`src.analysis.models.Citation` shape the DFM issues already use — so a knowledge
-backed statement is inspectable in the UI by the exact mechanism that already
exists for analyzer citations.

---

## Current coverage

The corpus is held to **parity**: a user in any industry gets the same depth of
answer, so no process, environment or regime is allowed to be thin.

| Area | Coverage |
|---|---|
| Design rules | 89 rules; **every one of the 21 `ProcessType` values carries 6–10 process-specific rules** |
| Service environments | 18, spanning corrosion, thermal, biological, structural, mechanical and wear |
| Audit regimes | 13 checklists, 71 items |
| Red flags | 33, each with an observable signal |
| Glossary | 32 terms |
| Written library | 23 documents |

`test_every_process_meets_the_parity_floor` fails the build if any process drops
below six process-specific rules. **The fix is to add sourced rules, not to lower
the floor.**

### Where to extend next

Coverage is even, not complete. The honest next steps:

- **Licensed reference works.** Machinery's Handbook and the ASM Handbook are the
  field's canonical references and are commercially licensed. Facts may be stated
  and attributed; text may not be reproduced. Digital enterprise licensing is
  worth pricing.
- **Public-domain technical literature.** MIL-HDBK series, NASA technical reports
  (NTRS), DOE and NIST handbooks are free to use and substantial. This is the
  largest available uplift that costs nothing but effort.
- **Regimes not yet covered:** aviation maintenance (EASA Part 21/145), mining,
  agricultural machinery, semiconductor fab equipment.
- **Customer shop data.** The point of the whole design. Every number here is a
  cold start waiting to be replaced.

Applying the contract matters more than filling the table. A narrow area with
well-sourced rules is worth more than a broad one with invented numbers.

## What this corpus is *not*

- **Not a substitute for the customer's shop.** Every number here is a
  literature default. The moment a shop reports a real value, the shop wins.
  That is the ground-truth flywheel; this corpus is only the cold start.
- **Not a standards library.** It does not reproduce standards text. It records
  *what the standard requires* and points at the clause. Buy the standard.
- **Not legal or certification advice.** An engine that says "NACE MR0175
  requires ≤ 22 HRC" is stating a design constraint, not certifying compliance.
  Compliance is asserted by a qualified person against the controlled document.
