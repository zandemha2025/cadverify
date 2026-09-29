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
| Source units and scale warnings | Explicit mm/inch analysis tests; known automatic-inference gap | Resolve inference limitation honestly and verify UI switching |
| Should-cost quantities/material/region/shop choices | Live computation and prior CI | Compare every changed input with independent expected calculations |
| Price assumptions, markup, overhead and driver math | Prior audit corrections deployed; CI formula checks | Broader independent examples and calibrated shop data |
| Real quote accuracy and confidence | UI identifies generic/default, unvalidated estimates | Actual authorized quote/actual datasets and out-of-sample validation |
| Saved cost decision integrity | Units/version collision fixed locally (024) | Production save/reopen/export must match each live result |
| Glass Box overrides and scenario comparison | Prior synthetic/browser coverage | Live edit/re-cost/restore and exact reconciliation |
| Decision approve/reopen/stale governance | Prior CI workflow passed | Production role transitions and rate-change staleness |
| History and persisted analysis retrieval | Live saved record reopened and survived reload | Full detail, filters, old/new engine distinction and error recovery |
| PDF, JSON and CSV exports | Existing API/CI coverage; some PDF tests mock renderer | Download and inspect real production files and their numbers |
| Public shares and revocation | Existing test coverage | Real links, access limits, revocation and tenant-data boundaries |
| RFQ package create/review/download | Prior route/API coverage | Complete live package and compare each attachment to its source |
| Batch ZIP upload, progress and retry | Existing local/CI coverage | Real multi-file production batch, mixed failures and reconciliation |
| Direct object-storage batch input | Local Moto proof only | Authorized real storage configuration and completed worker run |
| CSV SAP/PLM manifest imports | Real dry-run exposed hidden row errors; local recovery fixed | Production dry-run, import, duplicate/update and resulting records |
| Quote/actuals CSV ingestion | Existing tests | Live authorized data import and calibration linkage |
| SAP S/4HANA API | No vendor transport; CSV could falsely claim API evidence | Real read-only transport, secure credential use and tenant proof |
| PTC Windchill API | Same gap as SAP | Real read-only transport, secure credential use and tenant proof |
| Connector credential probe | Configuration-presence check, not a vendor connection test | Actual authenticated vendor request and actionable errors |
| Machine inventory, rates and calibration | Prior enterprise CI | Live declared records, approval rules, persistence and cost effects |
| Parts/programs/portfolio views | Prior CI bounded math and navigation | Real record editing, filtering and aggregate reconciliation |
| Design Studio generation/edit/version/STEP export | Prior CI 15-step flow and 12 evidence contracts | Production generation, geometric accuracy, retries and exported CAD |
| Reconstruction and labeling | Production health reports reconstruction backend unavailable | Inspect visible availability and configure/verify actual inference |
| Search, navigation, notifications and theme | Prior journeys; navigation fix deployed | All menu branches, search results and notification actions |
| Responsive/accessibility behavior | Prior 20 local cases; two Render pages checked at 390 px | Remaining functional pages, keyboard/focus and dialog flows |
| Public product, team, method, docs and API-reference pages | Prior route sweep and selected corrections | Check every claim and interactive example against current behavior |
| CAD retention/security statements | Product and Method copy corrected locally (025) | Deploy and finish the wider public-claim audit |
| Production URL and old deployments | Render works; Fly DB and disabled Vercel unresolved | Provider recovery/migration or intentional retirement/redirects |
| Deployment repeatability and image security | Manual release worked; auto-deploy and HIGH image findings open | Resolve findings 016/017 and rerun release gates |

External dependencies have been requested once: an authorized receiving inbox and company-IdP/SAP/Windchill test tenants. No credentials should be pasted into chat. Internal fixes and verification continue while those are pending.
