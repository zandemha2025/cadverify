# CadVerify — Product Gaps Register (living; 2026-07-04)

**Mandate (founder):** don't just plug-and-play — find what's missing, design it, build it, polish it. This register is the loop's source for that. Disposition: `design` / `build` / `both` / `external` / `queued` (already in the plan).

## A. Engine gaps
1. **STEP-assembly / product-structure ingestion** (W3.5 rung 2 — the context zoom-out's data). Needs OCP/cadquery (not installable in cloud sandboxes; deploy-target/local task). `build` — the verification thesis's "part in its world" is declared-only until this lands.
2. **Secondary-op costing** — `makeable_with_secondary_op` names grind/HIP but adds no $ line (Phase C carried limitation). `build` (small; spec exists).
3. **True 5-axis/undercut reachability** — verdict defers to the routing archetype; a geometric check would harden "can it be machined." `build` (M; research first).
4. **Force gates need declared force** — tonnage/taper never derived from geometry. `build` (M) or honest-input polish (`design`: make the declaration moment obvious).
5. **Lead-time/queue honesty** — design shows "at current queue"; the engine's queue model is a static assumption. Either a real queue state on machine inventory (throughput × backlog) or an explicit `[assumption]` tag end-to-end. `both`.
6. **estimates[] ordering is PYTHONHASHSEED-dependent** (pre-existing; latent served-payload instability). `build` (micro-beat, own gate — changes served bytes).
7. **GD&T/PMI extraction** — tolerance-class is declared, never read from drawings. Strategy memo says spec authoring is a partner seam, not ours to own — keep declared-input, polish the input UX. `design`.
8. **Materials breadth** — oil-&-gas pack landed; Monel, forged 625/718 variants named as follow-on data. `build` (S, governed data not constants).

## B. Platform gaps
9. **Phase D** — triage `in_house_makeable` projection + capability-investment ranking. `queued` (next backend beat; the design's Triage drill-down payoff).
10. **Ask-the-engine v1 without an LLM** — the design's ask dock is IN DEVELOPMENT; the copilot is the category's center of gravity per research. A deterministic v1 is buildable NOW: constrained grammar (qty/material/region/shop/environment what-ifs → EstimateOptions), honest refusal for anything else — structurally cannot hallucinate because it only parses into engine calls. `both` (design the answer/refusal states are done; build the parser + wire). **High-leverage.**
11. **Geometry-similar parts** — the analogy k-NN already embeds geometry for quotes; the same index could power "similar parts in your catalog" (dedupe, precedent decisions). `both` (M). Real moat surface.
12. **Verification-record PDF/export** — cost PDF exists; the verification record (verdict + gaps + env exclusions + resource cost) has no export. The shareable record is the growth loop. `build` (S–M; template exists as pattern).
13. **Decision sign-off flow** — records carry "whoever decided"; no review/approve on decisions themselves (governance flow exists only for libraries). Enterprise expectation. `both` (M).
14. **Notification center** — webhooks exist (batch + verification events per design seams); no in-product notifications backend. Design stubbed it. `build` (M).
15. **Session revocation + SAML config UI** — long-standing backlog; enterprise gate adjacents. `build` (M).
16. **Governance self-approve flag** — one-line `allow_self_approve=False` before any enterprise/Aramco sale. `build` (S, queued).

## C. Product/UX gaps (beyond the current handoff)
17. **Declare-your-floor onboarding wizard** — day-zero friction is machine entry. CSV import exists; add "start from the reference catalog" (the 19-machine `/api/v1/machines` catalog → pick yours → set rates) and make first-run a guided arc: floor → first part → first verdict. `design` then `build`. **The activation moment.**
18. **Error/edge states** — designed: firstrun, negative verdict, pipeline overlay. Missing: network failure, structured 4xx rendering (invalid geometry with repair guidance is a backend strength — surface it beautifully), timeout/long-compute, partial batch failures. `design`.
19. **Responsive strategy** — prototypes are 1440-fixed; decide the floor (desktop-first with a tablet pass; mobile = read-only records/share views). `design`.
20. **Accessibility pass** — reduced-motion exists in the design system; needs contrast audit on provenance colors (bronze-on-white is borderline), keyboard nav for the walk, focus states. `design` + `build`.
21. **The pilot-report artifact** — the site sells "a validated-on-your-parts report including the parts we got wrong"; no designed artifact exists for it (measured residuals per process family). This is the sales-closing document. `both` (M). 
22. **Batch/BOM drop UX into Triage** — backend batch-cost exists (W3), triage exists; the ingest moment (drop ZIP/manifest → parts stream into buckets live) is designed only as a static screen. `build` (wire batch → part_summaries → triage live updates).

## D. Data/content gaps
23. **Machine seed catalog coverage** — 19 reference machines; real floors have brands/models beyond it (Mazak, DMG, Trumpf, EOS…). Curated expansion as governed data. `build` (S, data).
24. **Region rate seeds** — defaults exist; per-region governed rate-card seeds would make the first verdict less DEFAULT-heavy. `build` (S–M, data + provenance honesty).

## E. Go-live / ops gaps
25. **Deploy runbook** — must run `backend/scripts/backfill_part_summaries.py` once; enable flags deliberately (RATE/SHOP/MATERIAL_LIBRARY, COST_ENSEMBLE, METRICS, BATCH_COST, NEXT_PUBLIC_VERIFY_UI); Prometheus scrape config; verify Docker image builds with new deps. `build` (S — write `outputs/deploy-runbook.md`).
26. **prod promotion** — blocked on founder ("promote it" or the settings allow-rule); origin/prod is many gates stale.
27. **Local dev env drift** — venv is py3.9, CI/Docker 3.12; keep `from __future__ import annotations` discipline; plan a venv upgrade beat.
28. **CI for the frontend flag matrix** — flag-off byte-identity should be CI-enforced once VERIFY_UI merges. `build` (S).

## F. Trust / human gates (external, prepared by us)
29. **Validation with real operator data** — the reframed gate: machine-hours accuracy + the customer's own historical costs (packet regen queued post-Phase-C/D + prod promotion).
30. **Pen test, SOC 2** — external; the site now states them honestly (in progress/planned).
31. **The honesty paradox GTM** — wide bands until data arrives; the pilot flow (#21) is the answer; keep it front and center.

---
*Top of queue derived from this register: Phase D (§9) → ask-the-engine v1 (§10) → declare-your-floor onboarding (§17) → verification-record export (§12) → secondary-op costing (§2) → deploy runbook (§25). A fresh-eyes 3-lens gap hunt is running to extend this list; findings merge here.*
