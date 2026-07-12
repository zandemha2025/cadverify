# CadVerify — Human-Sim Validation (Security deep-dive + 3 shipped features)

- **Date:** 2026-07-11
- **Branch / HEAD:** `claude/resume-review-oxqw0l` @ `0db0eb8` (fillet + chamfer detectors)
- **Stack:** backend `uvicorn main:app` on :8097, frontend `next dev` on :3097, Postgres cluster `fix` on :5433 (fresh UTF8 db `cadverify_hs`, `alembic upgrade head` → 0037). `/health` = `{"status":"ok","postgres":true}`. Signup smoke = 200 + session.
- **How exercised:** real Chromium (Playwright) driving `http://localhost:3097`; authenticated actions go through the app's same-origin proxy (`/api/proxy/* → backend /api/v1/*`) carrying the httpOnly `dash_session` cookie — i.e. the real product path, not raw backend curls. Screenshots in this directory.

---

## A. SECURITY DEEP-DIVE — Score: **4.5 / 5**

Skeptical-reviewer note: most of the security surface is backend and already unit-covered; this run exercises what is reachable live and confirms it holds end-to-end through the real UI/proxy.

| Check | Result | Evidence |
|---|---|---|
| Signup → session cookie is **httpOnly** | PASS — `dash_session` `httpOnly=true, sameSite=Lax`; `document.cookie` from JS is empty (not readable to scripts) | `sec_01_orgA_signed_in.png` |
| Unauthenticated request to a protected route is **rejected** | PASS — `GET /api/proxy/cost-decisions` with no session → **HTTP 401** `{"code":"auth_missing"}`; UI visit to `/cost-decisions` → redirect to `/login?next=/cost-decisions` | `sec_02_unauth_redirect_login.png`, `sec_02b_unauth_api.png` |
| Logout clears the session | PASS — after `POST /api/auth/logout`, `dash_session` absent; subsequent `GET /cost-decisions` → **401**; UI redirects to login | `sec_03_logout_redirect.png` |
| **Tenant isolation (key adversarial check)** | PASS — Org A creates cost-decision `01KX77T86R…`; Org A reads its own → **200**; **Org B reads the same id → 404 "Cost decision not found"**, no Org A email/data in the response; Org B's own list does **not** contain Org A's id | `sec_04_tenant_isolation.png`, `sec_04b_tenant_isolation_ui.png` |
| Org-admin gating | PARTIAL / not fully exercised live — each signup provisions a **new single-member org with that user as `admin`** (confirmed: `GET /orgs/members` returns only the caller, `org_role":"admin"`). There is no second, non-admin member in an org without going through the invite flow, so in-org privilege gating (member removal / SSO / SAML) could not be driven from a clean signup. The cross-tenant boundary (the real adversary) is fully denied above. | see note |
| Input safety (junk / malformed upload) | PASS — `junk.txt` (text/plain) → **HTTP 400** structured error, **no** stack trace / internal paths leaked; garbage bytes with an odd filename → **HTTP 400**. No 500, no internals to the client. | `sec_05_input_safety.png` |

**Why 4.5 and not 5:** every check run passed cleanly and the tenant-isolation boundary is airtight, but in-org admin gating could not be exercised end-to-end from the UI (needs an invited second user), so I won't claim it as verified-live.

---

## B. THREE SHIPPED FEATURES

### 1. Material from CAD (commit `1c41f23`) — **PARTIAL (engine PASS, on-screen provenance chip FAIL)**

- **Material-from-file works — PASS.** `cube_with_material.step` uploaded with **no** material declared → engine reads the file's annotation: `material_class = "aluminum"` (default is polymer), best estimate material = **"6061-T6 Aluminum"**, should-cost **$10.65/unit on CNC 3-Axis**. Plain `cube.step` (no annotation) → `material_class = "polymer"`, material **"PP (Molded)"**, provenance DEFAULT. Verified in the UI workspace and via API.
- **Honest provenance in the engine — PASS.** The cost response carries `assumptions[].provenance = "CAD"`: `{"name":"material_class","provenance":"CAD","source":"material class = aluminum (read from the CAD file's material annotation)"}`.
- **On-screen magenta "CAD" chip — FAIL / NEW FINDING.** The chip never appears. In the verify workspace the material line renders **`material class aluminum · route hint aluminum [DEFAULT]`**, and the glass-box record's Material driver row also shows **DEFAULT**. Root cause: `frontend/src/components/verify/verify-screen.tsx:561` hardcodes `<ProvChip p="DEFAULT" />` for the material line, and no component feeds the material's CAD provenance to a `ProvChip`. Commit `1c41f23` added the CAD chip's CSS tokens, the `Provenance="CAD"` type, and `normProv()` acceptance (the plumbing), but not a render site — so a CAD-read material still visually reads **"DEFAULT / we're guessing"**, the exact outcome the commit message claims it prevents. Material identity is correct; only the on-screen provenance *label* is wrong.
- Evidence: `feat1_01_material_cad_workspace.png`, `feat1_02_record_detail.png`, `feat1_03_plaincube_default.png`, `feat1_04_api_provenance_CAD.png`, `feat1_05_api_default.png`, `feat1_06_FINDING_chip_hardcoded.png`.

### 2. Long-bar routing (commit `519f981`) — **PASS**

- Crafted a 200 × 20 × 10 mm binary-STL box, ran `POST /api/v1/validate/cost` with `material_class=aluminum` (the detector is gated non-polymer).
- Result: `routing.archetype = "long_prismatic_bar"`, `routing.recommended_process = "cnc_3axis"`, `alternatives = ["cnc_turning"]`, `decision.make_now_process = "cnc_3axis"`. Reasoning: *"Slender prismatic bar … saw to length, then 3-axis mill — 5-axis is not warranted for bar stock."* **Never routes to `cnc_5axis`.** (The only "5-axis" substring in the JSON is that exclusion sentence.)
- Evidence: `feat2_01_api_routing.png`.

### 3. Feature detection — fillets / chamfers (commit `0db0eb8`) — **PASS**

Real uploads to `POST /api/v1/validate` (feature kinds emitted as `"fillet"` / `"chamfer"`):

| Part | Detected features |
|---|---|
| `chamfered_box.stl` (20³ box, one 3 mm×45° bevel) | 7 flat + **1 chamfer** (area 84.85 ≈ 20·3·√2, dihedral in 15–75°, conf 0.73) |
| `filleted_box.stl` (20³ box, one r=3 mm rounded edge) | 15 flat, 3 cylinder_boss, **1 fillet** (radius **3.0 mm** via Kasa fit, conf 0.75) |
| `cube.step` (plain) | flat / cylinder only — **0 fillets, 0 chamfers** |
| `nist_periodic_ctc05.stp` | 341 features (195 flat, 58 boss, 88 hole) — no fillets/chamfers (it's a sharp-edged milling artifact) |

Fillets/chamfers appear on the parts that have them and a plain cube shows none — the honesty guard holds. Evidence: `feat3_01_api_features.png`.

> Note: chamfered/filleted boxes were built procedurally (trimesh `extrude_polygon`, mirroring `backend/tests/test_features_fillet_chamfer.py`) because no rounded/beveled fixture ships in `backend/tests/assets/`. Features 2 & 3 are reported from the `/validate*` JSON per the task's allowance; the app's UI feature-display surface was not separately driven.

---

## Overall product state (honest)

The core engine is solid and honest: auth, tenant isolation, and input handling all behave correctly through the real product path; the three shipped engine capabilities (material-from-file, long-bar routing, fillet/chamfer detection) all compute the right answers with correct provenance tagging in the API. The one real gap is a **UI/engine mismatch on Feature 1**: the backend correctly labels a CAD-read material `provenance=CAD`, but the frontend hardcodes the material provenance chip to `DEFAULT` (verify-screen.tsx:561) and never surfaces the plumbed magenta CAD chip — so a user sees "DEFAULT" for a value that is actually read from their file. Nothing was fabricated; the in-org admin-gating check is the only item I could not exercise end-to-end and is flagged as such.

### New findings
1. **Material CAD-provenance chip not surfaced (Feature 1).** Engine emits `provenance=CAD`; UI renders `DEFAULT`. `verify-screen.tsx:561` hardcodes `<ProvChip p="DEFAULT" />`; no render site reads the material assumption's provenance. Chip styling/type/`normProv` are shipped but unused for material. Low security risk, but it defeats the honesty goal of the commit.
2. (Minor) `cube.step` reports a `cylinder_hole` + `cylinder_boss` features for what is nominally a plain cube — worth a glance to confirm the fixture/tessellation is as intended (did not affect any pass/fail here).
