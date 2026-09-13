# ProofShape API quickstart

This quickstart uses the production API at `https://cadverify-api.onrender.com`.
The live OpenAPI document is at
[`/openapi.json`](https://cadverify-api.onrender.com/openapi.json), and the
interactive Swagger UI is at
[`/docs`](https://cadverify-api.onrender.com/docs).

## 1. Create an API key

Sign in to ProofShape, open **Settings > Developer**, and create a key. The full
key is shown once. Store it in your secret manager rather than in source control.

Export the key in your shell:

```bash
export PROOFSHAPE_API_KEY='cv_live_...'
export PROOFSHAPE_API_URL='https://cadverify-api.onrender.com'
```

Every authenticated API call uses the bearer header:

```text
Authorization: Bearer cv_live_...
```

## 2. Validate a part

`POST /api/v1/validate` accepts an STL, STEP/STP, or IGES/IGS file as the
multipart field `file`.

```bash
curl --fail-with-body --silent --show-error \
  -X POST "$PROOFSHAPE_API_URL/api/v1/validate" \
  -H "Authorization: Bearer $PROOFSHAPE_API_KEY" \
  -F 'file=@part.step' \
  | tee validation.json
```

The normal response is synchronous JSON. Keep the entire response as the
verification record; the live OpenAPI schema does not currently publish a
stable response-field contract for this route.

### Optional query parameters

Put these options in the query string, not in the multipart body:

| Parameter | Values | Meaning |
| --- | --- | --- |
| `processes` | comma-separated process IDs | Restrict the processes checked; omit to check all. |
| `rule_pack` | `aerospace`, `automotive`, `oil_gas`, `medical` | Apply an industry rule pack. |
| `include_thickness` | `true` or `false` | Include the per-face `wall_thickness_map`; off by default and never persisted or cached. |
| `units` | `mm` or `inch` | Declare source units. Unset defaults to mm. STL does not carry unit metadata. |
| `segmentation` | `sam3d` | Request asynchronous SAM-3D segmentation. See the next section. |

Example for an inch-authored STL, restricted to two processes:

```bash
curl --fail-with-body --silent --show-error \
  -X POST \
  "$PROOFSHAPE_API_URL/api/v1/validate?units=inch&processes=fdm,cnc_3axis" \
  -H "Authorization: Bearer $PROOFSHAPE_API_KEY" \
  -F 'file=@part.stl' \
  | tee validation.json
```

## 3. Poll an asynchronous segmentation job

Adding `segmentation=sam3d` changes a successful submission to HTTP 202. The
response contains the synchronous verification in `result`, plus `analysis_id`,
`job_id`, and a relative `poll_url`.

```bash
curl --fail-with-body --silent --show-error \
  -X POST "$PROOFSHAPE_API_URL/api/v1/validate?segmentation=sam3d" \
  -H "Authorization: Bearer $PROOFSHAPE_API_KEY" \
  -F 'file=@part.step' \
  -o submission.json

job_id=$(jq -er '.job_id' submission.json)
```

Poll the job status with the same bearer key:

```bash
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $PROOFSHAPE_API_KEY" \
  "$PROOFSHAPE_API_URL/api/v1/jobs/$job_id" \
  | tee job.json
```

The status response includes `status` and keeps `result_url` null until the job
is `done` or `partial`. When `result_url` is present, fetch it:

```bash
result_url=$(jq -er '.result_url' job.json)

curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $PROOFSHAPE_API_KEY" \
  "$PROOFSHAPE_API_URL$result_url" \
  | tee job-result.json
```

A result requested before completion returns 404. A failed job exposes an
`error` object on its status response instead of a result URL.

## 4. Handle errors loudly

Do not treat a non-2xx response as a verification result. `curl
--fail-with-body` exits nonzero while preserving the server's JSON error body.
For example, a request without a bearer key currently returns HTTP 401:

```json
{
  "code": "auth_missing",
  "message": "Authorization: Bearer cv_live_... header or dashboard session required",
  "doc_url": "https://cadverify-web.onrender.com/docs#auth_missing"
}
```

HTTP 422 means the request shape failed validation. Invalid options and invalid
CAD input can produce other 4xx responses. A `segmentation=sam3d` submission can
return HTTP 503 with `SAM3D_ENQUEUE_FAILED` if publication to the worker cannot
be confirmed; that error includes a `job_id` and marks the request retryable.

For support, include the HTTP status, response body, and request ID header if one
was returned. Never include the bearer key.

## Contract notes

- Authentication and job polling are scoped to the calling user or
  organization. A missing job and another user's job both return 404.
- The API-key secret is shown once. Rotate or revoke it from Developer settings.
- The interactive Swagger UI and OpenAPI document are the source of truth for
  the deployed route set. This guide intentionally does not name response fields
  that the live schema leaves unspecified.
