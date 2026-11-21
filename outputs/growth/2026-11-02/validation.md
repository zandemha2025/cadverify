# Validation

November 2, 2026. Scope: growth pages, calculator, pricing presentation, public-route analytics classification and sitemap.

- `npm run build` passed on Next.js 16.4.2 after the final source changes. The existing `precise.css` emitted six animation parsing warnings; this branch does not change that stylesheet.
- Targeted ESLint passed for the new routes/components/helpers, changed pricing components, analytics files and the browser test.
- 22 calculator/privacy/RB2B tests passed. They cover the worked example, equal costs, identical routes, reversed/nonpositive crossovers, invalid inputs, exact public-route recognition, sensitive input scrubbing, consent and replay restrictions.
- Six existing billing tests passed, including backend plan parsing, price formatting and checkout/portal routing.
- Browser checks exercised all seven new pages plus pricing at 1440px and 390px: 200 responses, one H1, canonical URLs, new-page OG URLs, parseable JSON-LD, no horizontal document overflow, calculator edits/reset, mobile menu, sitemap inclusion and llms.txt. Unknown guide routes emit noindex.
- `browser-checks.json` and the screenshots record the latest browser run. The reproducible test is `frontend/scripts/growth-e2e.mjs`; run with Chrome installed and `GROWTH_BASE_URL` pointing at the running frontend. `GROWTH_EVIDENCE_DIR` selects the artifact directory.
- Public production `/api/billing/plans` returned 15 work-email free checks, 3 personal-email free checks, 50 Pro checks per month, no available checkout and no current public Pro price. The pricing fallback to contact is consistent with that observed state.
- `git diff --check` passed.

Not performed: live deployment, Google URL Inspection or Rich Results Test, successful real signup/CAD upload/payment, authenticated paid-plan UI, paid keyword volume/backlink analysis, customer interviews, competitor hands-on benchmarks or external distribution. No traffic increase, ranking improvement or revenue result is claimed.

Research tooling note: the agent-reach Exa server was not configured; web search and Jina reading were used. Installed agent-reach is v1.5.0; its update check reported v1.6.1 available. No tool upgrade was performed. Optional update instructions: https://raw.githubusercontent.com/Panniantong/agent-reach/main/docs/update.md
