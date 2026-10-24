# Free checks and manual paid access

Each authenticated account receives **10 lifetime single-part CAD checks**. A check includes that upload's preview, DFM analysis and cost estimate. A completed analysis or estimate consumes one check. Failed operations can retry; invalid files do not consume completed checks. Simultaneous requests reserve slots before compute, so they cannot exceed ten by racing. API keys and browser sessions share the account allowance.

The public `/sample` is a recorded example with no live computation. Both legacy `/validate/demo` endpoints now require authentication and use the same allowance. Batch work, reconstruction, Design Studio generation/interpretation, repair, context fit, multi-part assembly work, multipart bulk uploads and recalibration require approved access. Reading saved results and exporting existing reports remain available after the free allowance is exhausted.

There is no checkout or recurring subscription in this release. The **Request paid access** link opens an email draft to the existing contact address. It neither sends an email automatically nor grants access. Agree the commercial terms separately; an authorized operator can then set the existing account entitlement `users.plan` to `pilot` using a parameterized database update for the verified account ID/email. That existing entitlement grants unlimited checks and the advanced tools. Reverting the plan to `trial` restores the remaining lifetime allowance; it does not erase usage. Do not change platform roles or organization membership to grant paid access.

## Deployment

Apply Alembic migration `0049_trial_checks` before starting the new API. It creates the durable check ledger and backfills past analyses and cost-only results; a cost result with a matching user/mesh analysis is not counted twice. Existing approved `pilot` users remain unlimited. Deploy the matching web build so its preview, analysis and costing requests share the `X-Part-Check-ID` UUID. The server independently binds the ID to the authenticated user and uploaded filename/bytes; the header grants no authority. A recheck uses a fresh ID. The former cap override and rolling-window environment variables no longer control the product allowance.

The migration is additive; leave the table in place if rolling the application back. Do not downgrade/drop the ledger on a live system, because doing so loses the new usage history.

## Interrupted work

Idle previews expire after one hour. Running operations retain their reservations until settled, including after an API crash; elapsed time does not permit uncounted simultaneous compute. If a reservation remains stuck, first verify that its worker/request has stopped and inspect saved results for that account and file. An authorized operator can settle completed work or remove only the failed operation under the same user-row lock used by `finish_check`. Never reset the entire account or refund an operation whose result persisted. Accounting database failures stop admission with 503 rather than allowing unpaid compute.

## Verification

`backend/tests/test_validation_caps.py` exercises real PostgreSQL races, lifetime totals, failure refunds, account isolation, paid gates, foreign-key locking and commit failure. `backend/tests/test_free_check_access.py` checks anonymous access to core and legacy compute. Frontend tests verify shared request IDs and preview reuse after remounts. `npm run test:e2e:site-design --prefix frontend` checks the public sample-to-account journey and responsive pages. Paid-feature E2E fixtures explicitly grant the existing entitlement only for disposable example-domain accounts on loopback app/database targets; normal signup remains a free account.
