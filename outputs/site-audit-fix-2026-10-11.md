# ScaleCad site fixes and commercial answers

Prepared October 11, 2026. **Local review draft; not published.**

## 1. Can we deliver a make-vs-buy answer in one day?

Not as an unconditional, validated decision. The repository proves computation
and ranking, not a staffed one-business-day delivery commitment. No current
customer turnaround benchmark was found.

A preliminary screen is a reasonable target for a small, qualified cohort after
receiving usable CAD, material/tolerance requirements, a declared machine list,
rates, volumes and current buy prices. Missing inputs, tolerances, setup,
capacity and supplier considerations can change the decision. The engine's
resource estimate alone is not a supplier quote or a production approval.

Recommendation: agree turnaround after intake. Establish repeated end-to-end
delivery evidence on the free 25-part qualification before offering a one-day
screening commitment. Do not promise a validated 500-part decision in one day.
The prepared pages make no one-day promise.

## 2. Are capability gaps and equipment ranking live today?

Implemented and wired into the current release, with limits:

- Per-part verification records machine-fit failures and capability gaps.
- `/api/v1/catalog/makeability` provides the organization breakdown.
- `/api/v1/catalog/capability-investment` ranks candidate acquisitions from
  stored single-constraint gaps, with part drill-down.
- The Verify triage screen renders the ranking in the needs-capability bucket.
  Verify is enabled by default.
- Multi-constraint parts are separated; stale verdicts are marked. Ranking a
  capability category is not proof that a particular machine can make every
  counted part. Check a candidate machine against all requirements and reverify.
  This is not a capex ROI model or a machine purchase recommendation.

Read-only production observations on October 11:

- API health reports build `c52267285f622237250306b81ae24db1da1759c9`, matching
  this patch's base, with PostgreSQL, Redis and worker healthy.
- `/verify` redirects to login; the surface is not a public 404.
- The same-origin ranking URL returns 401 without a dashboard session. That
  establishes the auth boundary, not successful authenticated feature execution.

The targeted local capability and owned-equipment tests passed (28 tests).
**Authenticated production behavior has not been verified in this task.** Do
not turn the implementation finding into an unconditional live-feature claim.
Safe description: review capability gaps and candidate upgrades during a scoped
pilot, with the underlying assumptions and machine review made explicit.

## 3. What should a pilot cost?

Recommendation: **$7,500 for 4–6 weeks, one plant, agreed process families and up
to 500 supported part numbers**, credited in full toward the first-year annual
agreement if the customer continues. This is a proposed offer based on the team's
scope, not a verified market benchmark. Annual pricing remains quoted to scope.

Offer a **free, team-assisted 25-part qualification** to establish data readiness,
process coverage and a credible success criterion. It is separate from the
existing 10 lifetime self-service checks; no quota or entitlement was changed.

The 500-part scope means portfolio screening, not manual validation of every
part. Validate a representative held-out subset against customer actuals.
Deliver a ranked decision brief, visible assumptions, misses, unresolved gaps
and next checks. Start the clock after agreed inputs are ready. Scope custom
integrations, data cleanup and self-hosted deployment separately. Confirm
scope, schedule, credit and acceptance criteria in the signed order form.

## Patch and release dependencies

- Added pricing, contact and pilot pages; `/about` permanently redirects to
  `/company`. Existing `/company#pilot` intake remains available.
- Added pricing/navigation and sitemap links, the requested homepage headline,
  and company attribution as **Nazeem Ahmed · Founder**. The full name was
  verified against the existing ScaleCAD Google Workspace account.
- Replaced frontend personal-email links with the existing
  `nazeem@scalecad.ai` mailbox. Security copy says contact, rather than claiming
  a security team. Proposed role aliases were removed because their existence
  could not be verified.
- Reused the connected pilot form and its existing validation/security handling.
  No live form was submitted and no email was sent.
- The domain publishes a Google MX record. The existing signed-in
  `nazeem@scalecad.ai` mailbox has received external email. No test message was
  sent. Google Admin requests reauthentication before alias configuration is
  available; no new mailboxes, aliases or access grants were created.

The three commercial answers were delivered before publication. Authenticated
production capability-gap/ranking execution still needs a signed-in ScaleCad
session. No unconditional production-functionality or one-day SLA claim was
added. No DNS change, mailbox provisioning or production data mutation was
performed. The role aliases are optional future work, not a release dependency.

## Verification

- Production build and TypeScript: passed.
- ESLint on changed frontend modules: passed.
- Existing site browser journey, extended for the audit: passed. Covers 21
  supporting routes on desktop and mobile, the permanent about redirect,
  founder attribution, pricing, domain email links, workflow preselection,
  pilot validation/retry/receipt, navigation and no browser errors. Account and
  pilot POST requests were stubbed; no live customer request was created.
- Capability/owned-equipment unit tests: 28 passed; six PostgreSQL tests
  deselected. Existing WebGL fallback unit tests: five passed.
- Desktop/mobile homepage screenshots reviewed; no layout overflow found.
- Final sitemap, robots directives and HTTP 308 about redirect: passed.

Browser artifacts: `/tmp/scalecad-site-audit-2026-10-11/`; final identity/contact
check: `/tmp/scalecad-site-audit-2026-10-11-final/`.
