---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Enterprise
status: defining
last_updated: "2026-04-15T00:00:00.000Z"
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 15
  completed_plans: 0
  percent: 0
---

# STATE: CadVerify

**Last updated:** 2026-04-15 (after v2.0 Enterprise milestone initialization)

## Project Reference

- **Project doc:** `.planning/PROJECT.md`
- **Requirements:** `.planning/REQUIREMENTS.md`
- **Roadmap:** `.planning/ROADMAP.md`
- **Research:** `.planning/research/` (SUMMARY, STACK, FEATURES, ARCHITECTURE, PITFALLS)
- **Brownfield codebase map:** `.planning/codebase/` (ARCHITECTURE, STACK, STRUCTURE, CONVENTIONS, INTEGRATIONS, CONCERNS, TESTING)

**Core value:** Upload a CAD file, get back trustworthy, process-aware manufacturability feedback in seconds — with enough specificity that an engineer can act on it.

**Current milestone:** v2.0 Enterprise — 4 phases (9-12), 22 requirements, 100% mapped.

## Current Position

- **Phase:** Not started (defining requirements)
- **Plan:** —
- **Status:** Defining requirements
- **Progress:** [░░░░░░░░░░] 0%

**Next action:** `/gsd-discuss-phase 9` or `/gsd-plan-phase 9` to begin Phase 9 (Batch API + Webhook Pipeline).

**Last session (2026-04-15):** Initialized v2.0 Enterprise milestone. Defined 22 requirements across 4 phases (9-12). Updated PROJECT.md, REQUIREMENTS.md, ROADMAP.md.

## Milestone Progress

| Phase | Status | Plans Complete |
|-------|--------|----------------|
| 9. Batch API + Webhook Pipeline | Not started | 0/3 |
| 10. Image-to-Mesh Pipeline | Not started | 0/3 |
| 11. STEP AP242 + GD&T/PMI Extraction | Not started | 0/4 |
| 12. On-Premise Deployment Hardening | Not started | 0/5 |

## Performance Metrics

- Phases completed: 0 / 4
- Plans completed: 0 / 15
- Requirements delivered: 0 / 22

## Accumulated Context

### Key Decisions (carried from v1.0 + v2.0)

- Public free beta, no billing (v1.0)
- API-key-only auth with Google OAuth + magic-link signup (v1.0)
- Vercel (frontend) + Fly.io (backend + worker) + Neon Postgres (v1.0)
- arq as job queue — already deployed, reuse for batch pipeline (v1.0 Phase 7)
- Docker Compose + fly.toml already exist (v1.0 Phase 6)
- Enterprise target: Saudi Aramco with 14M legacy parts (v2.0)
- Image-to-mesh reconstruction as competitive moat (v2.0)
- STEP AP242 with GD&T for enterprise credibility (v2.0)
- On-prem deployment with SSO/SAML/RBAC for enterprise customers (v2.0)

### Research Flags Pending

- **Phase 9:** S3 integration, CSV manifest schema, webhook retry strategy, arq concurrency tuning
- **Phase 10:** TripoSR vs InstantMesh, model licensing, GPU requirements, quality metrics
- **Phase 11:** OpenCascade AP242 PMI API, GD&T data model, tolerance-to-process mapping
- **Phase 12:** SAML 2.0 providers, RBAC patterns, SOC2 audit schema, air-gap bundling, Helm

### Open Todos

- Run `/gsd-discuss-phase 9` to begin Phase 9 (Batch API + Webhook Pipeline)
- All 4 phases need `/gsd-research-phase` before planning

### Blockers

None.

## Session Continuity

**On session resume:**

1. Read PROJECT.md for product intent
2. Read ROADMAP.md for phase structure + dependencies (scroll to v2.0 section)
3. Read this STATE.md for current position
4. If entering a new phase, check "Research Flags Pending" above
5. Continue from `Next action` above

---

*State initialized: 2026-04-15 for v2.0 Enterprise milestone*
