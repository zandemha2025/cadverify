# Machine-Inventory Verification — Engineering Spec (the verification-thesis crux)

**Author:** Fable (orchestrator) · **Date:** 2026-07-04 · **Status:** DRAFT — capability schema (§3) to be finalized against the machine-capability domain research; everything else buildable.
**Thesis (founder, 2026-07-04):** put a part in → understand its service environment → answer *can it be made, in what environment-valid material, how long, and **on which of THEIR machines** — or if not, exactly why and what machine spec would close the gap.* "Cost" = physical resource cost (material + machine/print hours + machine ownership), never shop/partner price.

This spec turns the **process-level** owned-equipment seam (`owned_processes` → marginal rate) into a **machine-level** capability-matching engine, adds a **service-environment gate**, and threads both through the live decision path and the triage-at-scale path. Nothing here is surface-level: every verdict is a defensible, provenance-tagged claim or an honest abstention.

---

## 0. What "makeable in-house" must mean (the verdict lattice)

For a part P, a process Pr, and an org's owned machine inventory M, the verdict per (P) is one of:

- **`makeable_in_house`** — ∃ a machine m ∈ M that (a) runs process Pr, (b) whose work envelope **fits** P, (c) is **capable** of P's material, (d) meets P's **tolerance/precision** need, (e) is under **max part weight**, and (f) all **required secondary ops** (heat-treat/HIP/etc.) are available in-house. Carries the *best* machine + the resource cost on it (marginal rate).
- **`makeable_with_secondary_op`** — the base machine fits on every gate EXCEPT a precision/finish/density spec the base process can't hold alone (IT below the machine's grade → grind/hone/EDM; fatigue-critical cast/AM → HIP), AND the org **has that secondary op** in-house. Makeable, with the op's added resource cost surfaced as its own line. (If the org LACKS the op → it's a gap, below.)
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

## 3. Data model — `MachineInstance` (org-owned inventory) — FINALIZED against domain research

**Design principle from the research:** every makeability check reduces to a scalar comparison `part_requirement ⩿ machine_capability`, and every failure is one of six gate types — **envelope · mass · force/energy · reach/access · resolution · material-qualification**. So the schema carries a small set of universal typed columns (queried/indexed) + a per-process-family `capabilities` JSONB (the process-appropriate scalars), validated on write against a per-family schema. This keeps the table clean across ~24 heterogeneous process families without a sparse 40-column monster.

`machine_instances` (org-scoped, one row per owned machine or identical group):

| Column | Type | Purpose / gate |
|---|---|---|
| `id` BigInt PK, `ulid` Text | — | identity |
| `org_id` Text NOT NULL (FK orgs) | — | tenant boundary |
| `name` Text | — | "Haas VF-2 #3" (display) |
| `process` Text NOT NULL | ProcessType.value | which process family (indexed) |
| `count` Int default 1 | — | N identical machines (capacity, not fit) |
| `max_workpiece_kg` Float NULL | kg | **mass gate** vs part mass (universal — every family has one) |
| `hourly_rate_usd` Float NULL | $/hr | the machine's OWN rate (overrides rate-card default for cost) |
| `capital_frac` Float NULL | 0–1 | per-machine sunk-capital fraction; NULL → rate-card default |
| `capabilities` JSONB NOT NULL | per-family scalars (below) | the fit gates |
| `materials` JSONB | list of material names/classes **qualified on THIS machine** | **material-qualification** gate |
| `material_thickness_map` JSONB NULL | `{material: max_mm}` (laser/EDM/sheet) | power×material×thickness gate (research §A) |
| `notes` Text, `created_by`, `created_at`, `updated_at` | — | provenance/audit |

**`capabilities` JSONB, by gate type (fields present per family; all USER-declared, validated on write):**
- **Envelope** — one of: `{x,y,z}` mm (mill travels / AM build / EDM Z) · `{bed_x,bed_y}` mm (sheet) · `{swing_dia, between_centers, spindle_bore}` mm (turning) · `{flask_x,flask_y,flask_z}` mm (casting) · `{platen_x,platen_y,tie_bar_gap,daylight}` mm (molding). Orientation permutation allowed for AM/milling.
- **Force/energy** — `spindle_power_kw`, `spindle_taper`, `max_rpm` (mill) · `laser_power_kw` (laser) · `tonnage_t` + `max_bend_length_mm` (brake) · `clamp_tonnage_t` + `shot_capacity_g` + `max_injection_bar` (molding/die-cast) · `press_tonnage_t` (forging) · `furnace_capacity_kg` + `max_pour_kg` (casting) · `max_cut_thickness_mm` (laser/EDM).
- **Reach/access** — `axes` (3/4/5), `motion_mode` (`positional_3plus2` | `simultaneous_5`), `min_tool_dia_mm` (→ min internal radius), `max_tool_reach_ratio`, and turning flags `live_tooling`/`y_axis`/`sub_spindle`/`bar_feed`.
- **Resolution/precision** — `achievable_it_grade` (Int; **store the IT grade, NOT ±mm** — ± is size-dependent, computed per-dimension via ISO 286), `positioning_accuracy_um`, `repeatability_um`, `surface_finish_ra_um`, plus AM/EDM `min_layer_um`, `min_wall_mm`, `min_feature_mm`, `max_taper_deg` (EDM).
- **Material special gates** — `conductive_required` (EDM, bool), `chamber_type` (`hot`|`cold`, die-cast).

Indexes: `(org_id)`, `(org_id, process)`. Migration `0021_machine_instances` (down_revision `0020_manifest_parts`), reversible.

**Conservative-default + honesty note (from the research uncertainty flags):** laser thickness-by-power, forging/casting maxima, and AM per-material build windows are *site-specific and vary ±20–30%*. So capability is **always the org's own declaration** (provenance USER), never a hardcoded process constant; where we offer catalog defaults they are conservative + clearly a starting point to edit. IT-grade→±mm is computed per-dimension from ISO 286, never a stored ±mm.

### 3.1 Shop-level secondary-op capabilities (`shop_capabilities`)
Secondary ops are **shop-level, not per-machine** (a foundry has one HIP vessel, not one per press). Small org-scoped table `shop_capabilities` (or a JSONB on a per-org row): `{heat_treat, stress_relief, hip:{dia_mm,height_mm}, sinter_furnace:{envelope}, grinding, plating, cmm:{measuring_vol}, ct_inspection}` — each a bool + optional size/temp limit. The matcher consumes this as the org's available-secondary-ops set. Some parts **require** an op (HIP for fatigue-critical cast/AM; sinter for binder-jet; stress-relief for metal-AM before plate removal; grind/hone/EDM to reach IT below the base process) — a missing required op is a real gate (§0 `makeable_with_secondary_op` vs a gap).

**Seed convenience:** an "add from catalog" path pre-fills `capabilities` from the static `MachineProfile` reference DB (`profiles/database.py`) — pick "Haas VF-2", edit. The catalog is the *template*; the org instance is the *declaration*.

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
