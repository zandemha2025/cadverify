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

## G. Fresh-eyes hunt findings (2026-07-04; §32 orchestrator-verified)
32. **NO MULTI-USER ORG — the #1 gap in the whole register.** Every user (password/Google/SAML) is auto-siloed into a personal org (`ensure_personal_org` is the ONLY membership-creation path, org_context.py:154); no invite, add-member, org-create, or org-switch endpoint exists (verified). Two engineers at one company get two isolated worlds; "a colleague joins" is impossible; moat #3 (org memory) unreachable; SSO marketing hollow. Design has the Members surface — build-absent. `build` (L). **NEXT BACKEND BEAT after Phase D.** User deactivation (§39) rides along.
33. **Verdict collects no surface finish / heat treatment / inspection specs** — cost-dominant process specs, none declared or collected (zero hits for Ra/heat_treat/HRC/inspection/FAI in the costing path). The #1 verdict-credibility hole for a real ME. Distinct from GD&T (§7). `both` (M).
34. **Shops carry no certifications (AS9100/NADCAP/ISO/ITAR)** while the rule packs already demand them (aerospace.py:108 FAIR per AS9102, automotive PPAP, medical UDI) — "make outside" can't route to a qualified shop. `both` (M).
35. **Audit log coverage is hollow** — machine CRUD, library publishes, governance approvals, ground-truth ingest, and THE DECISIONS THEMSELVES emit no audit events; "why did we decide in March?" is unanswerable. Contradicts the site's audit-trail claim. `build` (M; decision events are cheap — ride the §32 beat).
36. **Programs are a free-text label, not an object** — no programs table/router/CRUD/lifecycle; the designed Programs surface has a stub underneath; volume→exposure is string-grouped. `both` (M).
37. **Decisions never go stale** — no rate_version staleness signal on records when rates change quarterly; the memory silently rots. Calibration switcher replays faithfully but nothing says "computed at v11, you're on v13 — re-verify?". `both` (M).
38. **Decision dead-end** — "make outside"/"acquire" record the choice but bridge to nothing (no RFQ handoff, no capex request, no outsourcing tracker). Scope decision needed: system-of-record boundary vs last-mile. `design` first.
39. **No user deactivation/offboarding** — no is_active column; SSO re-provisions departed users on next login. Procurement blocker. `build` (S–M, rides §32).
40. **No org data export / right-to-erasure** — decision-level export exists; account/org-level export+delete absent (GDPR/CCPA line item). `build` (M).
41. **USD-locked** — no currency/FX handling anywhere, for an Aramco-scale international thesis. `build` (M).
42. **mm-only** — no imperial display toggle; US shops read inches. `both` (S–M).
43. **Environment door is O&G-shaped** — fixed schema (temp/pressure/sour/medium) can't express fatigue, biocompatibility, radiation, galvanic, flammability — despite aerospace/automotive/medical rule packs existing. The marquee input moment is single-vertical. `both` (M).
44. **No weldments / multi-body / sheet-metal part types** — single-solid-body assumption; distinct from STEP-assembly context (§1). Any ME whose work is fabrications bounces. `build` (L; scope honestly on the site until built).

---
*Top of queue (re-ranked after the hunt): Phase D (§9, in flight) → **ORG MEMBERSHIP beat: §32 + §39 + §35 decision-audit events** → programs-as-object (§36) + decision staleness (§37) → ask-the-engine v1 (§10) → verdict process-specs (§33) + shop certifications (§34) → declare-your-floor onboarding (§17) → verification-record export (§12) → units toggle (§42) → the rest by impact. §38/§43/§44 need founder scope decisions before building.*
