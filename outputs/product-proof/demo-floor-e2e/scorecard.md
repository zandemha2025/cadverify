# CadVerify Demo-Floor E2E Proof — 2026-07-05

## What Ran

- Fresh disposable Postgres database migrated to Alembic head.
- Real backend on `http://127.0.0.1:8000`, real frontend on `http://localhost:3210`.
- Seeded via real HTTP routes, not ORM shortcuts:
  - `POST /auth/signup`
  - `POST /api/v1/machine-inventory` for `A-5X Demo Cell` and `MJF Pilot Bay`
  - `PUT /api/v1/part-context/{mesh_hash}` for both demo parts
  - `POST /api/v1/validate`
  - `POST /api/v1/validate/cost`
- Browser walked `/verify` with the seeded session cookie and same-origin `/api/proxy/*` auth.

## Data Proof

- Machines: `2`
- Seeded records before browser upload: `2`
- Browser-visible records after live upload: `3`
- Catalog rows: `2`
- Portfolio rows: `2`
- Makeability rollup: `2 / 2 makeable_in_house`
- Browser proxy statuses: all `200` for cost-decisions, catalog, machine-inventory, portfolio, makeability, capability-investment.
- Browser console/page errors: `0`

## Screenshots

- `00-home.png` — populated Home
- `01-live-upload-verdict.png` — live drop pipeline overlay
- `01b-live-upload-settled-walk.png` — settled audit walk
- `03-parts.png` — populated Parts catalog
- `04-records.png` — populated Records
- `05-programs.png` — populated Program rollup
- `06-machines.png` — declared floor
- `07-triage.png` — makeability rollup
- `08-calibration.png` — calibration/truth/audit surface

## Five-Bar Drop-Audit Rubric

1. Cinematic: provisional pass for the pipeline overlay + settled split audit. Founder taste call remains binding.
2. Data true: pass. Every count and cost shown came from real engine/DB responses.
3. Environment correct + cinematic: pass for machine-floor fit and declared context round trip; the live browser upload used ambient conditions, while seeded records include declared contexts.
4. Drillable: pass. Home, Parts, Records, Programs, Machines, Triage, and Calibration all opened against the same backend state.
5. Conversational: partial. Structured asks and compare affordances are engine-computed; free-form natural language is still explicitly IN DEVELOPMENT and refused rather than invented.

## Bottom Line

Pilot demo-floor proof passes: a fresh local platform can create an org, declare a floor, compute real should-cost records, persist them, populate the product shell, and walk the browser surfaces without fixtures.
