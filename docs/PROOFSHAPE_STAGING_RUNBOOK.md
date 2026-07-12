# ProofShape non-Arcus staging runbook

Status: code-ready; external account provisioning is not complete
Target branch: `codex/proofshape-scalecad-staging`
Protected existing deployment: Arcus Vercel `eager-euler` — do not modify

## Outcome

This runbook creates one production-shaped ProofShape staging environment where
a real user can sign in, create and revise CAD, preview/download exact revisions,
send a generated STEP into DFM/should-cost verification, and use the existing
portfolio/decision workflows.

Staging is not production approval. Supplier-accuracy evidence, the public
domain/name decision, legal source authorization, production backup/restore,
on-call, and the applicable commercial or regulated launch gates remain
separate requirements.

## Non-negotiable ownership boundary

- Create every target in a new personal or ProofShape-owned account/team.
- Do not use the Arcus Vercel team, Arcus Fly organization, Arcus billing,
  Arcus domains, or Arcus secrets.
- Do not attach a ProofShape alias to `eager-euler` or redeploy it.
- ScaleCAD source is an authorized reference/input only. ProofShape deploys this
  repository's web, API, worker, database migration, and object model.

## Chosen topology

Use the repository's supported container path for staging:

| Component | Staging target |
|---|---|
| Web | isolated ProofShape Fly app (or equivalent container web service) |
| API | isolated ProofShape Fly app, `web` process group |
| Worker | same backend image, isolated `worker` process group |
| Database | managed Postgres with pooled and direct TLS URLs |
| Queue | managed TLS Redis |
| Artifacts | private, encrypted, versioned S3-compatible bucket |
| Email | Resend with a ProofShape-owned verified sender domain |
| Bot defense | Cloudflare Turnstile site/secret pair |
| Errors | separate ProofShape staging Sentry projects |
| Delivery | protected GitHub staging environment and scoped deploy token |

An all-Vercel deployment is intentionally not selected. The app needs a native
gmsh/OpenCASCADE image, a durable ARQ worker, Redis, and large streaming CAD
uploads. The Next.js web app can run on Vercel, but that would still require the
container/data plane elsewhere and would not simplify the first complete test.

## Human-owned prerequisites

The owner must create or approve these in provider dashboards; they cannot be
simulated by application code:

1. a non-Arcus Fly organization/account (or approved equivalent container host);
2. a ProofShape-owned domain or temporary approved staging subdomain;
3. managed Postgres, TLS Redis, and private S3 credentials;
4. Resend domain verification, Turnstile keys, and Sentry projects;
5. a protected GitHub environment with scoped deployment credentials; and
6. written ownership/license evidence for the ScaleCAD source before public or
   commercial distribution.

Never paste these secrets into chat, source, issue comments, or build logs.

## Resource names

Use names that make the boundary visible. Check provider availability before
creation; suffix with a random non-company identifier if a global name is taken.

```text
proofshape-stg-api
proofshape-stg-web
proofshape-stg-postgres
proofshape-stg-redis
proofshape-stg-artifacts
GitHub environment: proofshape-staging
```

The checked-in Fly files contain historical default app names. The approved
workflow must pass explicit target app names; never rely on those defaults.

## Configuration

Use `docs/LAUNCH_RUNBOOK.md` for the complete secret list and fail-closed
production controls. Staging must still set a real release identifier and the
production-shaped controls below:

```text
RELEASE=<exact-git-sha>
DEPLOYMENT_ENVIRONMENT=staging
API_ORIGIN=https://<proofshape-api-host>
DASHBOARD_ORIGIN=https://<proofshape-web-host>
AUTH_MODE=password
PASSWORD_LOGIN_ENABLED=1
MAGIC_LINK_ENABLED=1
PUBLIC_PASSWORD_SIGNUP_ENABLED=0
RESEND_FROM=<verified ProofShape sender>
PILOT_INBOX=<owned launch inbox>
OBJECT_STORE_BACKEND=s3
PRODUCTION_STORAGE_REQUIRED=1
PRODUCTION_OBSERVABILITY_REQUIRED=1
PRODUCTION_TLS_REQUIRED=1
ASYNC_STRICT_HEALTH=1
WORKER_STRICT_HEALTH=1
RECONSTRUCTION_BACKEND=local
RECONSTRUCTION_ALLOW_REMOTE_EGRESS=0
DESIGN_GENERATION_TIMEOUT_SECONDS=45
DESIGN_GENERATION_CONCURRENCY=2
```

The API and web must receive the same `AUTH_PROXY_SECRET`. `DASHBOARD_ORIGIN`
must be the canonical HTTPS web origin. `DATABASE_URL_DIRECT` is used only by
the release migration; application traffic uses the pooled URL.

## Deployment sequence

1. Create the non-Arcus host organization and the five external data/provider
   resources above.
2. Create protected GitHub environment `proofshape-staging`. Set scoped secrets
   directly there/provider-side and set explicit API/web app variables.
3. Generate fresh random launch secrets with
   `scripts/ops/gen-launch-secrets.sh`; replace every external placeholder.
4. Run the required-secret gate against the explicit ProofShape app names.
5. Merge the reviewed branch through protected CI. Do not deploy a dirty local
   tree or mutable branch tag.
6. Record the exact commit and digest-qualified web/backend images.
7. Run `alembic upgrade head` as the backend release command. Migration 0040
   creates `design_projects` and `design_revisions`.
8. Deploy API and worker from the same backend digest, then deploy the web digest.
9. Require token-authenticated deep health to show Postgres, Redis, worker, queue,
   and S3 healthy before inviting a user.
10. Run the acceptance journey below and retain screenshots/log evidence.

## Staging acceptance journey

Every item must use real infrastructure and two real test organizations:

- [ ] Magic-link email arrives; initial password can be set; logout/login works.
- [ ] A user opens Design Studio from onboarding, Home, navigation, and command
      palette without a dead end.
- [ ] Plate with four holes generates a real preview and STEP.
- [ ] Bracket and open enclosure generate without mock/fallback geometry.
- [ ] Revision 2 leaves revision 1 preview/download/hash available.
- [ ] `Verify revision 1` and `Verify revision 2` import the exact STEP and return
      real DFM/should-cost results.
- [ ] A manually uploaded STEP still completes normally.
- [ ] Viewer can read/download but cannot create/revise/archive.
- [ ] A second org receives 404 for project, history, preview, and STEP identifiers
      from the first org.
- [ ] Queue outage creates an honest terminal failure; restoring Redis permits a
      new revision without manual database repair.
- [ ] Worker loss does not freeze API health; a restarted worker drains queued jobs.
- [ ] S3 write/read/list/delete canary, Sentry event, uptime alert, and Postgres
      restore drill all reach their owners.
- [ ] Browser console has no uncaught errors; keyboard navigation and mobile
      layout do not block creation, revision, download, or Verify handoff.

## Current blocker list

No ProofShape staging deployment has been made because the required non-Arcus
host organization, domain/sender, managed data plane, Sentry/Turnstile, and
protected GitHub environment are not yet available to this task. Deploying to
the already-authenticated Arcus scopes would violate the ownership boundary and
recreate the beta-grade environment that was rejected.

Once the owner supplies those accounts through the provider UIs, this runbook
can proceed without changing `eager-euler`.
