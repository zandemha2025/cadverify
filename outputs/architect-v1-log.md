# Architect V1 Fix-Spec — Log

**Agent:** V1 Fix-Spec Architect · **Date:** 2026-06-28 · **Status:** DONE (not blocked)

## What I did
- Read all inputs: `validation-packet.md` (8 weaknesses, Section B), `v0-spec.md`, `strategy.md`, `build-readme.md`, and every module in `backend/src/costing/` (provenance, rates, drivers, routing, cost_model, leadtime, decision, estimate, report, cli, __init__) + both test files.
- Reproduced the live V0 incoherence bug (#7) on the ECU mount: headline "Make by fdm", crossover pairs fdm↔injection_molding, but @qty-50 argmin = cnc_3axis (a DFM-fail process). Three different processes — confirmed root cause: `low_volume_process` = argmin(fixed among DFM-ready); `recommendation[q]` = argmin(unit over ALL incl DFM-fail). They are not the same selection.
- Prototyped the full proposed V1 cost model in a scratch script and verified every worked number against the stated DEFAULTs (no fabrication): ECU SLS $126→$47.25, MJF $44.13, throttle SLS@100 $41→$7.42, crossover ~739. Confirmed nesting drops powder-bed machine from 82% of unit to a minority share, and small-part AM lands in the validation packet's independent $4–8 ballpark.

## Deliverable
`outputs/v1-fix-spec.md` — build-ready, single builder, zero open decisions. Covers all 8 weaknesses (module/function, formula, DEFAULT + source basis, override path) plus the accuracy-harness design (independent local reference bands R1–R4, ≥10-part reproducible sample, per-process error bands, pass criteria, report format). Σ-invariant and provenance constraints preserved; zero network egress in the harness.

## No blockers
Environment verified working (venv 3.9, trimesh, real parts present, CLI + tests run). Nothing fabricated; every figure traces to a stated DEFAULT and was computed in a verified prototype.
