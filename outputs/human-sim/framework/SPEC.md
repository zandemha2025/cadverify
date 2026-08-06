# CadVerify — Phase-1 Living Behavioral Map (SPEC)

The complete, honest inventory of the CadVerify product that every human-sim
validation run scores against. Read-only survey; all anchors are `file:line`.

**Two distinct product surfaces exist and both are in scope:**

1. **The Verify "light instrument"** — the founder-approved primary product, a
   single client shell at `/verify` gated by `NEXT_PUBLIC_VERIFY_UI`
   (`frontend/src/app/(verify)/layout.tsx:25`, `frontend/src/lib/verify-flag.ts`).
   Light-themed, own rail + top bar, one state container:
   `frontend/src/components/verify/verify-app.tsx:77`. **This is where a fresh
   login lands** (`frontend/src/app/(auth)/login/page.tsx:14` → `POST_LOGIN_HOME = "/verify"`).
2. **The legacy `(app)` dark enterprise dashboard** — the older route group under
   `frontend/src/app/(app)/*` (analyze, cost, batch, history, cost-decisions,
   integrations, settings, reconstruct, rfq-packages, notifications, keys). Still
   reachable from inside the app but "no longer the product's front door"
   (`login/page.tsx:10-12`).
3. Plus the **`(site)` marketing theater** and **`(auth)` login/signup** groups.

Backend: FastAPI, all routers registered in `backend/main.py:246-362`.
Frontend→backend calls go same-origin through the Next authed proxy
`frontend/src/app/api/proxy/[...path]/route.ts` (`/api/proxy/<p>` → backend
`/api/v1/<p>` with the httpOnly `dash_session` cookie; no API key in the browser).

---

## (A) SCREENS TABLE

### A.1 Verify light-instrument surfaces (`frontend/src/components/verify/`)

Router: `verify-app.tsx:362-435`. Rail/hotkey map: `verify-app.tsx:37-61` (H/V/P/R/G/M/T/C, ⌘K palette, `?` shortcuts).

| Screen | File:line | For | What the user does | Renders |
|---|---|---|---|---|
| Home (desk) | `home-screen.tsx:32` | The verification desk / day-zero landing | Sees records, in-flight, floor count, action queue, ground-truth flywheel, activity; picks a file | Real GET `/cost-decisions`, `/machine-inventory`, `/governance/change-requests`, `/ground-truth`; honest EMPTY state when org has no data (`home-screen.tsx:3-22`) |
| Verify / Verdict Walk | `verify-screen.tsx` (mounted `verify-app.tsx:401`) | The hero loop: can this part be made, on your machines, in its world, and what will it take | Drops STL/STEP/IGES, toggles environment (temp/sour/pressure), picks material class, re-verifies, asks NL questions | Stage 3D render + verdict walk: routing, DFM, should-cost drivers, crossover, makeability lattice. Every number real or WITHHELD (`verify-screen.tsx:3-11`) |
| Stage (3D) | `stage.tsx` / `stage-canvas.tsx` (mounted `verify-app.tsx:365`) | Tessellated part render | Orbits, sees measured bbox/volume/watertight | Real GLB from `/validate/preview-mesh` (`lib/verify/preview-mesh.ts:52`); assembly GLB from `/validate/assembly` |
| Assembly panel | `assembly-panel.tsx:20` | Multi-part (>=2 solids) in-context analysis, replaces the walk | Selects part-of-interest, reads per-part verdict/cost/interference | Real per-part DFM+should-cost+interference from `/validate/assembly?format=analysis` (`lib/verify/assembly.ts:295`); honesty boundaries block (`assembly-panel.tsx:16-18`) |
| Parts catalog | `catalog-screen.tsx:22` | Org-scoped parts×decisions grid | Filters (state/findings), searches, paginates, opens a part standing | Real GET `/catalog` via `fetchCatalog` + `mapCatalogItems`; geometry previews WITHHELD (neutral glyph) (`catalog-screen.tsx:15-20`) |
| Part standing | `part-screen.tsx:21` | The org's memory of ONE part (identity + history + decisions) | Reviews lineage, decision history, blockers | Assembled from GET `/catalog`, `/part-context/{mesh_hash}`, `/cost-decisions`, `/cost-decisions/{id}` (`part-screen.tsx:9-12`) |
| Compare | `compare-screen.tsx:17` | Same part, two calibrations/routes | Picks two saved decisions, reads deltas + crossover + bands | Real GET `/cost-decisions/compare?ids=a,b` + each `/cost-decisions/{id}` for the honest bands (`compare-screen.tsx:4-9`) |
| Records | `records-screen.tsx:17` | System of record (immutable artifacts) | Lists decisions, opens read-only shared-record view, exports/shares | GET `/cost-decisions` + `/{id}`, export.json/csv/pdf, POST/DELETE `/{id}/share` (`records-screen.tsx:4-15`) |
| Programs (portfolio) | `programs-screen.tsx:17` | Portfolio roll-up volume→exposure | Groups parts into programs, declares annual volume | GET `/catalog/portfolio` + PUT `/part-context/{mesh}`; $/year WITHHELD without USER volume (`programs-screen.tsx:4-15`) |
| Program detail | `program-screen.tsx:21` | One program's declared-world summary | Assigns parts, declares volume, sees world alignment | GET `/catalog/portfolio` + PUT `/part-context/{mesh}` merge-write (`program-screen.tsx:8-19`) |
| Your machines | `machines-screen.tsx:12` | Declare the floor + machine detail | CRUD machines, CSV import, sees rate history + parts routed here | Real CRUD `/machine-inventory` (list/create/get/patch/delete/import) + `/rate-library` + `/cost-decisions`; every cap is ●USER (`machines-screen.tsx:3-10`) |
| Triage at scale | `triage-screen.tsx:16` | Whole inventory → makeability buckets | Drills into buckets, sees which acquisition unlocks most parts, bulk-imports manifest | GET `/catalog/makeability` + `/catalog/capability-investment`; POST `/manifest/import` (`triage-screen.tsx:4-14`) |
| Calibration & truth | `calibration-screen.tsx:25` | Governed-truth surface (how accuracy is earned) | Publishes governed rates, reviews change-requests, imports ground truth, recalibrates, manages members/keys/audit | rate-library, governance, ground-truth, admin `/users` + `/audit-log` + `/usage-summary` + `/webhook-deliveries`, `/keys` (`calibration-screen.tsx:9-23`) |
| Acquisition modal | `acquisition-modal.tsx:24` | Make-vs-buy as a capital question | Reads capex-vs-marginal against engine crossover | Persisted CostReport + GET `/catalog/capability-investment`; standalone capex WITHHELD (`acquisition-modal.tsx:3-21`) |
| Command palette | `command-surfaces.tsx` (mounted `verify-app.tsx:427`) | ⌘K jump/scripted asks | Jumps to any surface/action | Nav map |
| Notifications panel | `command-surfaces.tsx` / `notifications-panel.tsx` (mounted `verify-app.tsx:360`) | Workflow inbox | Reads/marks notifications | GET `/notifications`, POST `/{id}/read`, `/read-all` (`lib/verify/notifications-api.ts:89-106`) |
| Shortcuts overlay | `shortcuts-overlay.tsx` (mounted `verify-app.tsx:435`) | Keyboard help | `?` opens | Static |
| Calibration switcher | `calibration-switcher.tsx` (header `verify-app.tsx:341`) | Bound-rate indicator | Opens calibration | Reads rate binding |

### A.2 Legacy `(app)` dark dashboard pages (`frontend/src/app/(app)/`)

| Route | File | For |
|---|---|---|
| `/cost` (app home) | `cost/page.tsx` → `LandingEntry` | Drop CAD → should-cost (three-door landing behind flag) |
| `/analyze` | `analyze/page.tsx` → `PartWorkspace defaultRole="mfg"` | Routing & DFM lens, findings 2-way linked to 3D |
| `/analyses/[id]` | `analyses/[id]/page.tsx` | Saved analysis detail |
| `/batch`, `/batch/[id]` | `batch/page.tsx`, `batch/[id]/page.tsx` | Bulk upload + batch progress/items/CSV |
| `/history` | `history/page.tsx` | Analysis history + quota |
| `/cost-decisions`, `/[id]`, `/compare` | `cost-decisions/*` | Saved cost-decision history/detail/compare |
| `/rfq-packages`, `/[id]` | `rfq-packages/*` | Build/download RFQ evidence ZIPs |
| `/integrations` | `integrations/page.tsx` | Connector registry + run ledger |
| `/notifications` | `notifications/page.tsx` | Inbox |
| `/reconstruct` | `reconstruct/page.tsx` | Image→mesh reconstruction (async job) |
| `/label` | `label/page.tsx` | Local corpus labeling (dev-gated) |
| `/onboarding` | `onboarding/page.tsx` | 3-step: declare floor → publish rates → send actuals (all deep-link to `/verify`) |
| `/settings/organization` | `settings/organization/page.tsx` | Org, members, invites, keys, activity, SAML/SCIM |
| `/settings/developer` | `settings/developer/page.tsx` | API keys (reveal-once) |
| `/design-system` | `design-system/page.tsx` | Internal component gallery |

### A.3 `(site)` marketing + `(auth)` + public share pages

Marketing: `(site)/page.tsx` (cinematic home), `platform/`, `method/`, `security/`,
`company/`, `teams/{cost-engineering,design-engineering,in-house-manufacturing,shop-owners,sourcing}`,
`developers/`, `api-reference/`, `pilot-report/`, `status/`, `privacy/`, `terms/`, `dpa/`.
Auth: `(auth)/login/page.tsx`, `signup/page.tsx`, `magic/sent`, `magic/verify`, `orgs/accept/page.tsx`.
Public share: `app/s/[shortId]/page.tsx` (analysis), `app/s/cost/[shortId]/page.tsx` (cost decision).
Docs: `app/docs/page.tsx`, `app/scalar/route.ts`. Errors: `app/error.tsx`, `global-error.tsx`, `not-found.tsx`.

---

## (B) WORKFLOWS

Each: entry → steps → screens → backend routes → expected outcome.

**W1 — Upload a part → verify → should-cost (the hero loop).**
Entry: Home "Verify a part" / header primary action / hotkey V / drop file
(`verify-app.tsx:356,269-279`). Steps: pick file → `runVerify` (`verify-app.tsx:119`)
→ `runVerification` (`lib/verify/run.ts:142`): (1) GET `/machine-inventory` for owned
processes; (2) compute mesh hash + PUT `/part-context/{mesh_hash}` to persist the
declared world; (3) POST `/validate` (DFM); (4) POST `/validate/cost` with
`owned_processes` (marginal costing). Screens: Home → Verify (Stage + VerifyScreen).
Expected: verdict walk with routing, DFM findings, glass-box drivers (provenance
tagged), crossover, makeability lattice IF machines/env declared, else honest "not
evaluated"; walk stops at a failed gate (GEOMETRY_INVALID 400).

**W2 — Environment declaration → survival gate (real round-trip).**
Entry: toggle temp/sour/pressure + material class on VerifyScreen (`verify-app.tsx:79,406-408`).
Steps: change triggers re-run (`verify-app.tsx:196-213`) → env persisted via PUT
`/part-context/{mesh_hash}` (`lib/verify/run.ts:160-176`) → cost route returns a
`verification` block with `env_exclusions` citing standards (NACE MR0175 / HDT).
Expected: material-survival exclusions with cited standards, or honest unknown.

**W3 — Assembly upload → per-part analysis.**
Entry: drop a STEP/IGES with >=2 solids (`verify-app.tsx:140-165`). Steps: parallel
`fetchAssembly` (GLB + tree) then `fetchAssemblyAnalysis` (`lib/verify/assembly.ts:295`,
`/validate/assembly?format=glb|json|analysis`). Screens: Stage + AssemblyPanel.
Expected: per-part quantity(FACT)/verdict/should-cost/interference; honest per-part error, boundaries block.

**W4 — Bulk manifest → triage at scale.**
Entry: Triage screen (hotkey T). Steps: POST `/manifest/import` (CSV/BOM) →
GET `/catalog/makeability` (buckets) → drill `/catalog/triage` → GET
`/catalog/capability-investment` (`lib/verify/triage-api.ts:141-192`). Expected:
makeability buckets summing to total, stale flagged, one-acquisition unlock ranking.

**W5 — Configure machines → makeability.**
Entry: Your machines (hotkey M). Steps: create/patch/delete or CSV import via
`/machine-inventory` (`lib/verify/machine-api.ts:84-118`); shop-capabilities PUT.
Expected: owned floor feeds W1 marginal costing + W4 makeability; caps tagged ●USER.

**W6 — Portfolio program setup → annual exposure.**
Entry: Programs (hotkey G). Steps: GET `/catalog/portfolio`, assign part + declare
volume via PUT `/part-context/{mesh}` (`lib/verify/program-api.ts:110-182`).
Expected: $/year = unit cost × declared volume, WITHHELD without volume.

**W7 — Calibration / ground-truth flywheel.**
Entry: Calibration & truth (hotkey C). Steps: publish governed rate version
(rate-library + governance change-request → approve), import ground truth
(`/ground-truth/import`), POST `/ground-truth/recalibrate` (`lib/verify/calibration-api.ts`).
Expected: bands flip hatched→solid only on real held-out residuals; below floor recalibrate REFUSED.

**W8 — Save / export / share a decision (system of record).**
Entry: Records or after a verify. Steps: cost route auto-persists (`saved:{id,url}`,
`routes.py:1820-1823`); export.json/csv/pdf; POST/DELETE `/cost-decisions/{id}/share`;
approve/reopen `/{id}/approve`. Expected: immutable artifact pinned to its rate version.

**W9 — RFQ / supplier evidence package.**
Entry: `/rfq-packages`. Steps: POST `/rfq-packages` with decision ids → download.zip.
Expected: local ZIP, no live supplier send, raw CAD opt-in, stale/unvalidated warnings.

**W10 — Org setup → invite → SSO/SCIM.**
Entry: `/settings/organization` (or `/api/v1/orgs`). Steps: create org (analyst),
invite (org admin, POST `/orgs/invites`), accept (`(auth)/orgs/accept/page.tsx`,
POST `/orgs/invites/accept`), role PATCH `/orgs/members/{id}/role` (org admin);
SSO via `/auth/saml|oidc|google`; SCIM provisioning at `/scim/v2/*` (org admin);
SAML group-mappings `/orgs/saml/group-mappings`. Expected: multi-user org with RBAC.

**W11 — Part identity confirm.**
Part identity is the mesh_hash (`part_key`); part-context is declared/read per
mesh_hash (`/part-context/{mesh_hash}` GET viewer / PUT analyst). Manifest adds a
THIRD declared `part_id` identity separate from geometry-derived catalog parts
(`backend/main.py:301-305`). NOTE: no dedicated `/identity/confirm` route found (see gaps).

**W12 — Auth (login / signup / magic / logout).**
Entry: `/login`, `/signup`. Frontend routes POST `/api/auth/login|signup|logout`
(`app/api/auth/*/route.ts`) which set the `dash_session` cookie; backend `/auth/*`
(password, google, magic, saml, oidc). Fresh login → `/verify`.

---

## (C) ROUTES TABLE

Auth legend: **A**=platform analyst, **V**=platform viewer, **OA**=org admin,
**OM**=org member, **SA**=superadmin, **pub**=public/no-auth, **KS**=also gated by
`require_kill_switch_open`. Superadmin (rank 4) clears every `require_role` gate
(`auth/rbac.py:41-83`). RBAC source: `auth/rbac.py`. UF = user-facing (UI calls it).

### Core engine — `routes.py`, prefix `/api/v1`
| Method | Path | Auth | Purpose | UF |
|---|---|---|---|---|
| POST | /validate | A, KS | DFM validation (routing + issues + geometry) `routes.py:687` | yes (W1) |
| POST | /validate/preview-mesh | A, KS | Decimated GLB for the Stage render `routes.py:838` | yes (Stage) |
| POST | /validate/assembly | A, KS | Assembly model / GLB / per-part analysis `routes.py:1007` | yes (W3) |
| POST | /validate/quick | A, KS | Fast quick-verdict `routes.py:1103` | internal |
| POST | /validate/demo | pub, KS | Unauthed demo validation (marketing) `routes.py:1122` | site |
| POST | /validate/cost | A, KS | Glass-box should-cost + make-vs-buy, persists decision `routes.py:1762` | yes (W1) |
| POST | /validate/cost/demo | pub, KS | Unauthed demo cost (marketing) `routes.py:1849` | site |
| POST | /validate/repair | A, KS | Mesh repair + re-analysis `routes.py:1912` | yes |
| GET | /rule-packs | V | Industry rule packs `routes.py:1949` | yes |
| GET | /processes | V | Process→material/machine map `routes.py:1971` | yes |
| GET | /shops | V | Bindable per-shop calibration profiles `routes.py:1981` | yes (cost opts) |
| GET | /materials | V | Material reference library `routes.py:1997` | yes |
| GET | /machines | V | Global AM reference catalog `routes.py:2019` | yes |

### Analyses / history / share / pdf
| Method | Path | Auth | Purpose | UF |
|---|---|---|---|---|
| GET | /api/v1/analyses | V | List analyses (cursor) `history.py:28` | yes |
| GET | /api/v1/analyses/{id} | V | Analysis detail `history.py:87` | yes |
| POST | /api/v1/analyses/{id}/share | A | Create share link `share.py:30` | yes |
| DELETE | /api/v1/analyses/{id}/share | A | Revoke share `share.py:44` | yes |
| GET | /api/v1/analyses/{id}/pdf | V | DFM report PDF `pdf.py:25` | yes |
| GET | /s/{short_id} | pub | Public shared analysis `share.py:58` | yes (public) |

### Cost decisions — prefix `/api/v1/cost-decisions`
| Method | Path | Auth | Purpose | UF |
|---|---|---|---|---|
| GET | "" | V | List saved decisions `cost_decisions.py:69` | yes |
| GET | /compare | V | Structured diff of two decisions `cost_decisions.py:113` | yes (Compare) |
| GET | /{id} | V | Full decision detail `cost_decisions.py:134` | yes |
| POST | /{id}/approve | A | Sign off (artifact immutable) `cost_decisions.py:162` | yes |
| DELETE | /{id}/approve | A | Reopen signoff `cost_decisions.py:180` | yes |
| GET | /{id}/pdf | V | Cost report PDF `cost_decisions.py:197` | yes |
| GET | /{id}/export.json | V | Raw glass-box JSON `cost_decisions.py:217` | yes |
| GET | /{id}/export.csv | V | Estimates CSV `cost_decisions.py:240` | yes |
| POST | /{id}/share | A | Public share link `cost_decisions.py:259` | yes |
| DELETE | /{id}/share | A | Revoke share `cost_decisions.py:272` | yes |
| GET | /s/cost/{short_id} | pub | Public sanitized cost decision `cost_decisions.py:286` | yes (public) |

### Catalog / portfolio / triage — prefix `/api/v1/catalog`
| GET "" | V | Org parts×decisions grid `catalog.py:46` | yes (Catalog) |
| GET /portfolio | V | Program roll-up + exposure `catalog.py:186` | yes (Programs) |
| GET /triage | V | Triage projection `catalog.py:238` | yes |
| GET /makeability | V | Makeability buckets (GROUP BY) `catalog.py:304` | yes (Triage) |
| GET /capability-investment | V | One-acquisition unlock ranking `catalog.py:408` | yes (Triage/Acq) |

### Part context — prefix `/api/v1/part-context`
| GET /{mesh_hash} | V | Read declared world/lineage `part_context.py:58` | yes |
| PUT /{mesh_hash} | A | Declare env/program/volume `part_context.py:75` | yes (W2/W6) |

### Machine inventory — prefix `/api/v1/machine-inventory`
| GET /catalog | V | Static machine templates `machine_inventory.py:148` | yes |
| GET /import/template | V | CSV header `machine_inventory.py:163` | yes |
| GET /shop-capabilities | V | Shop secondary ops `machine_inventory.py:180` | yes |
| PUT /shop-capabilities | A, KS | Set shop caps `machine_inventory.py:194` | yes |
| POST /import | A, KS | CSV bulk import `machine_inventory.py:223` | yes |
| POST "" | A, KS | Create machine `machine_inventory.py:276` | yes |
| GET "" | V | List owned machines `machine_inventory.py:303` | yes (W1/W5) |
| GET /{id} | V | Machine detail `machine_inventory.py:319` | yes |
| PATCH /{id} | A, KS | Update machine `machine_inventory.py:336` | yes |
| DELETE /{id} | A, KS | Delete machine `machine_inventory.py:363` | yes |

### Manifest — prefix `/api/v1/manifest`
| POST /import | A, KS | Bulk manifest/BOM ingest `manifest.py:98` | yes (W4) |
| GET "" | V | Declared inventory `manifest.py:152` | yes |
| GET /coverage | V | Geometry-coverage headline `manifest.py:171` | yes |
| GET /import/template | V | CSV template `manifest.py:186` | yes |

### Ground truth — prefix `/api/v1/ground-truth`
| POST "" | A, KS | Add record `groundtruth.py:170` | yes (W7) |
| GET "" | V | List records `groundtruth.py:202` | yes |
| GET /{id} | V | Record detail `groundtruth.py:216` | yes |
| POST /recalibrate | A, KS | Recalibrate on held-out residuals `groundtruth.py:233` | yes |
| GET /import/template | V | CSV template `groundtruth.py:265` | yes |
| POST /import | A, KS | CSV import `groundtruth.py:290` | yes |

### Governed libraries (viewer reads; **OA** mutations)
Rate: `/api/v1/rate-library` GET(""/effective/{id}/diff) V; POST/PATCH/DELETE/archive/publish OA (`rate_library.py:74-260`).
Shop: `/api/v1/shop-library` GET V; POST/PATCH/DELETE/archive/publish OA (`shop_library.py:76-206`).
Material: `/api/v1/material-library` GET(""/effective/{id}) V; POST/PATCH/DELETE/archive/publish OA (`material_library.py:74-234`).

### Governance — prefix `/api/v1/governance`
| POST /change-requests | OM | Propose change `governance.py:66` | yes |
| GET /change-requests | V | List `governance.py:104` | yes (Home/Calib) |
| GET /change-requests/{id} | V | Detail `governance.py:121` | yes |
| POST /change-requests/{id}/approve | OA | Approve→publish `governance.py:137` | yes |
| POST /change-requests/{id}/reject | OA | Reject `governance.py:178` | yes |

### Notifications — `/api/v1/notifications` (all V): GET "" `notifications.py:21`; POST /{id}/read `:53`; POST /read-all `:75`. UF yes.

### Integrations — prefix `/api/v1/integrations`
| GET /connectors | V | Connector registry `integrations.py:96` | yes |
| GET /credential-profiles | OA | List `integrations.py:106` | yes |
| POST /credential-profiles | OA | Create `integrations.py:123` | yes |
| GET /credential-profiles/{id} | OA | Detail `integrations.py:147` | yes |
| POST /credential-profiles/{id}/probe | OA | Dry-run probe `integrations.py:160` | yes |
| DELETE /credential-profiles/{id} | OA | Delete `integrations.py:173` | yes |
| POST /runs | A | Start run `integrations.py:187` | yes |
| GET /runs, /runs/{id} | V | Run ledger `integrations.py:224,253` | yes |

### RFQ packages — `/api/v1/rfq-packages`: POST "" A `rfq_packages.py:40`; GET "" V `:65`; GET /{id} V `:78`; GET /{id}/download.zip V `:91`. UF yes.

### Batch (no prefix): POST /batch A `batch_router.py:59`; GET /batches V; GET /batch/{id} V; GET /batch/{id}/items V; GET /batch/{id}/results/csv V; POST /batch/{id}/cancel A. UF yes (app).

### Reconstruct (no prefix): POST /reconstruct A `reconstruct_router.py:26`; GET /reconstructions/{id}/mesh.stl V `:80`. Jobs `/api/v1/jobs/{id}` V, `/{id}/result` V. UF yes (app).

### Org lifecycle — prefix `/api/v1/orgs`
| POST "" | A, KS | Create org `org_routes.py:142` | settings |
| GET "" | V | List my orgs `org_routes.py:160` | yes |
| POST /switch | V, KS | Switch active org `org_routes.py:172` | yes |
| GET/POST /saml/group-mappings | OA | SAML group→role map `org_routes.py:189,202` | settings |
| DELETE /saml/group-mappings/... | OA | Remove mapping `org_routes.py:237` | settings |
| POST /invites | OA, KS | Invite member `org_routes.py:268` | settings |
| GET /invites | OA | List invites `org_routes.py:302` | settings |
| POST /invites/accept | V, KS | Accept invite `org_routes.py:315` | yes (accept page) |
| DELETE /invites/{id} | OA, KS | Revoke invite `org_routes.py:345` | settings |
| GET /members | OV(viewer), | List members `org_routes.py:362` | yes (Calib) |
| PATCH /members/{id}/role | OA, KS | Change org role `org_routes.py:375` | settings |
| DELETE /members/{id} | OV+, KS | Remove member `org_routes.py:401` | settings |

### Admin — prefix `/api/v1/admin` (org-admin unless noted)
| GET /users | OA | List org users `admin_routes.py:95` | Calib |
| GET /users/{id} | OA | User detail `admin_routes.py:194` | Calib |
| PATCH /users/{id}/role | OA | Set platform role (not own, not superadmin, in-org only) `admin_routes.py:260` | Calib |
| POST /users/{id}/deactivate | **SA** | Deactivate `admin_routes.py:337` | admin |
| POST /users/{id}/reactivate | **SA** | Reactivate `admin_routes.py:361` | admin |
| POST /users/{id}/revoke-sessions | **SA** | Revoke sessions `admin_routes.py:382` | admin |
| GET /usage-summary | OA | Usage counters `admin_routes.py:412` | Calib |
| GET /webhook-deliveries | OA | Delivery log `admin_routes.py:487` | Calib |
| GET /ops/queue-health | OA | Queue health `admin_routes.py:532` | admin |
| GET /audit-log | OA | Immutable audit (CSV) `admin_routes.py:549` | Calib |

### API keys — `/api/v1/keys` (`keys_api.py`): GET, POST, POST /{id}/rotate, DELETE /{id}, PATCH /{id}. Roles via require_api_key. UF yes (Calib/dev settings).

### Auth (prefix `/auth` unless noted)
password: POST /signup `:145`, /login `:180`, /logout `:239`, /logout-all `:248`, GET /me `:259` (`auth/password.py`, unconditional).
google: GET /google/start, /google/callback (`oauth.py:45,63`). magic: POST /magic/start, GET /magic/verify (`magic_link.py:82,126`).
saml (`/auth/saml`): GET /login, POST /acs, GET /logout, POST /sls, GET /metadata (`saml.py`). oidc (`/auth/oidc`): GET /login, /callback (`oidc.py:211,244`).
Gated by `AUTH_MODE` (`backend/main.py:333-345`).

### SCIM 2.0 — prefix `/scim/v2` (all **OA**, `scim.py`): ServiceProviderConfig, Schemas, ResourceTypes, Users (GET/POST/{id} GET/PUT/PATCH/DELETE), Groups (GET/{id} GET/PATCH). Mounted at IdP path for Okta/Entra.

### Health / metrics / corpus
GET /health (pub, 200/503 degraded) `health.py:32`; GET /health/deep `:148`. GET /metrics (pub, `METRICS_ENABLED`, private-network) `metrics.py:88`.
Corpus (dev only, `LABELING_ENABLED=1`, localhost, NO auth): `/api/v1/corpus/parts`, `/parts/{id}/mesh.stl`, `/parts/{id}`, POST /labels, GET /progress (`corpus_router.py:183-365`).

### Frontend BFF routes (`frontend/src/app/api/`)
POST /api/auth/login, /signup, /logout (`api/auth/*/route.ts`) set `dash_session`. `/api/proxy/[...path]` forwards all data calls with the cookie. `/scalar`, `/robots`, `/sitemap`, `/opengraph-image`.

---

## (D) ROLES & PERMISSIONS MATRIX

Two orthogonal axes (`auth/rbac.py:1-23`):
- **Platform role** `users.role` (`require_role`): viewer(1) < analyst(2) < admin(3) < superadmin(4). Superadmin provisioned out-of-band, never self-service assignable (`rbac.py:45-49`).
- **Org role** `memberships.org_role` (`require_org_role`): viewer(1) < member(2) < admin(3), scoped to the caller's own org; superadmin bypasses org boundary entirely (`rbac.py:120-170`).

| Capability | viewer | analyst | admin(platform) | org member | org admin | superadmin |
|---|---|---|---|---|---|---|
| Read analyses/catalog/records/portfolio/machines/rates/notifications | ✅ | ✅ | ✅ | (needs platform V) | ✅ | ✅ |
| Run /validate, /validate/cost, /assembly, /repair, batch, reconstruct | ❌ | ✅ | ✅ | — | — | ✅ |
| Declare part-context (PUT), machine CRUD/import, manifest/ground-truth import, recalibrate | ❌ | ✅ | ✅ | — | — | ✅ |
| Share/approve cost decisions, RFQ create, integration runs | ❌ | ✅ | ✅ | — | — | ✅ |
| Propose governance change-request | — | — | — | ✅ | ✅ | ✅ |
| Approve/reject governance; publish rate/shop/material versions | — | — | — | ❌ | ✅ | ✅ |
| Org invites/members/role, SAML group-map, SCIM, credential-profiles, admin usage/audit | — | — | — | ❌ | ✅ | ✅ |
| Deactivate/reactivate user, revoke sessions | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ only |

**Enforcement:** FastAPI `Depends(require_role(...))` / `Depends(require_org_role(...))`
per route (see §C anchors); 403 `insufficient_role` / `insufficient_org_role`
(`rbac.py:73-80,147-158`). UI gates: Verify layout hard `verifySession()` redirect
to `/login` (`(verify)/layout.tsx:26`); Calibration screen surfaces member/admin
sections only when admin (`calibration-screen.tsx:16`).

**Cross-tenant/org isolation points:** every org-scoped read/write scopes by
`ctx.org_id` from `require_org_role` (`rbac.py:160-168`); admin role PATCH refuses
cross-org targets with 404 (`admin_routes.py:287-297`, "cannot touch a user outside
their org"); catalog/portfolio/records/part-context all org-scoped; ground truth
"tenant-scoped, never pooled" (`(site)/security/page.tsx:155`). `kill_switch`
(`require_kill_switch_open`) globally freezes mutations when tripped.

---

## (E) PRODUCT PROMISES (quoted + cited + how to validate)

**P1 — Makeability verification (the core thesis, cost is a byproduct).**
> "Can this part be made — on your machines, in materials that survive its world — and what will it really take? Should-cost is one artifact inside the verdict, never the destination." — `(site)/layout.tsx:25`; echoed `(verify)/verify/page.tsx:7`.
Validate: W1 produces a verdict that names machine-fit + material survival + effort; should-cost is subordinate, never the headline.

**P2 — Deterministic DFM (measured facts, reasoning shown).**
> "The engine reads the part itself — volume, bounding box, wall thickness, watertightness. These are MEASURED facts taken directly from your CAD… parsed in-process and discarded." — `(site)/method/page.tsx:276`. "Every DFM blocker states the measured value against the threshold and points at the offending faces." — `method/page.tsx:308`.
Validate: same file → same findings; each blocker carries measured vs required + `affected_faces` + citation (`lib/api.ts:44-58`); NL refusal for nondeterministic asks (`verify-screen.tsx:27`).

**P3 — Glass-box should-cost with provenance (MEASURED/USER/SHOP/DEFAULT).**
> "No sealed total. Five drivers — material, machine, labor, setup, nesting — each measured off the geometry or bound to your shop's real rates, each carrying its source." — `(site)/page.tsx:260`. "Every driver on the table, provenance-tagged and sourced, with line items summing visibly to the unit cost — no naked totals. Anything generic is flagged DEFAULT." — `method/page.tsx:352`.
Provenance enum `MEASURED|SHOP|USER|DEFAULT` (`lib/api.ts:593`); filled dot = grounded, hollow ring = default (`method/page.tsx:544-554`). Validate: every driver has a provenance + source string; line items reconcile to unit cost on screen.

**P4 — Material-survival environment gate with cited standards.**
> "fails NACE MR0175" — `(site)/page.tsx:344`. Cost route returns `environment_excluded` + `environment_exclusion_reason` "usually naming the governing standard" (`lib/api.ts:672-675`); env round-trip cites "NACE MR0175 / HDT" (`lib/verify/run.ts:40`).
Validate: declare a sour/hot world (W2) → a process/material pair is excluded with a real standard citation, not a bare fail.

**P5 — Make-vs-buy crossover (honest "if redesigned").**
> "Tool up beyond — stated honestly as 'if redesigned.'" — `(site)/page.tsx:318`; live crossover dial fitted from real costed quantities (`_home/crossover-dial.tsx:10`).
`CostDecision.crossover_qty` + `if_redesigned` (`lib/api.ts:698-707`). Validate: crossover qty is engine-computed; acquisition modal (W-Acq) anchors capex on it; standalone capex WITHHELD (`acquisition-modal.tsx:18-19`).

**P6 — Real tessellated render (never faked geometry).**
Stage streams a real decimated GLB from `/validate/preview-mesh` with honest
decimation provenance headers (`x-mesh-*`, `proxy/route.ts:32-37`,
`lib/verify/preview-mesh.ts:8-12`). Validate: shape shown matches uploaded bytes;
catalog previews WITHHELD (neutral glyph) because production serves no org mesh
(`catalog-screen.tsx:15-18`).

**P7 — Assembly-context analysis.**
Per-part DFM + should-cost + real interference on world-positioned solids
(`assembly-panel.tsx:3-18`, `/validate/assembly?format=analysis`). Validate: quantity
labelled FACT, material DEFAULT, interference labelled "a signal, NOT a fault".

**P8 — Zero-egress / geometry never leaves.**
> "geometry never leaves your environment, run it where your program requires, and every answer is defensible." — `(site)/security/page.tsx:34`. "GEOMETRY NEVER LEAVES YOUR ENVIRONMENT" `:173`; "controlled environment · zero egress · export-controlled programs" `:202`; "Parsed in-process, measured, then discarded" `:262`.
Backend: "IP-local compute: the CAD is parsed and costed in-process and no network call is made (the costing layer opens zero sockets)… the raw CAD blob is never retained." — `routes.py:1819-1826`. Validate: no outbound socket during cost; only the decision (no CAD) persisted.

**P9 — Honest gates / no unmeasured accuracy claims.**
> "We don't print accuracy figures we haven't measured on your parts." — `security/page.tsx:345`; "±40% is what an uncalibrated should-cost honestly knows… not a measured accuracy dressed up as one." — `method/page.tsx:600-601`.
`CostConfidence` stays `assumption-band` / `validated:false` / label "assumption-based, not yet validated" until real residuals accrue (`lib/api.ts:604-624`). Validate: bands render HATCHED (n=0) until W7 recalibrate flips them; recalibrate REFUSES below the residual floor (`calibration-screen.tsx:11-13`).

**P10 — Governed, versioned, pinned records.**
Records are "immutable and PINNED to the rate version they were computed under — a calibration switch never rewrites them." — `records-screen.tsx:12-14`. Validate: change a rate version → old records unchanged, still cite their pinned version.

---

## (F) FAILURE / BRANCH SURFACES

| Surface | Where handled | Expected behavior |
|---|---|---|
| Invalid / wrong-type upload (magic mismatch) | `upload_validation.py:53-70` (validate_magic) | 400 with static detail (e.g. "missing ISO-10303-21 header"); user content never reflected |
| Huge upload (triangle cap) | `upload_validation.py:28-35` `MAX_TRIANGLES=2M` (demo 500k); `_read_capped` `routes.py:726` | Rejected before full parse |
| Empty file | upload_validation / read cap | 400 structured error |
| Broken geometry (vol<=0 / non-watertight) | Cost G1 gate → 400 `GEOMETRY_INVALID` with structured `geometry` body (`lib/api.ts:790-797,870-876`; `lib/verify/run.ts:124-134`) | Walk stops at G1; UI renders repair card with measured geometry, not a bare error |
| Periodic-surface / unanalyzable part | DFM `scope:"whole_part"` when unlocalizable (`lib/api.ts:56-58`); per-part assembly error | Honest whole-part finding / per-part error, never faked faces |
| No environment declared | `run.ts:160-176`; verification block absent | Env gate renders honest unknown / "not evaluated", never a fabricated verdict |
| No machines owned | `run.ts:143-151`; empty owned processes | Fully-loaded costing (not marginal); makeability "not evaluated"; machines screen "declare your floor" empty state |
| Backend down / 5xx | `apiClient.fetch` retry+backoff, Sentry, toast "Server error" (`lib/api.ts:317-325`) | Retries reads, honest toast, no fake data |
| Degraded backend | `/health` returns 503 `status:"degraded"` (`health.py:32-50`); `/status` page | Health surfaces degraded tier |
| Rate limited (429) | `apiClient` 429 branch, `Retry-After` toast (`lib/api.ts:309-314`); slowapi limits (e.g. `60/hour;500/day` on validate/cost) | Toast with retry seconds, no retry |
| Expired / missing session | `verifySession()` redirect to /login (`(verify)/layout.tsx:26`, `lib/dal.ts`); proxy sends empty cookie → 401 | Redirect to login |
| Non-admin hitting admin | `require_org_role`/`require_role` 403 `insufficient_(org_)role` (`rbac.py:73-80,147-158`); Calibration hides member/admin sections when not admin | 403 / hidden UI |
| Kill switch tripped | `require_kill_switch_open` on all mutations (`backend/main.py` deps) | Mutations frozen, reads continue |
| Malformed JSON response | `apiClient.fetchJson` catch (`lib/api.ts:342-346`) | Sentry + toast "Unexpected server response" |
| Network timeout | `apiClient.fetch` catch (`lib/api.ts:294-302`) | Toast "Connection timed out" |
| Verify flag off | `(verify)/layout.tsx:25` `notFound()` | /verify 404, rest of app byte-identical |
| Stale verdict (machine changed after compute) | Triage counts + flags stale (`triage-screen.tsx:12-14`) | Counted, flagged, never served as fresh |

---

## (G) AREAS NOT FULLY MAPPED (honest gaps)

1. **`/identity/confirm` route** named in the task does not exist as a discrete
   endpoint. Part identity = mesh_hash `part_key` used across catalog/part-context;
   the closest "confirm" is the manifest declared-`part_id` reconciliation
   (`backend/main.py:301-305`). Not verified whether a confirm-UI exists.
2. **`verify-screen.tsx` interior** (the verdict walk render logic, ~hundreds of
   lines) read only through line 55 (imports/docstring) plus its lib deps
   (`lib/verify/ask.ts`, `derive.ts`, `verification.ts`, `scrub.ts`). The exact
   on-screen copy for each gate/step was inferred from docstrings + the `ask.ts`/
   `verification.ts` API, not line-by-line.
3. **`connectors` / SAP-PLM adapters** — I mapped the integrations HTTP surface and
   registry but not each connector adapter's behavior (`services/connector_adapters.py` not opened).
4. **Legacy `(app)` dashboard internals** — page purposes captured from headers;
   `PartWorkspace`, glass-box view components, and workspace hero not deeply read.
5. **SAML/OIDC/SCIM internals** — route inventory + auth gating captured; the
   assertion-parsing / provisioning bodies (`services/scim_service.py`,
   `org_saml_service.py`, `auth/saml.py` beyond decorators) not fully read.
6. **Exact rate-limit numbers** verified only for `/validate` and `/validate/cost`
   (`60/hour;500/day`) and demo (`240/hour`); other routers' limiter decorators not enumerated.
7. **`require_org_role(OrgRole.viewer)` on `/orgs/members` DELETE/list** — the exact
   minimum org role for a few org routes was read from the `Depends` line; the
   in-body additional checks (e.g. self-removal, last-admin) were not traced.
8. Marketing pages surveyed for promises via grep; not every `(site)/teams/*` page
   read in full — additional narrower claims may exist there.
