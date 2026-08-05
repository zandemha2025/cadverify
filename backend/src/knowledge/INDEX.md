# Knowledge corpus — index

Start with [README.md](README.md) for the corpus contract (provenance tiers, the
rules for contributors, and how the engine consumes this).

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
| [Cost and should-cost](library/foundations/cost-and-should-cost.md) | The anatomy of a credible estimate and the five places it goes wrong |
| [Quality, inspection and NDT](library/foundations/quality-inspection-and-ndt.md) | How a part gets believed; FAI vs PPAP; designing for provability |

### Processes — good, bad, and expert heuristics

| Document | Covers |
|---|---|
| [Subtractive machining](library/processes/subtractive-machining.md) | `cnc_3axis`, `cnc_5axis`, `cnc_turning`, `wire_edm` |
| [Additive manufacturing](library/processes/additive-manufacturing.md) | `dmls`, `slm`, `ebm`, `sls`, `mjf`, `fdm`, `sla`, `dlp`, `binder_jetting`, `ded`, `waam` |
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

### Exemplars

| Document | Read it for |
|---|---|
| [Good vs bad](library/exemplars/good-vs-bad.md) | Eight paired examples: the same requirement solved well and badly |
| [The red-flag catalogue](library/exemplars/red-flag-catalogue.md) | The five-minute scan, and every anti-pattern with its tell |

---

## Reading paths

**New to manufacturing.** Manufacturing 101 → DFM first principles → Good vs bad
→ the process document for whatever you are working on.

**Building the engine.** README (the contract) → CAD development → Mesh quality
and repair → `packs/design_rules.yaml` → DFM first principles.

**Preparing for an audit.** The auditor playbook → Industry regimes → the
relevant checklist in `packs/audit_checklists.yaml` → Quality, inspection and NDT.

**Reviewing someone else's part.** The red-flag catalogue (start with the
five-minute scan) → GD&T and tolerancing → the relevant process document.

**Selecting a material.** Materials and service environments →
`packs/environments.yaml` → the relevant process document for what the alloy does
to manufacturability.

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
