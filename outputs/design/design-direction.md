# CadVerify — Locked Design Direction

## North star
**Least friction to the answer.** The product *is* the manufacturing decision (make by X, $Y/unit,
Z days, switch to a mold above N units). Every design choice is judged by one question: *does it get
the user to that answer faster, with the evidence one click away?* This is also why the comps stumble —
aPriori/Siemens bury the answer under cost-engineering density; Xometry/Protolabs bury it under a
quoting funnel. We surface the answer first; the glass-box detail is progressive disclosure.

## The blend (one language, three strands)
- **Modern-clean SaaS** → clarity, whitespace where decisions live, speed, polished states.
- **Enterprise-authoritative** → one consistent system, structured data, trust signals; credible to a
  Head of Manufacturing and to procurement/IT.
- **Technical-industrial** → precision; numbers are the product (monospace), instrument-grade confidence.

Not a mush: airy & friendly around the *decision*; dense, disciplined & serious around the *data*.

## Concrete decisions (locked — the architect expands, does not re-decide)
- **Color:** neutral-gray foundation; ONE confident accent = steel/technical blue (not playful indigo,
  not loud); strict semantic status — green (pass) / amber (advisory) / red (required-fix). One status
  map, single-sourced, used everywhere.
- **Type:** clean UI sans = Geist/Inter (delete the stray Arial override); **monospace for every number**
  (cost, dimensions, lead time, qty). Scale 32 / 24 / 16 / 14 / 12; tabular figures for tables.
- **Density:** 8px grid. Airy for the hero/decision; compact, right-aligned-numeric, frozen-ID for data
  tables. Density toggle on big tables.
- **Shape/motion:** one radius token (~6–8px), modern but not bubbly; minimal, fast, purposeful motion.
- **Components:** shadcn/ui on Radix + TanStack Table. Exactly one of each primitive (Button, Card,
  Badge/StatusBadge, Table, Input/Select, Tabs, Dialog, Toast, EmptyState, Skeleton). No inline re-rolls.

## Information architecture (kill the Frankenstein roots)
- **One app shell:** left sidebar (logo, sections, active state, account menu) + topbar (part context,
  actions). Enterprise width, not 768px.
- **One route tree:** resolve the `/` collision; delete the duplicate `/dashboard/*` shim tree; one
  namespace; route-protect authed pages.
- **Part-as-an-object with tabs:** a part opens to tabs — **Analyze · Cost/Decide · Tolerances · Share** —
  so the surfaces cohere instead of being silos. Global nav: Analyze · Cost · Batch · History · Label · API · Docs.

## Signature interaction (the north star, made concrete)
1. Drop a CAD file (STL/STEP) → **the ANSWER is the hero**, above the fold: "Make by CNC ≤ 740 units —
   $44.13/unit, 6–10 days · mold wins above 740."
2. Right there: the **make-vs-buy breakeven chart** (cost/unit vs quantity, process curves, marked
   crossover) with a **quantity slider** that live-flips the recommended process. (The thing no comp nails.)
3. Viewer-first: 3D part with DFM issues highlighted on geometry, two-way-linked to a named issue list
   (Required vs Advisory — not opaque scores).
4. **Glass-box on demand:** the provenance-tagged cost breakdown (MEASURED/USER/DEFAULT, Σ=unit) is one
   click/tab away — present for trust, not in the way of the answer.
- **No empty-form cold starts.** No opaque numeric scores. No silos.

## Keep (already at the quality bar)
`CostDecisionCard.tsx`, `AnalysisDashboard.tsx` (refactor onto primitives), the `lib/api*` data layer,
the R3F 3D viewers. Extract primitives upward from these.

*Sources: outputs/design/{current-state-audit, competitor-ux, design-system-patterns}.md*
