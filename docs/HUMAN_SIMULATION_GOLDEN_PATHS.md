# ProofShape human-simulation golden paths

This is the product-behavior release contract for ProofShape. A green unit or
integration suite is necessary, but it is not sufficient. Release candidates
must also be driven through the same browser surface a person uses, across the
branches below, with the visible, persisted, and numerical outcomes observed.

## What “100%” means

`LOCAL_100` means every locally executable row marked **browser** passes against
the current production build with real PostgreSQL, Redis, worker, CAD kernel,
and object storage; no row is skipped; and there are no unresolved defects,
unexpected console errors, or request failures.

`STAGING_100` additionally requires the rows marked **external** against the
deployed staging boundary with managed storage, email, Turnstile, Sentry,
identity providers, DNS/TLS, and provider failure/recovery. A simulator never
turns an external row green.

Each browser result records:

- persona and preconditions;
- exact clicks, file, dimensions, declarations, and role;
- expected URL, visible copy, and visual state;
- expected durable record, revision, status, and authorization result;
- numerical exactness or tolerance;
- screenshot, console result, network result, and recovery behavior.

## Personas and surfaces

| Persona | Primary goal | Surfaces |
| --- | --- | --- |
| Public evaluator | Decide whether ProofShape is credible and safe | Public site, team pages, method, security, developers, pilot request |
| First CAD engineer | Get from no account to the first useful manufacturing result | Signup, Day Zero, Design Studio, Verify |
| Daily design engineer | Create/revise CAD, inspect DFM, and hand off exact evidence | Design Studio, Verify, Records, History |
| Cost engineer | Produce inspectable cost and compare governed decisions | Should-cost, Decisions, Compare, PDF/CSV/share |
| Manufacturing lead | Declare the real floor and decide make/outside/acquire/redesign | Machines, Triage, Programs, Calibration |
| Sourcing lead | Build an evidence-bearing RFQ package | Decisions, RFQ packages, exports |
| Organization admin | Manage users, roles, sessions, keys, SSO, and integrations | Organization, Security, Developer, Integrations |
| Viewer/auditor | Read permitted evidence without mutation authority | Shared records, Records, role-gated organization views |
| Regulated operator | Use the private plane inside approved legal/identity boundaries | Approved IdP, GovCloud/private data plane, audit/restore controls |

## 1. Public evaluation, access, and first use

| ID | Human path | Golden visible/text outcome | Golden persisted/numeric outcome | Mode |
| --- | --- | --- | --- | --- |
| PUB-01 | Open every public, team, developer, legal, company, and status route from navigation | One ProofShape identity; route-specific heading; no CadVerify/Arcus identity, unfinished copy, overflow, blank hero, console error, or failed request | Correct HTTP status and canonical route | browser |
| PUB-02 | Repeat home and public navigation at 390 px | Menu and calls-to-action remain reachable; no horizontal page overflow | Same route state as desktop | browser |
| PUB-03 | Submit a valid pilot request | Bounded success acknowledgement; never asks for CAD or quote data | One durable receipt UUID | browser |
| PUB-04 | Omit fields, trip honeypot, and repeat the same request | Field validation or neutral bot response; no user-enumeration detail | Duplicate request reuses the receipt and does not create a second row | browser |
| AUTH-01 | Open every protected route signed out | Redirect to `/login`; no protected content flashes | Protected API calls are 401 | browser |
| AUTH-02 | Submit a weak password | `Password must be at least 8 characters.` | No user/session/org created | browser |
| AUTH-03 | Submit an unknown email/wrong password | `Invalid email or password.` | No session; no user enumeration | browser |
| AUTH-04 | Sign up with a valid local password | Redirect `/verify`; `DAY ZERO SETUP`; unified ProofShape shell | One user, organization membership, and session | browser |
| AUTH-05 | Log out, revisit a protected URL, then log back in | Login boundary returns; successful login returns to a safe local `next` path | Old logged-out session is rejected | browser |
| AUTH-06 | Request and consume a production magic link | `/magic/sent`; token disappears from URL after exchange; reuse/expiry is bounded | Exactly one session; token consumed once | external |
| AUTH-07 | Accept, expire, and revoke organization invitations | Accepted invite enters the named org/role; invalid invite never implies success | Membership created once; invalid token changes nothing | browser |
| AUTH-08 | Configure initial password and revoke all sessions | Success states that older sessions were revoked | Prior cookies fail on the next protected request | browser |

## 2. Day Zero and Verify

| ID | Human path | Golden visible/text outcome | Golden persisted/numeric outcome | Mode |
| --- | --- | --- | --- | --- |
| VER-01 | Fresh account opens Verify Home | Four honest steps: declare machines → verify first part → add program context → send actuals | All counters are zero; no seeded tenant facts | browser |
| VER-02 | Select Home, Verify, Parts, Records, Programs, Machines, Triage, Calibration | Correct active section and honest empty/populated state | No section mutates data merely by opening | browser |
| VER-03 | Open command palette, search `triage`, press Enter | Triage surface opens; focus returns predictably | No route/state corruption | browser |
| VER-04 | Open notification inbox; mark one/all read | `You're all caught up` or durable rows; actions remain understandable | Unread status survives refresh | browser |
| VER-05 | Upload `backend/tests/assets/cube.step` through Verify | Real geometry, DFM, routing, cost, provenance, and record; never `temporarily busy` or `couldn't be tessellated` on the golden file | SHA-256 `76923244d66efcbf1eb1639a26a6b4b6bd20fd73eaf44ad1b95268dddf61103a`; 20 × 15 × 10 mm ±0.1 mm; 2717.3 mm³ ±1; 1432 mm² ±2; watertight | browser |
| VER-06 | Change material, service world, and quantity | Headline process/cost agrees with the selected quantity; exclusions are visible and cited | Quantity ladder is `[1,100,1000,2000,5000,10000]`, with declared annual volume replacing the nearest interior point | browser |
| VER-07 | Choose make in-house/outside/acquire/redesign | Chosen decision appears beside the immutable cost-decision evidence | Decision note persists; cost artifact is unchanged | browser |
| VER-08 | Refresh or navigate away while verification runs | Job resumes or returns to the exact selected result; never a fake success | One durable analysis/decision for the deterministic input | browser |
| VER-09 | Repeat at 375, 768, and desktop widths; keyboard-only | All primary actions, section navigation, focus, and evidence remain reachable | Same selected record/revision on every viewport | browser |

## 3. Design Studio, revisions, and exact handoff

| ID | Human path | Golden visual/text outcome | Golden numerical/persistence outcome | Mode |
| --- | --- | --- | --- | --- |
| DES-01 | Describe an unsupported turbine/freeform shape | Explicitly limits the release to plate, L bracket, or open enclosure and directs existing CAD to Verify; never approximates | No design/revision/job created | browser |
| DES-02 | Describe an incomplete enclosure | Names exact missing fields; preserves only explicit dimensions | `100 × 60` prefills width/depth; height/wall remain reviewable defaults | browser |
| DES-03 | Interpret `120 × 70 × 8 mm plate with four 10 mm corner holes` | `Safe dimensions extracted`; local rules/no AI egress/review required | Fields are exactly `120`, `70`, `8`, `10`, `8.4`; no floating-point noise | browser |
| DES-04 | Set unsafe hole inset `5` and generate | `Hole inset must leave at least 1 mm of material at the edge.` | No design/revision/job created | browser |
| DES-05 | Generate golden mounting plate | Rectangular plate, four symmetric holes, nonblank preview or explicit WebGL fallback; Ready; STEP/download/Verify present | Envelope 120 × 70 × 8 mm; volume 64.686726 cm³, UI `64.69`; downloaded STEP SHA equals displayed evidence prefix/full response header | browser |
| DES-06 | Generate default L bracket | Recognizable perpendicular L legs; never a cylinder/box | 80 × 50 × 60 mm; thickness 6; volume 40.20 cm³ | browser |
| DES-07 | Verify the L bracket | CNC Turning is `issues`, never `pass`/route pick; DFM and cost still complete | `rotational=false`; turning absent from cost shortlist | browser |
| DES-08 | Generate default open enclosure | Open top, visible inner cavity, four walls and floor | Outer 80 × 50 × 60 mm; wall/floor 3; inner 74 × 44 × 57; volume 54.408 cm³, UI `54.41` | browser |
| DES-09 | Verify the enclosure | Route explains thin-wall enclosure; CNC Turning is rejected | Archetype `thin_wall_enclosure`; `rotational=false` | browser |
| DES-10 | Revise plate width 120 → 130 | R2 becomes current; R1 remains selectable, downloadable, and verifiable | R2 envelope 130 × 70 × 8; UI volume `70.29`; R2 hash differs; R1 hash/bytes remain exact | browser |
| DES-11 | Select R1 after R2 and choose Verify | UI says `Viewing revision 1 · current is 2`; Verify filename/result is R1, not current R2 | Query has `revision=1`; measured 120 × 70 × 8 and 64.69; imported hash equals R1 | browser |
| DES-12 | Archive, first cancel then confirm | Dialog states audit evidence is retained; cancel keeps card; confirm removes it | Active design list loses the project; retained evidence is not rewritten | browser |
| DES-13 | Repeat Design Studio at mobile width or without WebGL | Same ProofShape shell; explicit static fallback, dimensions, hash, download, and Verify remain usable | Artifact and revision identity unchanged | browser |

Generated STEP bytes are not frozen to a literal hash because the STEP header
contains generation time. The invariant is equality among stored revision SHA,
downloaded bytes, response header, and the bytes handed to Verify.

## 4. Daily engineering and commercial workflows

| ID | Human path | Golden outcome | Mode |
| --- | --- | --- | --- |
| WORK-01 | Should-cost: upload, change material/process/quantity | Unit cost, confidence, make-vs-buy, crossover, and every driver agree with the saved record; `abs(unit − round(sum(lines),2)) < $0.02`; low ≤ point ≤ high | browser |
| WORK-02 | Analyze DFM: upload and inspect finding-to-geometry links | Measured geometry; ranked routes; every finding has code, severity, remediation, process/scope, and citation when applicable | browser |
| WORK-03 | Valid batch ZIP: start, refresh, inspect, cancel | Durable progress; `(completed + failed + skipped) = total`; cancellation preserves completed work and skips pending work | browser |
| WORK-04 | Batch detail and CSV export | One row per item; exact documented headers; status/result URL/error agree with item cards | browser |
| WORK-05 | Approve, reopen, then stale a decision | Visible `Unreviewed → Approved → Unreviewed`; governed-rate publication marks prior decision `Stale` with `Re-cost before relying on this record.` | browser |
| WORK-06 | Compare A/B | Aligned quantities; delta = B − A to $0.01; percent to 0.1%, null when either source value is absent | browser |
| WORK-07 | Export PDF/JSON/CSV, create share, revoke share | Downloads equal saved evidence; share is read-only and redacts internal IDs/hashes; revoked URL is unavailable | browser |
| WORK-08 | Build and download RFQ package | Counts for approved, stale, unvalidated, and raw-CAD items match selected decisions; warnings survive ZIP/PDF | browser |
| WORK-09 | Integration dry run then import | Counts and SHA-256 displayed; dry-run changes nothing; import creates only declared rows; retry is idempotent | browser |
| WORK-10 | History → analysis detail | Filename, type, time, verdict, geometry, findings, and decision links equal persisted analysis | browser |
| WORK-11 | Reconstruction success and failure | Progress reaches a real mesh or returns to an actionable upload state; no fake preview | browser |
| WORK-12 | API key create/reveal/rotate/revoke | Full key appears once; later UI shows prefix/status only; revoked key is rejected | browser |

Literal costs are frozen only for a completely pinned organization/rate/material
fixture. Otherwise the invariant is reconciliation to the saved record and its
provenance—not a stale dollar snapshot.

## 5. Enterprise, roles, integrations, and regulated use

| ID | Human path | Golden outcome | Mode |
| --- | --- | --- | --- |
| ENT-01 | Publish governed rate card and declare floor | MJF $48/hr, CNC 3-axis $95/hr, CNC 5-axis $142/hr, DMLS $185/hr; all `USER`; authored/published state is visible | browser |
| ENT-02 | Ingest four actuals and recalibrate | Four real rows remain below floor eight; recalibration refuses and never says validated | browser |
| ENT-03 | Severe-service stainless verification | 120°C, sour service, 35 MPa remain visible; invalid materials/routes are excluded with standards citations | browser |
| ENT-04 | Assign annual volume before and after exact re-verification | Exposure withheld before exact quantity; after reverify, unit $133.58 × 12,000 = $1,602,960 | browser |
| ENT-05 | Programs rollup | One assigned verified part, annual volume, exposure, and source decision agree across Programs/Records | browser |
| ROLE-01 | Viewer opens allowed evidence then attempts admin mutation | Readable permitted evidence; admin controls absent/gated; API is 403; cross-tenant unknown ID is 404 | browser |
| ROLE-02 | Analyst/member attempts rate publication | Can verify/create decisions; cannot publish governed libraries | browser |
| ROLE-03 | Org admin invites/removes/changes mappings | Exact membership/role lifecycle and audit event; no cross-org visibility | browser |
| ROLE-04 | Two real organizations try each other's IDs/downloads | No object existence leak; reads/mutations/downloads are 404 or authorization denial | browser |
| IDP-01 | Approved SAML group mapping and login | Signed assertion accepted once; exact org role; replay/invalid audience rejected | external |
| IDP-02 | SCIM create/move/deactivate | IdP lifecycle produces exact membership state and revokes access | external |
| CONN-01 | Live ERP/PLM sandbox import | Counts, revisions, service context, hash, and idempotency agree with provider sandbox | external |
| REG-01 | SAML-only regulated login and private-plane use | Password/magic surfaces absent; approved identity enters private tenant only | external |
| REG-02 | Backup, restore, worker loss, kill switch, rollback | User sees honest degraded/retry state; alert fires; restore meets measured RPO/RTO; rollback returns canary health | external |
| REG-03 | Supplier accuracy pilot | ≥20 protected parts and ≥3 suppliers meet declared MAPE/P90/bias gates with signed customer evidence | external |

## 6. Failure and recovery matrix

| ID | Injected/real failure | Exact user oracle | Recovery oracle |
| --- | --- | --- | --- |
| FAIL-01 | Invalid CAD magic bytes/native format | `We couldn’t read this file.` and supported STL/STEP/STP/IGES/IGS guidance | Correct file succeeds without a new account/session |
| FAIL-02 | Actual tessellation failure | `This part couldn’t be tessellated.` with clean-solid re-export guidance | Re-exported valid solid proceeds; ordinary DFM/routing failures never use this copy |
| FAIL-03 | Verify capacity/429 | `Verification is temporarily busy.`; routing, DFM, and cost did not start | Retry without re-exporting CAD |
| FAIL-04 | Design queue unavailable | `Design generation is temporarily unavailable. Retry shortly.`; revision states scheduling failure | Restored worker permits explicit retry; no fake artifact |
| FAIL-05 | CAD kernel failure | `The CAD kernel could not generate this revision. Check the dimensions and retry.` | Inputs retained; revised plan creates a new immutable revision |
| FAIL-06 | Object-store failure | `The generated files could not be stored. Retry this revision.` | No partial download/Verify; restored store creates complete artifacts only |
| FAIL-07 | Batch queue unavailable | Accepted batch is marked failed with retry copy | Retry creates one durable batch; no duplicate item processing |
| FAIL-08 | Cost-history/API 503 | Visible unavailable state, not an empty-history lie | Refresh after recovery shows the same durable decisions |
| FAIL-09 | Session expiry/revocation | Redirect login; no protected content flash | Fresh login restores only authorized org data |
| FAIL-10 | Database/Redis/storage degradation | Honest degraded state and bounded retry | Health and UI recover without success-looking orphan rows |

## Automation and evidence mapping

| Gate | Command | Proves |
| --- | --- | --- |
| General human journey | `npm run test:e2e:human` | Public/auth/shell/route/mobile/real STEP browser behavior |
| Design and exact CAD | `npm run test:e2e:design-studio` | DES-01…13, exact artifact/revision/hash and Verify handoff |
| Enterprise journey | `npm run test:e2e:enterprise` | Governed rates, floor, actuals, severe service, programs, exposure |
| Roles/failures | `npm run test:e2e:p7` | Signed-out boundaries, invalid/network failures, governance, viewer denial |
| Full local gate | `npm run test:e2e:full` | All browser, corpus, load, restore, and readiness gates in sequence |

The local report may say `LOCAL_100` only when every local browser row required
for the release has a current-head artifact and zero skips. External rows remain
explicit launch prerequisites until the real accounts and environments exist.
