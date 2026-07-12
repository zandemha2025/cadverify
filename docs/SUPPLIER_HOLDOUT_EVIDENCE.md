# Supplier-quote holdout evidence

Commercial staging and production promotion fail closed until a real,
confidential supplier-quote holdout has been evaluated and approved. Synthetic
coupons and geometry-only archives cannot create this evidence.

## Required study

- Freeze at least 20 licensed, provenance-locked parts that were not used to
  tune the model.
- Retain independent quotes from at least three suppliers across additive, CNC,
  and injection-molding launch families.
- Include at least five quoted parts and three independent suppliers in each
  launch family; global totals alone are not sufficient evidence.
- Evaluate the exact 40-character release SHA being promoted.
- Require MAPE at or below 30%, P90 absolute error at or below 50%, and median
  signed bias within ±25% for every represented process family.
- Have an accountable reviewer approve the retained corpus, quotes, results,
  licensing record, and holdout/tuning separation.

The protected summary JSON must contain exactly these fields. Angle-bracket
values below are placeholders; numeric and boolean fields must use native JSON
types rather than quoted strings:

```json
{
  "schema": "cadverify-supplier-holdout-v1",
  "release_sha": "<40 lowercase hex>",
  "generated_at": "<UTC timestamp ending in Z>",
  "expires_at": "<UTC timestamp ending in Z>",
  "n_parts": 20,
  "n_suppliers": 3,
  "mean_abs_pct_error": 0.30,
  "p90_abs_pct_error": 0.50,
  "process_median_bias": {
    "additive": 0.0,
    "cnc": 0.0,
    "injection_molding": 0.0
  },
  "process_part_counts": {
    "additive": 5,
    "cnc": 10,
    "injection_molding": 5
  },
  "process_supplier_counts": {
    "additive": 3,
    "cnc": 3,
    "injection_molding": 3
  },
  "provenance_locked": true,
  "license_reviewed": true,
  "holdout_excluded_from_tuning": true,
  "corpus_sha256": "<64 lowercase hex>",
  "quotes_sha256": "<64 lowercase hex>",
  "results_sha256": "<64 lowercase hex>",
  "approval_sha256": "<64 lowercase hex>",
  "reviewer_id": "<accountable reviewer identifier>",
  "approval_id": "<retained approval record identifier>"
}
```

The timestamps must be recent: evidence older than 30 days, already expired,
generated in the future, or issued with a validity window longer than 90 days is
rejected. Hash fields identify the retained confidential artifacts; do not put
supplier names, quote values, CAD, or personal data in the summary.

After protected-main CI creates the immutable release, evaluate that exact SHA.
Base64-encode the reviewed JSON without changing it and set the result as the
`CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_B64` secret in both protected GitHub
environments. Replace both for every release. Staging validates the secret
before any deployment and records only its SHA-256 digest. After the production
approval wait, production independently revalidates freshness and every gate,
then requires its digest to match staging's. Missing, malformed, stale, changed,
release-mismatched, under-sampled, or failing evidence blocks deployment.
