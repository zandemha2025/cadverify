# Knowledge corpus — index

Start with [README.md](README.md) for the corpus contract (provenance tiers, the
rules for contributors, and how the engine consumes this), and
[INGESTION.md](INGESTION.md) for what may and may not be brought in from outside
— the licence and ingestion policy the loader enforces.

---

## Machine-readable packs

Loaded and validated by `loader.py`; every record resolves to a citation.

| Pack | What it holds | Engine use |
|---|---|---|
| [`packs/sources.yaml`](packs/sources.yaml) | The citation registry — every source, defined once, tiered | Resolves every `source_id`; nothing may cite outside it |
| [`packs/design_rules.yaml`](packs/design_rules.yaml) | Numeric and advisory design rules per process, each with `why`, good/bad, and the Issue codes it backs | Backs DFM thresholds; lets a finding cite the source of its threshold |
| [`packs/environments.yaml`](packs/environments.yaml) | Service environments, damage mechanisms, material constraints | The Environment Door: filters materials and says why |
| [`packs/audit_checklists.yaml`](packs/audit_checklists.yaml) | What expert auditors open first, per regime, with the classic finding | Audit-readiness narration; design levers |
| [`packs/red_flags.yaml`](packs/red_flags.yaml) | Anti-patterns with an observable `signal` | Detector specifications; "what bad looks like" |
| [`packs/glossary.yaml`](packs/glossary.yaml) | The vocabulary, plus the misunderstanding that usually costs money | Copilot definitions; UI tooltips |

---

## The written library

### Foundations — the 101s

| Document | Read it for |
|---|---|
| [Manufacturing 101](library/foundations/manufacturing-101.md) | The three process families, their physics, and the questions to ask in order |
| [DFM from first principles](library/foundations/dfm-first-principles.md) | The ten principles the numbers come from — the copilot's reasoning backbone |
| [GD&T and tolerancing](library/foundations/gdt-and-tolerancing.md) | 101 to expert, the datum scheme as a functional statement, and the mistakes ranked by cost |
| [Materials and service environments](library/foundations/materials-and-service-environments.md) | Alloy families, damage mechanisms, and why compliance is never a boolean |
| [The environment atlas](library/foundations/environment-atlas.md) | All 18 environments, what each attacks with, and why their solutions conflict |
| [Cost and should-cost](library/foundations/cost-and-should-cost.md) | The anatomy of a credible estimate and the five places it goes wrong |
| [Quality, inspection and NDT](library/foundations/quality-inspection-and-ndt.md) | How a part gets believed; FAI vs PPAP; designing for provability |

### Processes — good, bad, and expert heuristics

| Document | Covers |
|---|---|
| [Subtractive machining](library/processes/subtractive-machining.md) | `cnc_3axis`, `cnc_5axis`, `cnc_turning`, `wire_edm` |
| [Additive manufacturing](library/processes/additive-manufacturing.md) | Metal AM in depth: `dmls`, `slm`, `ebm`, `binder_jetting`, `ded`, `waam` — plus when AM is the right answer at all |
| [Polymer additive](library/processes/polymer-additive.md) | `fdm`, `sla`, `dlp`, `sls`, `mjf` — four technologies with opposite constraints |
| [Moulding and casting](library/processes/moulding-and-casting.md) | `injection_molding`, `die_casting`, `investment_casting`, `sand_casting` |
| [Forging and sheet metal](library/processes/forging-and-sheet-metal.md) | `forging`, `sheet_metal` |

### CAD practice and development

| Document | Read it for |
|---|---|
| [CAD modelling quality](library/cad/cad-modelling-quality.md) | What expert CAD designers do; why a bad model is a cost forecast |
| [File formats and interoperability](library/cad/file-formats-and-interoperability.md) | What survives an exchange; AP242 and semantic PMI; the STL unit problem |
| [Mesh quality and repair](library/cad/mesh-quality-and-repair.md) | Analysing geometry you did not author, and the ethics of repair |
| [MBD, PMI and drawings](library/cad/mbd-pmi-and-drawings.md) | Where product definition lives, and the characteristic-count defence |
| [CAD data management](library/cad/cad-data-management.md) | Revision, release, change impact — "which revision was manufactured?" |
| [CAD development](library/cad/cad-development.md) | Building geometry software: kernels, the hard problems, engine principles |

### Audit

| Document | Read it for |
|---|---|
| [The auditor playbook](library/audit/auditor-playbook.md) | How expert auditors think, the findings that recur, what good evidence is |
| [Industry regimes](library/audit/industry-regimes.md) | Oil & gas, aerospace, medical, automotive — what each demands and fears |
| [Specialised regimes](library/audit/specialised-regimes.md) | Nuclear, pressure equipment, rail, marine class, structural, export control, hygienic — and the trap in each |

### Exemplars

| Document | Read it for |
|---|---|
| [Good vs bad](library/exemplars/good-vs-bad.md) | Eight paired examples: the same requirement solved well and badly |
| [The red-flag catalogue](library/exemplars/red-flag-catalogue.md) | The five-minute scan, and every anti-pattern with its tell |

---

## Reading paths by role

The corpus serves several different jobs. Start where your question lives.

**Design engineer** — "will this part work and can it be made?"
DFM from first principles → the process document for your route → GD&T and
tolerancing → the environment atlas → Good vs bad.

**Manufacturing engineer** — "how do we actually make this, and what will bite?"
Manufacturing 101 → your process document → the red-flag catalogue → Cost and
should-cost → Quality, inspection and NDT.

**CAD designer / drafter** — "is this model and definition fit to release?"
CAD modelling quality → MBD, PMI and drawings → File formats and
interoperability → GD&T and tolerancing → CAD data management.

**Quality engineer / auditor** — "can we prove it?"
The auditor playbook → Industry regimes → Specialised regimes → the relevant
checklist in `packs/audit_checklists.yaml` → Quality, inspection and NDT.

**Procurement / cost engineer** — "is this quote fair, and what is driving it?"
Cost and should-cost → Manufacturing 101 (the volume bands and crossover) → the
process document for the routed process → the economics section of the red-flag
catalogue.

**Materials / corrosion engineer** — "will it survive its world?"
Materials and service environments → The environment atlas →
`packs/environments.yaml` → the process document for what the alloy does to
manufacturability.

**Platform engineer** — "how do I build on this?"
README (the contract) → CAD development → Mesh quality and repair →
`packs/design_rules.yaml` → DFM from first principles.

**New to the whole field.** Manufacturing 101 → DFM from first principles →
Good vs bad → then whichever role path above matches your job.

## Reading paths by task

**Reviewing an unfamiliar part.** The red-flag catalogue (start with the
five-minute scan) → GD&T and tolerancing → the relevant process document.

**Choosing a process.** Manufacturing 101 (the six questions, in order) → Cost
and should-cost (the crossover) → candidate process documents.

**Entering a new industry.** Industry regimes or Specialised regimes → the
auditor playbook → the relevant checklist.

**Debugging a part that failed in service.** The environment atlas (which
mechanism?) → Materials and service environments → the process document (was it
a process defect?) → Quality, inspection and NDT (would inspection have caught
it?).

---

## Extending the corpus

Read the contract in [README.md](README.md) first. In short:

1. Add the source to `packs/sources.yaml` before citing it — the loader rejects
   dangling references.
2. Every numeric rule needs `why`, `units`, `metric` and a `source_id`.
3. Every red flag needs an observable `signal`.
4. Ranges beat false precision; `contested` beats an invented consensus.
5. Never promote a shop rule of thumb to `standard` because it feels solid.
6. Library documents need front matter with `title`, `domain` and `sources`,
   and every `source_id` in it must resolve.

`backend/tests/test_knowledge.py` enforces all six.
