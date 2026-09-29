# Current live entry points

Verified 2026-09-29. Use [Render](https://cadverify-web.onrender.com) for the
currently working application: [log in](https://cadverify-web.onrender.com/login)
or [create an account](https://cadverify-web.onrender.com/signup).

| Deployment | Observed state |
| --- | --- |
| Render web/API | Disposable signup, logout, password login, uppercase `.STP` upload and saved-record retrieval succeeded in the browser. API health reports PostgreSQL, Redis and worker healthy, build `ec6f8e1127fd8dc6b210b0d30d4919d141317609`. |
| `cadvrfy-web.fly.dev` / `cadvrfy-api.fly.dev` | Legacy July release. API health returns 503 with `postgres:false`; signup and login return 500. Provider logs are needed to diagnose the database failure. |
| `cadverify.vercel.app` | Returns 402 `DEPLOYMENT_DISABLED`; it is not a working application entry point. |

Existing Fly accounts and saved data have **not** been verified on Render.
No database migration, legacy redirect, provider configuration change or new
release was performed during this check.

The future AWS release architecture is described in
[the deployment handoff](COWORK_DEPLOY_HANDOFF.md). Those plans do not establish
that an AWS deployment is live. The observations above establish the working
public entry point, not completion of the full production acceptance contract.
