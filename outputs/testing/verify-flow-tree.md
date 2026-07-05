# Verify Product — Branching User-Flow Tree (E2E test map)

**Purpose:** the mapped journey an agent DRIVES with Playwright to human-simulate use of the Verify web app — not unit tests, the real surface. Surface: web app at `/verify` (behind `NEXT_PUBLIC_VERIFY_UI=1`), authed analyst session via the same-origin proxy. Each node is a user decision; each branch is a path to walk. Capture a screenshot + observed behavior at every ★ checkpoint. Introduce the edge cases in **[EDGE]** — that's where real bugs hide.

## 0. Entry / auth (gate before anything)
- Load `/verify` unauthenticated → **★** should redirect to `/login` (the `(verify)/layout.tsx` gate). **[EDGE]** flag OFF → `/verify` 404s.
- Sign up / log in (email+password, the runnable path) → land on Home desk. **★** session cookie set, Home renders.
- **[EDGE]** viewer role (not analyst) → cost actions should surface "withheld — unavailable", never fake a number or 500.

## 1. Home desk (root of the tree)
Branches from Home:
- **A → Drop a part** (the core loop; §2)
- **B → Machines** rail nav (§3)
- **C → Records** rail nav (§4)
- **D → each stub surface** (Catalog / Compare / Programs / Triage / Calibration & truth) — **★** each must render the honest "NOT YET BUILT — AND NOT FAKED" IN-DEVELOPMENT frame, never a fake-interactive control.
- **★** Home KPIs: real counts or honest "[no data yet]" — no hardcoded n=0 dressed as data.
- **[EDGE]** first-run / empty org → designed empty states everywhere, not gray placeholders.

## 2. The Verify core loop (the money path — walk every branch)
Drop a part → the walk. Scenarios (the design's part chips map to real behavior):
- **2a — happy path (real STL, makeable):** drop → 3D stage renders the part → verdict walk assembles (envelope → materials → process physics → time/resources → resource cost → decide). **★** each step renders from REAL `/validate`+`/validate/cost`; the crossover scrub snaps to real engine quantities; Σ line-items = unit cost on screen; confidence band hatched + "assumption-based, n=0".
- **2b — declare the environment (the door):** toggle sour service / temp / pressure → **★** re-runs verification; materials get STRUCK with NACE MR0175 citations; verdict flips (e.g. makeable_in_house → makeable_outsource_only). Confirm the declared world actually persisted (part-context) — reopen and it's still there.
- **2c — declare a machine first (Phase C):** with a machine on the floor → **★** verdict shows `makeable_in_house` on THAT machine by name, per-route envelope fit ✓/✗ with need-vs-have numbers, machine-marginal rate on the make-now card.
- **2d — NEGATIVE verdict [EDGE]:** a part that exceeds every owned envelope → **★** the walk STOPS at the failed gate; downstream steps NOT rendered; honest "exceeds every envelope you own" + acquisition path. Never a fabricated pass.
- **2e — UNKNOWN verdict [EDGE]:** no machines declared → **★** honest unknown/feature state, not a fake verdict.
- **2f — GEOMETRY_INVALID [EDGE]:** non-watertight / broken mesh → **★** structured 400 surfaced as repair guidance, walk halts, no crash.
- **2g — provenance disclosure:** tap any driver number → **★** its verbatim engine source string; provenance dot filled (grounded) vs hollow (DEFAULT); hours tagged ○ MODEL not MEASURED.
- **2h — decide → record:** pick make-in-house → **★** persists a cost decision; appears in Records.
- **[EDGE] units landmine (B5):** upload an INCH-authored STL → **★** must NOT silently cost 16,000× wrong; expect the unit warning / declaration (once B5 lands).
- **[EDGE] STEP file (B4):** upload a .step → **★** honest "STEP needs OCP / not yet supported" (until B4 lands), never a silent wrong path.

## 3. Machines (real CRUD)
- List → **★** renders real inventory or designed empty state.
- Add machine (modal) → set type/envelope/materials/rate → **★** saved as ● USER; appears in list; now informs verdicts (loop back to 2c).
- Edit / delete → **★** verdicts re-evaluate; **[EDGE]** delete the machine a verdict depended on → the part's verdict changes honestly (or marks stale).
- **[EDGE]** CSV import with a malformed row → honest partial-success summary, not a silent drop or a 500.

## 4. Records (system of record)
- List → **★** real cost-decisions, paginated ("Load more" via real cursor — not "All 50" hiding the rest).
- Open a record → detail (make-now route, crossover, sourced drivers, declared world). **★** shows the environment that was declared (2b) — proving persistence.
- **[EDGE]** share (if wired) → read-only view, full provenance, nothing editable.

## 5. Cross-cutting edge cases (introduce these deliberately — the "human driving in different conditions")
- **Network failure** mid-verify → honest error state, retry, no silent hang.
- **Backend down** → the app degrades honestly, doesn't white-screen.
- **Session expiry** → re-auth prompt, not a broken surface.
- **Rapid re-verify same part** → dedup (same ULID updates in place — verified intentional, not a bug).
- **Rail nav under load** (H/V/P/R/G/M/T/C hotkeys per design) → no dead ends; Esc closes overlays.
- **Reduced-motion** OS setting → animations gate off, content still reachable.

## Checkpoints summary (must all be observed, not asserted-by-reading)
Auth gate · Home renders real/honest · the full verdict walk on real engine output · environment door persists + re-verifies with NACE · Phase C machine verdict by name · negative/unknown/invalid verdicts honest · provenance disclosure real · record persists + reopens with its world · stubs honest · units + STEP edge cases honest · network/auth failure states honest.

**Artifacts:** save screenshots per ★ to `outputs/pilot-proof/verify-e2e/` + a run-log of pass/observed/fail per node. A documented failure is more valuable than a faked pass.
