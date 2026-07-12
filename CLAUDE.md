## Deploy Configuration (configured by /setup-deploy)

- Platform: Fly.io for commercial SaaS; AWS GovCloud EKS via Helm for the regulated plane
- Production URL: https://cadverify.com
- Deploy workflow: .github/workflows/saas-promote.yml
- Deploy status command: fly status --app cadvrfy-api && fly status --app cadvrfy-web
- Merge method: merge
- Project type: Next.js web app, FastAPI API, and arq worker
- Post-deploy health check: https://api.cadverify.com/health

### Custom deploy hooks

- Pre-merge: protected `main` requires the complete GitHub CI check set and resolved conversations
- Deploy trigger: manually run Commercial SaaS Promotion on `main` with the successful release SHA
- Deploy status: verify the protected GitHub promotion, then run both Fly status commands
- Health check: run `scripts/ops/fly-live-health-gate.mjs` with authenticated deep health
- Staging: `cadvrfy-api-staging` and `cadvrfy-web-staging` must pass before production approval
- Regulated: use `.github/workflows/regulated-release.yml` and `.github/workflows/regulated-promote.yml` only after the GovCloud/legal boundary is approved
