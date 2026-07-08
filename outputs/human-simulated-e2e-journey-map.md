# Human-Simulated E2E Journey Map

This is the durable QA contract for CadVerify's web surface. Unit and integration
tests still matter, but they are not enough. The browser harness must drive the
product the way real users do: public visitors, new CAD engineers, enterprise org
admins, procurement/cost engineers, unauthenticated callers, and low-role users.

CI command:

```bash
npm run test:e2e:full --prefix frontend
```

That command runs the human, enterprise, and P7 browser journeys, then runs
`scripts/e2e/human-sim-journey-coverage.mjs`. The coverage auditor fails if any
required branch is missing, skipped, failed, has issues, has browser console
errors, has request failures, or loses the autonomous low-role viewer proof.

## Surfaces

| Surface | Human simulation intent | Current gate |
| --- | --- | --- |
| Public web | A buyer, engineer, or security reviewer lands on every public page and sees final copy with no broken app shell. | `human-e2e` public route sweep |
| Auth and signup | A new user tries bad credentials, weak signup, then creates a real account and enters the app. | `human-e2e` and `p7-role-failure` auth branches |
| Protected app shell | An authenticated user visits every core app route and each route renders an actual surface. | `human-e2e` authenticated route sweep |
| Verify workspace | A CAD engineer uses the rail, command palette, notifications, mobile layout, and real STEP upload. | `human-e2e` Verify branches |
| Enterprise CAD org | An org admin creates governed rates, machine inventory, ground truth, API keys, cost records, and portfolio/program views. | `enterprise-domain` |
| Cost governance | A cost decision is created, approved, reopened, then marked stale after governed rate publication. | `p7-role-failure` |
| Failure and recovery | Invalid login, network failure, unsupported uploads, injected API failure, and protected-route redirects produce bounded behavior. | `p7-role-failure` |
| Role security | A viewer is autonomously created, invited into the primary org, switched into viewer context, denied admin APIs, and shown gated UI copy. | `p7-role-failure` plus coverage auditor evidence checks |
| Finality sweep | Visible text is scanned for non-final language such as TODO, placeholder, stub, mock, partial, or coming soon. | all three journeys plus P7 copy sweep |

## Branch Tree

### Public evaluator

- Open `/`, `/platform`, `/developers`, `/api-reference`, `/docs`, `/teams`,
  every team page, `/method`, `/security`, `/status`, `/company`,
  `/pilot-report`, `/privacy`, `/terms`, and `/dpa`.
- For every page: assert final visible copy, expected page signal, screenshot
  evidence, and no blocking browser errors.
- Mobile branch: load public home at mobile width.

### New CAD engineer

- Visit protected Verify while signed out and confirm login boundary.
- Submit a weak password and confirm validation.
- Create a real account.
- Enter `/verify`.
- Navigate Verify rail branches: Home, Verify, Parts, Records, Programs,
  Your machines, Triage, and Calibration & truth.
- Use command palette to jump to Triage.
- Open notifications and verify derived state.
- Mobile branch: load authenticated Verify at mobile width.
- Upload and process a real STEP fixture through the browser.

### Authenticated app user

- Visit `/cost`, `/analyze`, `/batch`, `/cost-decisions`,
  `/cost-decisions/compare`, `/rfq-packages`, `/integrations`, `/history`,
  `/reconstruct`, `/label`, `/design-system`, `/settings/developer`, and
  `/notifications`.
- Each route must render a real product surface and not leak unfinished copy.

### Enterprise CAD organization

- Sign up as an enterprise engineer and receive an org.
- Confirm machine inventory rejects unauthenticated access.
- Publish a governed rate card.
- Declare owned machines with rates and envelopes.
- Ingest historical actuals and verify recalibration refuses below the floor.
- Confirm Verify UI shows declared machines and governed truth honestly.
- Create an API key and reveal it exactly once.
- Verify a real STEP file in the declared service world.
- Confirm portfolio exposure is withheld until declared volume, then compute
  server-side math.
- Confirm Programs UI and cost history show the verified enterprise part.

### Failure-path user

- Try protected routes without a session: `/cost`, `/cost-decisions`, `/batch`,
  `/history`, `/integrations`, `/notifications`, `/rfq-packages`,
  `/settings/developer`, and `/verify`.
- Call unauthenticated APIs through the same-origin proxy:
  `/api/proxy/admin/users`, `/api/proxy/machine-inventory`, and
  `/api/proxy/cost-decisions?limit=1`.
- Try invalid credentials.
- Inject a login network failure.
- Upload an unsupported batch file.
- Inject a cost-history API failure.
- Create a cost-decision fixture.
- Approve and reopen it through UI.
- Publish a governed rate card and confirm the decision becomes stale.

### Low-role viewer

- Create a viewer account without public signup quota.
- Invite that account into the primary org as `viewer`.
- Accept the invite as the viewer.
- Switch viewer context into the invited org.
- Confirm admin APIs return 401/403.
- Confirm Verify calibration/member controls show gated copy.

## Hard Pass Rules

- Every browser journey must report `PASS`.
- Skipped steps must be zero.
- Failed steps must be zero.
- Issues must be zero.
- Browser console errors must be zero.
- Request failures must be zero, except explicitly ignored browser prefetch noise.
- P7 must prove the low-role org role is `viewer`.
- P7 must prove low-role admin access is denied.
- In CI, P7 must self-seed the viewer unless explicit low-role hooks are supplied.
