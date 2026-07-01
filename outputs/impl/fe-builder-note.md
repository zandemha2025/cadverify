# FE builder note — F1-frontend, F3, F5

Staff FE + principal-design close of the teardown's frontend findings. The Wave-1
backend (`shop` param, `GET /shops`, `overrides`) is already built; this wave wires
the product to it, makes the override loop real, and removes the credibility-hygiene
problems. **Code only — no commit.**

Build proof: `npm run build` ✓ (Next 16, Turbopack, 18/18 pages) and
`npx tsc --noEmit` ✓ — both green. HTTP contracts verified live against the running
backend (see "Live verification").

---

## F1-frontend — the per-shop wedge is now IN the product

**Was:** the cost API call sent no `shop`; the live CalibrationBar's "swap shop"
just toasted *"Shop calibration through the API is a build gap"*; a signed-in buyer
was stuck on "Not calibrated — generic defaults". Per-shop calibration worked only
in the CLI.

**Now:** the live CalibrationBar fetches the real shop list, binds a shop, re-costs
through the cost API with `shop=`, and renders the SHOP-calibrated number + SHOP
provenance. The marquee differentiator is visible and working.

- `lib/api.ts` — `CostOptions` gains `shop?` and `overrides?`; `_costEstimate`
  appends `shop` and `overrides` (JSON) to the form; new `getShops()` →
  `GET /shops` returning `{ shops: [{id,name,region,source}] }`; new
  `ShopProfileInfo` type. Region is now omitted when "auto" so a **bound shop's own
  region wins** (verified: Shenzhen binds as region CN).
- `components/cost/CostOptionsForm.tsx` — region default is now `"auto"`
  ("Auto (shop region, else US)") so binding a shop doesn't get its region
  overridden by a forced US.
- `components/glass-box/calibration.tsx` — new live **ShopPicker** inside the bar:
  "Generic defaults" + one row per shop (name · region · source), the active shop
  checked, a re-costing spinner on the pill and panel. Renders only when `shops`
  is passed, so the static marketing/design-system usages are unchanged.
- `components/workspace/PartWorkspace.tsx` — fetches shops on mount; `onSelectShop`
  binds the shop into `opts` and re-costs; the returned report's "calibrated to
  shop X" note + SHOP-tagged assumptions flow through the existing `parseCalibration`
  so the bar flips to **"Calibrated to <shop>"** with the SHOP/DEFAULT rate split.

**See it live:** log in → **Cost** → drop a part → topbar pill "Not calibrated" →
open it → pick **Midwest Precision CNC** → the unit cost re-costs (e.g. $7.50 →
$14.14 on object.stl), the pill reads "Calibrated to Midwest Precision CNC", and the
drivers/assumptions show SHOP tags. Switch to **Shenzhen Contract Mfg** to drop it
again (and bind region CN).

> Number CORRECTNESS is not self-certified — F1's per-shop numbers go to the
> real-expert (Zoox Head of Manufacturing) validation packet, not marked "done" here.

---

## F3 — the override loop actually re-costs

**Was:** editing an assumption only re-labeled client-side; editing a driver and
"Save as scenario" only toasted *"Server re-cost … is a build gap"*. The number
never moved.

**Now:** an assumption/driver edit threads the engine's real override surface (the
CLI `--set` keys) back through the cost API; the number moves and the touched line
returns tagged **USER**. No more build-gap toasts.

- `lib/cost-views.ts` — pure mapping helpers mirroring `rates.py::_apply_override`:
  `assumptionOverrideKey` (labor_rate, margin, overhead, utilization, stock_allowance,
  daily_machine_hours), `driverOverrideKey` (machine_cost→`machine_rate.<PROC>`,
  labor/setup→`labor_rate`, material→`material_price.@<class>`), and `parseDriverRate`
  which reads the current rate back from the engine's own source string ("× $30/hr")
  so the editor pre-fills honestly.
- `components/glass-box/assumptions.tsx` — a `canOverride` predicate; the pencil
  shows only on assumptions that map to a real re-cost (categorical complexity /
  material_class stay read-only — they're set in Costing options).
- `components/glass-box/driver-breakdown.tsx` — the fake "Override — re-runs" button
  is now an inline editor for the driver's **underlying rate** (labeled "machine
  rate $/hr", "material price $/kg"), so the edit is honest about what it sets.
- `components/workspace/GlassBoxView.tsx` — wires both surfaces to the override key,
  a "Reset overrides" affordance + a USER-count badge when overrides are active, and
  a **session-local scenarios** row.
- `components/workspace/PartWorkspace.tsx` — `onApplyOverride(key,value)`,
  `onSetCavities`, `onClearOverrides` each update `opts.overrides` and re-cost;
  `onSaveScenario`/`onRecallScenario` snapshot the current shop+overrides+headline
  to a session list you can recall (no false persistence claim — labeled
  "Saved to this session").

**See it live:** Cost → **Glass Box** tab → click a driver (e.g. machine cost) →
"Override machine rate" → type 50 → the unit cost re-costs and that line goes USER;
or edit `labor_rate` in Assumptions. "Reset overrides" returns to the shop/default
rates.

> Per the engine invariants: Σ line-items == unit_cost, confidence band, and the SHOP
> note all come straight from `report_to_dict`, so every re-cost stays coherent.

---

## F5 — credibility hygiene

**Was:** internal dev tools shipped in the customer sidebar ("Parts (Label)" corpus
annotator, "Design system" / "the build proof"); the marketing method page captioned
a static fixture as live "real output … not screenshots" and the flagship fixture
self-contradicted (routing headlined a process its DFM hard-failed).

**Now:**
- **Dev tools gated out of the customer nav.** New `lib/dev-flag.ts`
  (`NEXT_PUBLIC_SHOW_DEV_TOOLS`, default **off**; plus a session-local
  `localStorage["cadverify:dev-tools"]` opt-in). `nav-item.tsx` gains a `devOnly`
  flag; `sidebar.tsx` marks "Parts (Label)" and "Design system" `devOnly` and filters
  them (SSR-safe: env-only on first paint, localStorage reconciled in an effect).
  Legitimate developer features (API keys, API docs) stay.
- **Marketing claims made honest.** The method-page caption no longer implies live
  in-browser compute — it states the panels are the real product components rendering
  the engine's own **captured** report for one part (object.stl), "not screenshots or
  mockups". I **verified every fixture number against the live engine** (see below)
  and added that verification note to `marketing/data.ts`; the cosmetic part name is
  aligned to the real captured file (`object.stl`). The **self-contradiction is gone**
  in the engine (Wave-1 F2: `recommend_routing` now respects `dfm_failed`/`dfm_clean`)
  and the fixture reflects it — cnc_turning routes AND passes DFM as "issues" (not
  fail), mjf is make-now, no headlined process is DFM-failed.

**See it live:** the sidebar no longer lists "Parts (Label)" / "Design system" for a
customer; run with `NEXT_PUBLIC_SHOW_DEV_TOOLS=1 npm run dev` (or set the localStorage
key) to restore them for engineering. Visit `/method` for the honest captions.

---

## Live verification (against the running backend)

`GET /api/v1/shops` (authed) → both profiles in the exact `{id,name,region,source}`
shape getShops() consumes.

`POST /validate/cost` (and `/demo`), object.stl, qty 10:

| call | mjf unit | provenance |
|---|---|---|
| no shop | $7.50 | labor DEFAULT |
| `shop=midwest-precision-cnc` | **$14.14** | labor SHOP + "Calibrated to shop 'Midwest Precision CNC'" note |
| `shop=…` + `overrides={labor_rate:80, machine_rate.MJF:50}` | **$22.23** | labor/machine **USER** |
| `shop=shenzhen-contract-mfg` + `overrides={material_price.@polymer:10}` | $7.50 | region **CN** (Auto), material **USER** |
| `overrides={not_a_key:5}` | — | clean **400** "Unknown global rate key" |
| `shop="Midwest Precision CNC"` (display name) | 200 | resolves |

Fixture cross-check (marketing/design-system): object.stl + Midwest = $14.14 @ qty10,
crossover ≈1,962, routing rotational→cnc_turning; Midwest-vs-Shenzhen @ qty1000
(mjf 10.45/2.68, sls 10.64/2.86, cnc_turning 26.92/5.96, cnc_5axis 47.36/10.95,
injection 14.25/4.65) — all match the live engine exactly.

## Files touched

New: `lib/dev-flag.ts`.
Changed: `lib/api.ts`, `lib/cost-views.ts`, `components/cost/CostOptionsForm.tsx`,
`components/ui/nav-item.tsx`, `components/ui/sidebar.tsx`,
`components/glass-box/{calibration,assumptions,driver-breakdown,index}.tsx|ts`,
`components/workspace/{GlassBoxView,PartWorkspace}.tsx`,
`app/method/page.tsx`, `components/marketing/data.ts`.

Design system + role-lens kept intact — this is wiring + correctness + hygiene, not a
redesign. The glass-box language (provenance dots, confidence bands, Σ check, role
lens) is unchanged; the shop picker and rate editors reuse the existing tokens.
