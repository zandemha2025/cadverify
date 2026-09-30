# Visible-feature verification ledger

Updated 2026-09-29. The goal is **not complete**. A page rendering, a synthetic provider fixture or a green unit test is not production proof of its whole workflow. This ledger groups the currently identified user-facing capabilities; remaining controls and branches must be expanded during the audit.

Production is Render, currently `09555c1`. The subsequent audit branch has not been deployed. Prior release evidence is in [release-handoff.md](release-handoff.md); reproduced defects and fixes are in [post-deploy-findings.md](post-deploy-findings.md).

| User-facing capability | Evidence / current state | Work still required |
| --- | --- | --- |
| Signup, password login, bad-password recovery, logout | Real disposable Render account completed these flows | Recheck after the next release; legacy Fly accounts remain separate |
| Protected pages and role boundaries | Prior CI journeys and API tests passed | Repeat representative production analyst/viewer boundaries |
| Email login and invitation delivery | No controlled inbox receipt verified; email login absent from deployed UI | Authorized inbox, provider configuration and actual receive/click proof |
| Company SAML/OIDC sign-in | Organization screen explicitly reports both disabled | Authorized IdP tenant and real sign-in/session/logout proof |
| SCIM lifecycle and group-to-role mapping | Synthetic CI lifecycle only | Real authorized IdP provisioning and revocation |
| Organization create/switch/invite/member management | CI role and membership journeys | Production invitation acceptance, access changes and failure recovery |
| API keys, reveal-once, revoke, usage | Prior CI enterprise journey | Live key request and revocation proof using disposable credentials |
| Session/security settings | Page and API coverage | Exercise every visible control and verify resulting access behavior |
| Real STEP/STP upload | Native Render uppercase `.STP` upload succeeded | Recheck corrected results after deployment |
| STL, IGES/IGS, AP203/AP242 inputs | Prior local/CI CAD corpus, 33 pinned NIST STEP files | Broader production format matrix and known-dimension controls |
| Unsupported native CAD and malformed files | Prior local/CI refusal/retry tests | Production bounded errors without losing the workspace |
| STEP assemblies | Local/CI real 18-part assembly evidence | Production component selection and assembly export/retry |
| Verify 3D preview | Prior live/core and CI proof | File replacement, large meshes, error recovery and all viewing controls |
| Analyze/cost 3D preview | Missing on live STEP; fixed locally | Deploy and repeat real-file render/inspection proof |
| Locate a DFM finding | Local preview now uses analysis mesh and exact fingerprint guard | Real STEP selection passes locally; cached-mesh mismatch recovery and production proof remain |
| Dimensions, volume, hole measurements | Known STEP: 20×15×10 mm, 6 mm bore; volume error 0.002581% | More independent shapes, orientations, thin walls and units |
| Small-feature warnings | Live false positive; corrected local tests retain 0.39 mm fail / 0.41 mm pass | Deploy; evaluate freeform boundaries and feature coverage |
| Casting corner warnings | Live smooth-bore false positive; corrected local coarse/fine controls | Deploy and expand representative cast geometry |
| Flat feature detection | Fixed locally: real STEP now has six planes + one bore (026) | Deploy and extend non-cylindrical/freeform controls |
| Remaining DFM process checks and suitability | Existing tests/trap corpus; bounded known-part evidence | Independent accuracy cases for every visible check and score |
| Source units and scale warnings | Fixed STEP/IGES double scaling across DFM/cost/preview (033); real browser STEP remains 20×15×10 mm with inches selected. Explicit STL conversion regressions pass | Canonical calibration-source identity fixed locally with mm/inch storage/cache separation (035); deploy and finish unitless STL inference/confirmation |
| Should-cost quantities/material/region/shop choices | Real STEP across five quantities: all 40 calculated prices now match slider/chart points; quantity-specific lead times and approximation labels fixed (041) | Deploy; remaining material/region/shop combinations and multi-process crossover advice |
| Price assumptions, markup, overhead and driver math | Native real STEP: 25% markup scales all 16 estimates correctly; doubled labor doubles only labor/setup and all line items reconcile. Invalid rates now refused (038); markup/fallback descriptions and provenance corrected (040) | Deploy; broader independent examples and calibrated shop data |
| Real quote accuracy and confidence | UI identifies generic/default, unvalidated estimates | Actual authorized quote/actual datasets and out-of-sample validation |
| Saved cost decision integrity | Units/version collision fixed locally (024); native saved $70/hour decision JSON exactly matches the live export (038) | Production save/reopen/export must match each live result |
| Glass Box overrides and scenario comparison | Native negative/malformed input rejection, correction, reset, save and recall pass. Unsaved draft/result mismatch fixed (039): quantity 123 draft no longer contaminates saved quantity 50 / $3.80 | Deploy; remaining input combinations and comparison branches |
| Decision approve/reopen/stale governance | Local real-STEP outcome/note/approval persisted into exports; editing the note reopened approval | Production role transitions and rate-change staleness |
| History and persisted analysis retrieval | Live saved record reopened and survived reload | Full detail, filters, old/new engine distinction and error recovery |
| PDF, JSON and CSV exports | Local native downloads of real STEP: 16 cost rows reconcile, Unicode notes/approval preserved; cost columns/headings fixed (029). Seven-page DFM PDF matches saved geometry and clarifies candidate-process scope (031) | Repeat production downloads and broader cases after deployment |
| Public shares and revocation | Existing test coverage | Real links, access limits, revocation and tenant-data boundaries |
| RFQ package create/review/download | Local real-STEP create/download exposed historical JSON/current-PDF mismatch; fixed and same package re-downloaded successfully (030) | Deploy; broader multi-item/raw-CAD and production proof |
| Batch ZIP upload, progress and retry | Real local worker: mixed STEP/STL batch, useful malformed-file error, explicit native-file skip, retry with corrected ZIP + manifest, matching CSV and saved geometry. Cancellation retains 3 completed results and skips 17 queued files. UI concurrency mismatch fixed (032) | Deploy; repeat production batch, webhook and worker/storage failure recovery |
| Direct object-storage batch input | Local Moto proof only | Authorized real storage configuration and completed worker run |
| CSV SAP/PLM manifest imports | Real dry-run exposed hidden row errors; local recovery fixed | Production dry-run, import, duplicate/update and resulting records |
| Quote/actuals CSV ingestion | Local native mm/inch demo import, precise invalid-row feedback/retry, deduplication and PostgreSQL readback pass (035/036); demo records correctly cannot validate | Deploy; actual authorized quote data and calibrated accuracy remain open |
| SAP S/4HANA API | Product-read transport and admin credential/test/revoke UI added locally (027); CSV evidence remains separate | BOM transport, import/reconciliation and authorized tenant proof |
| PTC Windchill API | Product-read transport and credential UI added locally (027) | BOM transport, import/reconciliation and authorized tenant proof |
| Connector credential probe | Actual bounded authenticated product read; DNS/IP pinning, TLS, redaction and actionable failure tests pass locally. Browser save/test-failure/revoke passes for both vendors | Deploy, configure encrypted storage (028), and verify actual authorized vendor success. No real-tenant success is claimed |
| Machine inventory, rates and calibration | Prior enterprise CI | Live declared records, approval rules, persistence and cost effects |
| Parts/programs/portfolio views | Prior CI bounded math and navigation | Real record editing, filtering and aggregate reconciliation |
| Design Studio generation/edit/version/STEP export | CI passes 14 steps and all 12 evidence contracts; mobile readiness race fixed (034). Local real plate renders at 390 px without overflow | Fresh CI, production generation/geometry/retry/export; local Chrome direct STEP download blocked after HTTP 200 |
| Reconstruction and labeling | Production health reports reconstruction backend unavailable | Inspect visible availability and configure/verify actual inference |
| Search, navigation, notifications and theme | Prior journeys; navigation fix deployed | All menu branches, search results and notification actions |
| Responsive/accessibility behavior | Prior 20 local cases; two Render pages checked at 390 px. Calibration overflow fixed locally with phone-width upload/recalibration proof (037) | Deploy; remaining functional pages, keyboard/focus and dialog flows |
| Public product, team, method, docs and API-reference pages | Prior route sweep and selected corrections | Check every claim and interactive example against current behavior |
| CAD retention/security statements | Product and Method copy corrected locally (025) | Deploy and finish the wider public-claim audit |
| Production URL and old deployments | Render works; Fly DB and disabled Vercel unresolved | Provider recovery/migration or intentional retirement/redirects |
| Deployment repeatability and image security | Manual release worked; auto-deploy and HIGH image findings open | Resolve findings 016/017 and rerun release gates |

External dependencies have been requested once: an authorized receiving inbox and company-IdP/SAP/Windchill test tenants. No credentials should be pasted into chat. Internal fixes and verification continue while those are pending.
