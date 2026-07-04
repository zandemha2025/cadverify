# Machine-Inventory Verification — Engineering Spec (the verification-thesis crux)

**Author:** Fable (orchestrator) · **Date:** 2026-07-04 · **Status:** DRAFT — capability schema (§3) to be finalized against the machine-capability domain research; everything else buildable.
**Thesis (founder, 2026-07-04):** put a part in → understand its service environment → answer *can it be made, in what environment-valid material, how long, and **on which of THEIR machines** — or if not, exactly why and what machine spec would close the gap.* "Cost" = physical resource cost (material + machine/print hours + machine ownership), never shop/partner price.

This spec turns the **process-level** owned-equipment seam (`owned_processes` → marginal rate) into a **machine-level** capability-matching engine, adds a **service-environment gate**, and threads both through the live decision path and the triage-at-scale path. Nothing here is surface-level: every verdict is a defensible, provenance-tagged claim or an honest abstention.

---

## 0. What "makeable in-house" must mean (the verdict lattice)

For a part P, a process Pr, and an org's owned machine inventory M, the verdict per (P) is one of:

- **`makeable_in_house`** — ∃ a machine m ∈ M that (a) runs process Pr, (b) whose work envelope **fits** P, (c) is **capable** of P's material, (d) meets P's **tolerance/precision** need, (e) is under **max part weight**, and (f) all **required secondary ops** (heat-treat/HIP/etc.) are available in-house. Carries the *best* machine + the resource cost on it (marginal rate).
- **`makeable_not_on_owned`** — Pr is a valid route AND the environment permits it, but **no owned machine fits**. Carries the **gap**: the minimal capability delta that would make it makeable (`"exceeds Z travel: part 380mm > your largest 305mm — need ≥380mm"`, `"no owned machine qualified for Inconel 718"`, `"tolerance IT6 exceeds your machines' IT9"`, `"needs 5-axis; you own 3-axis only"`). This is the acquisition-consideration surface ("if they get one").
- **`makeable_outsource_only`** — a valid, environment-permitted route exists but the org has **no capability for this process at all** (owns nothing of that family). Honest: "buy it, or acquire the capability."
- **`environment_excluded`** — the route/material is **invalid for the declared service environment** (e.g. aluminium for sour service; a polymer above its max service temp). Never counted makeable.
- **`not_makeable`** — no valid route at all (geometry invalid, or no process can produce this shape/spec).
- **`unknown`** — insufficient declared data to decide (no inventory declared, or a capability field the org didn't provide). **Never assumed makeable.** This is the honest default and the byte-identical-when-unused state.

These compose with the existing `triage_bucket` (makeable / needs_review / unknown) — machine-fit *refines* it: a part that is `makeable` (DFM-clean, routed) becomes `makeable_in_house` only when an owned machine actually fits; otherwise `makeable_not_on_owned` with the gap. The legacy triage stays intact (byte-identical when no inventory), and the in-house lens is additive.

---

## 1. Scope — three coupled builds, one engine

1. **Machine-inventory model** (§3–§4): org-owned machine instances with real capability fields; CRUD + governance; org-scoped.
2. **Capability-matching + gap engine** (§5): pure functions mapping *part requirements* (measured drivers + declared tolerance + material + environment) against *machine capabilities* → per-(process, machine) fit verdict + gap analysis. No DB, fully unit-testable.
3. **Service-environment gate** (§6): declared environment → restrict materials + processes to those valid; makeability verdict is environment-aware.

Threaded through: the live decision (`/validate/cost` → the in-house verdict + resource cost on the fitted machine), the triage-at-scale path (per-part in-house-makeable flag on `part_summaries`), and the catalog/portfolio read surfaces.

---

## 2. Non-negotiable honesty invariants (gate every phase against these)

1. **No inventory declared → byte-identical.** Absent machine inventory, every existing number and verdict is unchanged; the in-house lens simply reads `unknown`. Assert it.
2. **Capabilities are USER-declared → provenance USER, never MEASURED.** A machine's envelope/rate/material qualification is the org's declaration. A "fits" verdict on the *envelope* is a MEASURED-geometry × USER-capability comparison; the tolerance/secondary-op capability is USER-declared, never a measurement of the machine.
3. **Never fabricate `makeable`.** Missing a capability field → the fit is `unknown` for that axis, not a pass. A green "makeable in-house" must have every gate satisfied by real declared data.
4. **Environment validity is sourced.** "Invalid for sour service" cites the material property/standard (NACE MR0175 flag, max service temp) — the honest data we already carry. No naked exclusions.
5. **Cost stays resource-cost.** Owned machine → marginal rate (existing `machine_capital_frac` seam) at the *specific machine's* rate; not-owned → an explicit acquisition consideration, never a silent shop price. `validated` never flips from a machine-fit.
6. **Gap analysis is concrete + defensible.** Every `makeable_not_on_owned` states the exact measured-vs-declared delta that failed and the minimal spec that fixes it — never a vague "too big."
7. **Scale honesty.** The triage in-house flag over millions is either precomputed (projection) or honestly bounded; no silent truncation.

---

## 3. Data model — `MachineInstance` (org-owned inventory)

> **Capability field set is FIRST-CUT below; finalize against the machine-capability domain research (envelope, weight, materials, tolerance grade, axes, tonnage/power, layer/feature resolution, secondary-ops).** The research returns a per-process-family capability table + a recommended minimal schema — reconcile before the migration lands.

`machine_instances` (org-scoped, one row per owned machine — or per identical group with a `count`):

| Column | Type | Purpose / gate |
|---|---|---|
| `id` BigInt PK, `ulid` | — | identity |
| `org_id` Text NOT NULL (FK orgs) | — | tenant boundary |
| `name` Text | — | "Haas VF-2 #3" (display) |
| `process` Text NOT NULL | ProcessType.value | which process family this machine runs |
| `count` Int default 1 | — | N identical machines (capacity, not fit) |
| `envelope_mm` JSONB | `{x,y,z}` mm (build volume / travels) | **envelope fit** vs part bbox |
| `swing_dia_mm` Float NULL | mm | lathe max swing (turning) |
| `between_centers_mm` Float NULL | mm | lathe max length (turning) |
| `max_part_kg` Float NULL | kg | **weight gate** vs part mass |
| `materials` JSONB | list of material names / classes qualified | **material capability** gate |
| `tolerance_grade` Text NULL | IT grade or ±mm class → mapped to our `tolerance_class` ladder | **tolerance capability** gate |
| `axes` Int NULL | 3/4/5 (subtractive) | undercut/reachability gate |
| `max_thickness_mm` Float NULL | mm | sheet cut / EDM cut thickness |
| `tonnage` Float NULL | tons | press-brake / forging / molding clamp |
| `power_kw` Float NULL | kW | laser cut-thickness / spindle |
| `min_feature_mm` Float NULL | mm | min wall / min tool radius |
| `hourly_rate_usd` Float NULL | $/hr | the machine's OWN rate (overrides the rate-card default for cost) |
| `capital_frac` Float NULL | 0–1 | per-machine sunk-capital fraction (owned → marginal); NULL → rate-card default |
| `secondary_ops` JSONB | list: heat_treat/HIP/stress_relief/plating/grinding/CMM… | **required-secondary-op** availability |
| `notes` Text, `created_by`, `created_at`, `updated_at` | — | provenance/audit |

Indexes: `(org_id)`, `(org_id, process)`. Migration `0021_machine_instances` (down_revision `0020_manifest_parts`), reversible.

**Seed convenience (not required):** a "add from catalog" path that pre-fills capability from the existing static `MachineProfile` reference DB (`profiles/database.py`) so a user picks "Haas VF-2" and edits, rather than typing every field. The static catalog is the *template*; the org instance is the *declaration*.

**Service-environment declaration** (§6): extend `part_contexts` (already `(org_id, mesh_hash)`-keyed) with nullable `service_environment` JSONB `{max_temp_c, min_temp_c, pressure_bar, corrosive:bool, sour_service:bool, medium, standard}` — declared, provenance USER. Migration `0022_part_context_environment`. (Alternative: a dedicated `part_requirements` table; extending part_context is lighter and reuses the org/mesh key + the declared-context honesty model. Decide at build time; leaning extend.)

---

## 4. Services (org-scoped, mirror the governed-library pattern)

`machine_inventory_service.py`:
- `parse/validate_machine(fields)` — validate process ∈ ProcessType, envelope positive, rate ≥ 0, materials against the material DB/classes, tolerance_grade against a known ladder. Malformed → reported error, never coerced.
- `create/update/delete/list_machines(session, org_id, …)` — CRUD + keyset list (mirror rate_library_service). Bulk CSV import (mirror manifest/groundtruth importer) for a shop declaring 200 machines.
- `load_org_inventory(session, org_id) -> list[MachineCap]` — hydrate to DB-free capability dataclasses for the matcher (mirrors `load_org_ground_truth`).
- `add_from_catalog(profile_name)` — template pre-fill from `MachineProfile`.

`part_environment` on the existing `part_context_service` — add `service_environment` to the declared-context field set (validated, USER).

---

## 5. The capability-matching + gap engine (pure — the heart)

`backend/src/costing/makeability.py` (new, no DB, exhaustively unit-tested):

**Part requirements** — derived from what we already measure + declare:
- envelope need = `drivers.bbox_mm` (sorted); rotational → `rot_cross_dia_mm` × `rot_axis_len_mm`; sheet → footprint × `sheet_gauge_mm`.
- weight = `drivers.mass_kg(material.density)`.
- material = the routed material (name + class + its property flags).
- tolerance need = `options.tolerance_class` (standard/precision/tight → an ordinal).
- feature need = `drivers.nominal_wall_mm` / min radius proxy.
- process = the candidate route.
- required secondary ops = derived from material + process (e.g. forged/cast high-strength → stress relief/heat treat; metal AM → stress relief/plate removal; sour-service alloy → per-standard heat treat) + declared.

**`fit_machine(part_req, machine_cap) -> FitResult`** — per (part, machine), returns `PASS` or a list of concrete `FitFailure(axis, need, have, delta, human)`:
- **envelope**: each part dim ≤ corresponding machine envelope dim (with orientation: allow axis permutation for additive/milling; turning uses swing/length). Fail → `"Z 380mm > machine 305mm (need ≥380mm)"`.
- **weight**: `mass ≤ max_part_kg`. 
- **material**: routed material ∈ machine.materials (by name or class). Fail → `"not qualified for Inconel 718"`.
- **tolerance**: machine tolerance ordinal ≥ part need. Fail → `"needs tight (IT6); machine holds standard (IT9)"`.
- **axes**: undercut/reachability need (5-axis) ≤ machine axes. (Reachability heuristic from geometry: 5-axis needed when the part has undercuts the 3-axis archetype can't reach — reuse/extend the routing archetype classifier.)
- **thickness/tonnage/power**: sheet cut thickness ≤ machine max (power-derived); brake/forge tonnage ≥ required (projected area × factor); EDM cut thickness.
- **min feature**: part min wall/feature ≥ machine min_feature.
- **secondary ops**: every required op ∈ machine/org secondary_ops. Missing → `"requires HIP; not available in-house"`.

**`verify_part(part_req, inventory, env) -> MakeabilityVerdict`** — the top verdict (§0 lattice):
1. Apply the **environment gate** (§6) → drop env-excluded routes/materials.
2. For each surviving route, `fit_machine` against every owned machine of that process; pick the best PASS (lowest resource cost) → `makeable_in_house` (+ machine + cost).
3. No PASS but owns the process family → `makeable_not_on_owned` + **`gap_analysis`** = the *minimal* FitFailure set across the closest machines (smallest deltas), phrased as an acquisition spec.
4. Owns nothing of the family → `makeable_outsource_only`.
5. Aggregate to the part verdict; carry per-route detail.

**`gap_analysis(failures) -> AcquisitionSpec`** — collapse the closest-machine failures into the minimal machine that would pass ("a ≥400×400×400 5-axis mill qualified for Inconel, holding IT7 → makes 3 of your 12 currently-unmakeable parts"). At portfolio scale this becomes a **capability-investment ranking** (which single machine acquisition unlocks the most currently-outsourced parts) — a killer Aramco/vertically-integrated output, and a natural follow-on.

All pure, deterministic, exhaustively tested (§9).

---

## 6. The service-environment gate

`environment_gate(materials, processes, env) -> (valid_materials, valid_processes, exclusions)`:
- **Material validity** from the property data we already carry (the oil-&-gas pack's NACE/`sour_service`/`max_temperature_c` + standards; density; class): sour → require `nace_mr0175`/`sour_service`; temp → material max service temp ≥ env; corrosive/medium → CRA required; etc. Each exclusion cites the property/standard.
- **Process validity**: some environments imply process constraints (e.g. pressure-containing → forged/cast/wrought over AM unless the AM alloy+HIP is qualified — honest, conservative, cited).
- Feeds `verify_part` (§5) before machine-fit, and filters `eligible_processes`/material selection on the live path.
- No environment declared → gate is a no-op (byte-identical).

---

## 7. Integration points (where it plugs in)

- **`routing.eligible_processes`** — add an optional `inventory`/`env` param; when present, annotate each route with its fit verdict + (for cost) route to the fitted machine's rate. Absent → unchanged.
- **`cost_model.cost_breakdown`** — when a specific fitted machine is chosen, use its `hourly_rate_usd`/`capital_frac` instead of the rate-card default (still the marginal seam, now machine-specific). Absent → the existing `owned` process-level path, byte-identical.
- **`estimate.estimate_decision` / `/validate/cost`** — accept `inventory` (org's machines) + `service_environment`; attach the §0 verdict + gap + the machine + resource cost to the decision report. Absent → unchanged.
- **Triage-at-scale (`part_summaries`)** — add `in_house_makeable` (bool/enum) + `gap_summary` columns, maintained by the projection hooks (reuse the machine-fit verdict at persist time). The scaled triage rollup gains an in-house breakdown ("of 2.1M parts: 340k makeable in-house on current equipment; 1.2M need capability X; …"). Honest, uncapped, byte-identical when no inventory.
- **Catalog / portfolio reads** — surface the in-house verdict + gap per row; the portfolio gains the capability-investment ranking (§5).

---

## 8. Scale

- The per-part machine-fit is O(routes × machines) of cheap numeric comparisons — trivial per part. At triage scale it runs **at projection-refresh time** (the `part_summaries` hook), so the read is a SQL `GROUP BY in_house_makeable` — same scale story as the whole-inventory triage already shipped.
- Inventory is tiny (tens–hundreds of machines/org); load once, reuse across the batch.
- The capability-investment ranking (which acquisition unlocks the most parts) is a bounded aggregate over the projection.

---

## 9. Test plan (exhaustive — this is where "nothing less" is enforced)

**Pure matcher (`makeability.py`) — the bulk:**
- Envelope: fits exactly; exceeds each of X/Y/Z (with orientation permutation for additive); rotational swing/length; sheet footprint.
- Weight: under/at/over `max_part_kg`.
- Material: qualified by name; by class; not qualified → correct failure + message.
- Tolerance: machine ≥ / < part need across the full ladder.
- Axes: 3-axis part on 3-axis (pass); undercut part needs 5-axis on 3-axis (fail with the right gap).
- Thickness/tonnage/power/min-feature edge cases per family.
- Secondary ops: required op present/absent.
- Verdict lattice: every §0 outcome produced by a crafted case; `unknown` on missing data (never a fabricated pass).
- Gap analysis: minimal-delta correctness (closest machine, smallest spec that passes); multi-failure collapse.
- Environment gate: sour-service excludes aluminium (cites NACE); over-temp excludes polymer (cites max temp); no-env → no-op.
- **Byte-identity: empty inventory + no env → the decision/triage output is identical to pre-feature** (the hard invariant).

**PG integration:**
- Machine CRUD org-scoped + isolated; CSV bulk import; cross-tenant (org A never sees/uses org B's machines).
- `/validate/cost` with inventory+env → verdict + machine-specific resource cost; without → byte-identical.
- Triage projection maintains `in_house_makeable`; scaled rollup breakdown correct; cross-tenant.
- Migration `0021`/`0022` round-trip (upgrade head → downgrade base → re-upgrade), reversible, on top of the 0001→0020 chain.

**Gate discipline (per phase):** adversarial diff review → full no-DB suite (byte-identity of the existing engine) → throwaway-Postgres migration round-trip + PG integration → integrate. Same bar as every track this cycle.

---

## 10. Phased build (orchestration)

- **Phase A — model + inventory service + CRUD/CSV + migration 0021** (Opus builder, worktree). Gate.
- **Phase B — the pure matcher + gap engine + environment gate (`makeability.py`) + env declaration (part_context extension + migration 0022)** (Opus builder — this is the crux, most tests). Gate.
- **Phase C — live integration**: `eligible_processes`/`cost_breakdown`/`estimate`/`/validate/cost` wiring, machine-specific marginal rate, verdict on the decision report (Opus). Gate.
- **Phase D — triage-at-scale**: `part_summaries` `in_house_makeable` + projection-hook maintenance + scaled rollup breakdown + capability-investment ranking (builder). Gate.
- Each phase: byte-identity-when-unused proven, honesty invariants (§2) asserted, adversarial diff, full suite + PG. Phases A→B→C→D sequential (C depends on B; D on C); within a phase, parallelize independent files.

**First cut to build once §3 is finalized against the domain research: Phase A + Phase B in parallel worktrees (A = data/CRUD, B = pure engine — disjoint), then C, then D.**

---

*Open decisions to close before Phase A: (1) final capability field set from the domain research; (2) extend `part_contexts` vs a new `part_requirements` table for the environment (leaning extend); (3) the tolerance-grade → `tolerance_class` mapping ladder; (4) the 5-axis/undercut reachability heuristic (extend the routing archetype classifier vs a new geometric check).*
