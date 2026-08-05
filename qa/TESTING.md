# QA test harness briefing (for test agents)

The app is RUNNING locally. Test against it; do not start/stop services.

## Endpoints
- Backend API: `http://127.0.0.1:8000` (direct; use `Authorization: Bearer <api-key>` for `/api/v1/*`)
- Frontend: `http://localhost:3000` (product app; `/api/proxy/*` forwards to the backend with the dashboard session cookie; `/api/auth/*` handles login/signup)
- Health: `GET http://127.0.0.1:8000/health`

## Accounts
- Existing: `qa-tester@proofshape.local` / `QaTester123` (analyst, org "qa-tester's Organization" + "QA Test Org", org admin)
- Superadmin: `qa-super@proofshape.local` / `QaSuper123` (platform superadmin)
- Create your OWN throwaway accounts freely: `POST http://localhost:3000/api/auth/signup {"email","password","name"}` (rate limit disabled; password needs 8+ chars, letter + digit). Signup auto-creates a personal org with you as admin and returns a `dash_session` cookie.

## Getting an API key (for direct backend calls)
1. Log in: `curl -c cj.txt -X POST http://localhost:3000/api/auth/login -H 'Content-Type: application/json' -d '{"email":"...","password":"..."}'`
2. Mint: `curl -b cj.txt -c cj.txt -X POST http://localhost:3000/api/proxy/keys -H 'Content-Type: application/json' -d '{"name":"qa"}'`
   The one-time secret arrives in the `cv_mint_once` cookie in `cj.txt` (URL-encoded JSON) — extract the `cv_live_...` token from it.
3. Use: `curl -H "Authorization: Bearer cv_live_..." http://127.0.0.1:8000/api/v1/...`

## Rate limits (they are EXPECTED behavior, not bugs)
- `/validate` family: 60/hour;500/day per key. Budget your heavy calls; each agent should use its own account+key. Reference GETs are also 60/hour per key — spread across keys if needed.
- A 429 with Retry-After when you exceed a documented limit is a PASS for that limit's story, but do not deliberately exhaust limits before finishing your other stories.

## CAD fixtures (qa/fixtures/)
- `qa-box.stl` — valid watertight 40x30x10 box
- `qa-part2.stl` — valid watertight second part
- `qa-broken.stl` — non-watertight (2 faces removed)
- `qa-fake.stl` — PDF bytes with .stl name (magic-byte rejection)
- `qa-cube.step` — valid STEP
- `qa-batch.zip` — ZIP of the two valid STLs
- More STEP samples: `backend/tests/assets/*.step|.stp`

## Playwright (UI agents)
Use node with `frontend/node_modules/playwright-core`:
```js
const { chromium } = require('/home/user/cadverify/frontend/node_modules/playwright-core');
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
```
Log in by driving `/login` or by POSTing `/api/auth/login` and injecting the `dash_session` cookie into the context. Screenshot failures to `qa/results/screenshots/`.

## Reporting (MANDATORY)
Write results to `qa/results/<your-slice>.json` as a JSON array:
```json
[{"id": "CORE-001", "status": "TESTED-PASS" | "TESTED-FAIL" | "BLOCKED",
  "error_found": "empty for PASS; concrete observed error for FAIL (what you did, expected vs actual, HTTP codes/console errors)",
  "notes": "optional short context (e.g. verified 401/403/429 paths, or why BLOCKED)"}]
```
Rules:
- Test the story's EXPECTED behavior as written in `qa/user-stories.csv` (column `expected`). A documented honest 501/disabled/empty state that behaves as documented is a PASS.
- FAIL only for real deviations: wrong status codes, crashes, unhandled errors, wrong data, broken UI states, dead links, console errors, misleading copy.
- BLOCKED when the environment genuinely can't exercise it (say why).
- Do not fix anything. Do not modify app code. Only write your results file.
- Your final chat message should be ONLY a count summary (pass/fail/blocked) plus the ids of failures.
