# Import a part from a link

Status: built (backend a869ed9, app 912f6c4, migration 0058). It extends the
big-file path in `docs/BIG_FILES.md`: a link is one more way for a file to
reach the worker's check, and everything after the bytes arrive (unpacking,
sizing, the check, the kept source) is unchanged. "What differs from the
design" below lists where the build departs from the original note.

## What the user does

On Check a part, or in Home's drop box, "Paste a link" (next to the file
picker) takes a share link to one CAD file (or a one-part ZIP or `.gz`) from
Google Drive, Dropbox, OneDrive or SharePoint, or an S3 object URL. The field
names the source as it is pasted ("Dropbox link · bracket.step") and says at
once when a link plainly can't be imported. ScaleCAD fetches the file on the
worker and checks it; nothing is downloaded to the browser. The page and the
work bar show "Importing bracket.step", "Fetching from Dropbox", then the
check's own stages, and the part's page opens when it's done.

## Flow

1. `POST /api/v1/uploads/from-link {url, filename?, material_class?, qty?,
   units?, orientation?}` (202, the check's status as `GET /api/v1/checks/{id}`
   gives it, plus `direct_upload_id`). The request reads only the link: the
   URL rules below and the provider's download address
   (`src/services/link_import.py`, `plan_link`). It makes a `direct_uploads`
   row with purpose `link` (migration 0058) that reserves the organization's
   upload admission and is taken by its check at once (`attached`), and a
   `stored_check` job with `params.source = "link"`, in one transaction. The
   full link is kept only sealed (`CONNECTOR_SECRET_KEY`) on the job until the
   worker reads it; stored records hold the provider, host and path.
   An `Idempotency-Key` header (for API clients) makes a repeat with the same
   link the same check. `GET /api/v1/uploads/from-link` says whether it is on
   and which providers it takes.
2. The worker's first stage is `fetching` (`stored_check_tasks._fetch_link`):
   it drops the sealed link from the job, fetches the bytes to its local disk
   under the rules below, counting them against `part_max_size_bytes()`
   (2 GiB) and taking the SHA-256 as they stream. The upload row then holds the
   real size, digest and name.
3. The check continues as a big file's: `unpacking` -> `sizing` -> `measuring`
   -> `pricing`. A failed fetch ends the check with the reason and "Nothing was
   charged."; the allowance is only used once the bytes are known, as for an
   upload.

## The outbound rules

The server fetches a URL the user chose, so the fetch must not reach anything
private. Every address requested, the pasted link and each redirect alike:

- HTTPS on port 443 only; no user name or password in the URL.
- The host is on the provider's allowlist (an allowlist, not a blocklist). A
  redirect must stay within the same provider's hosts (an S3 link within its
  bucket, a SharePoint link within its tenant). A redirect to a sign-in page
  (`accounts.google.com`, `login.live.com`, `login.microsoftonline.com`,
  Dropbox's `/login`) is named as needing sign-in and never fetched.
- The host is resolved once. Every address must be publicly routable:
  `url_guard.resolve_public_host` refuses private, loopback, link-local
  (including 169.254.169.254), CGNAT, multicast, unspecified and reserved
  addresses and IPv4-mapped forms of them (and `fd00:ec2::254` falls in
  `fc00::/7`); the fetch then also requires `is_global`. The connection goes
  to that exact address, with SNI and Host set to the name and the
  certificate checked against the name, so DNS can't change between the
  check and the connect. Each address is tried in turn if one doesn't connect.
- At most 3 redirects. Google Drive's virus-scan page for large files is
  followed once through its confirm form, whose target passes the same rules.
- No cookies are kept or sent, no `Authorization` header or other ScaleCAD
  credential, a fixed User-Agent (`ScaleCAD-LinkImport/1.0`), no proxy from the
  environment, `Accept-Encoding: identity`; a compressed transfer is refused
  (the cap counts real bytes).
- `Content-Length` over 2 GiB is refused before the body is read; without one
  the stream is cut at 2 GiB. 10 s to connect, 30 s between bytes, and a total
  budget of 60 s plus 1 s per MiB (at most 30 minutes).
- A page (HTML) instead of a file is refused: "That link opens a page, not a
  file. Share the file itself, or download it and upload the file."
- Errors are fixed text; logs name the host only. The log and Sentry scrubber
  also redacts presigned and share-link query secrets (`X-Amz-Signature`,
  `X-Amz-Credential`, `rlkey`, `authkey`, `resourcekey` and others).
- ScaleCAD's own buckets are refused (`OBJECT_STORE_S3_BUCKET`,
  `DIRECT_UPLOAD_S3_BUCKET`, and any in `LINK_IMPORT_REFUSED_S3_BUCKETS`).

## Allowed hosts

| Source | Link the user pastes | What is fetched | Redirects allowed to |
|---|---|---|---|
| Google Drive | `drive.google.com/file/d/<id>/...`, `/open?id=`, `/uc?id=`, `docs.google.com/uc?id=` | `drive.usercontent.google.com/download?id=<id>&export=download` (with `resourcekey` when the link has one) | `drive.usercontent.google.com`, `drive.google.com`, `docs.google.com`, `<label>.googleusercontent.com` |
| Dropbox | `www.dropbox.com/s/...` or `/scl/fi/...` | the same link with `dl=1` | `www.dropbox.com`, `dl.dropboxusercontent.com`, `<label>.dl.dropboxusercontent.com` |
| OneDrive (personal) | `1drv.ms/...`, `onedrive.live.com/...` | `api.onedrive.com/v1.0/shares/u!<link, base64url>/root/content` | `api.onedrive.com`, `onedrive.live.com`, `*.files.1drv.com`, `*.livefilestore.com`, `*.microsoftpersonalcontent.com` |
| SharePoint, OneDrive for work | `<tenant>.sharepoint.com/:u:/...`, `/personal/...`, `/sites/...`, `/teams/...` | the link with `download=1` | the same tenant's `sharepoint.com` hosts |
| Amazon S3 | `<bucket>.s3[.<region>].amazonaws.com/<key>`, path style `s3[.<region>].amazonaws.com/<bucket>/<key>`, presigned or public | as given | the same bucket's S3 hosts |

Folder links are refused ("That's a link to a folder. Share one file and
paste its link."); anything else is refused with "Paste a share link from
Google Drive, Dropbox, OneDrive or SharePoint, or an S3 presigned URL."

## Limits

- The same per-org upload admission as a direct upload: free plans 2 uploads
  and 4 GiB at once, other plans 4 and 10 GiB. A link reserves the part cap
  (2 GiB) until its size is known, then its real size; the reservation ends
  with its check.
- A per-user limit of 20 links an hour and 100 a day, every plan.
- The kill switch and the same role gates as the other routes that check a
  new part (analyst and org member; an org viewer is refused).
- The fetched bytes go through the same unpacking rules, memory sizing and
  analysis as an upload.

## Settings

- `LINK_IMPORT_ENABLED` (default on). Never on with the regulated boundary
  (`PRODUCTION_REGULATED_BOUNDARY_REQUIRED`): the backend treats it as off,
  a released regulated process refuses to start with it on, the Helm chart
  renders it `0` for the regulated plane (`linkImport.enabled: false` in
  `values-regulated.yaml`) and refuses to render it on, and the regulated
  manifest gate checks it.
- `CONNECTOR_SECRET_KEY`: seals the link on the job (already required in
  production for connector credentials and webhook secrets). Without it a
  released process answers 503 `LINK_IMPORT_UNAVAILABLE`.
- `LINK_IMPORT_REFUSED_S3_BUCKETS`: more of ScaleCAD's own buckets to refuse,
  comma-separated.
- The worker needs outbound HTTPS (443) to the providers' hosts, without a
  proxy.

## What differs from the design

- One job, not two: the fetch is the first stage (`fetching`) of the
  `stored_check` job, not a separate `link_fetch` job, so the work bar
  follows one check from the link to the part.
- No new upload status: the row is `attached` (taken by its check) from the
  start instead of a new `fetching` status, so only the purpose check
  changed (migration 0058).
- The bytes go to the worker's local disk, where the `verifying` stage would
  have put the downloaded object, not into the incoming store: the check
  reads them from there, and the organization's kept source is saved by the
  analysis as for every check. Nothing is stored under the row's key, and its
  cleanup has nothing to delete.
- S3 links may be presigned or public object URLs.
- OneDrive personal links use the anonymous OneDrive shares API
  (`api.onedrive.com`) rather than Microsoft Graph, which needs a token.
- The per-user rate limit is the same on every plan.
- Not built: the providers' pickers (Google Picker, Dropbox Chooser, OneDrive
  File Picker) for files that aren't shared publicly, and their CSP. A link
  that needs sign-in is refused with a plain message to share the file so
  anyone with the link can view it, or to download and upload it.
- The link rewrites follow the providers' documented link forms and are
  tested against fakes of their responses (redirects, Drive's confirm form,
  Content-Disposition names); the tests never fetch real URLs, and this
  build hasn't been run against the live providers.

## Tests

- `backend/tests/test_link_import_rules.py`: each refused class of URL, each
  provider's rewrite, the redirect allowlist, names, the setting, the sealed
  link, the scrubber.
- `backend/tests/test_link_import_fetch.py`: the fetch with fake DNS and a
  fake transport: the pinned address, SNI and Host, the headers, every
  non-public address class, redirects, caps, pages, encodings, timeouts, and
  that no error or log carries the link's query.
- `backend/tests/test_link_import_e2e.py`: end to end with a real TLS server
  on loopback (a test CA, the provider's names), through the router and the
  worker task; admission, idempotency, the viewer gate and the setting.
- `frontend/src/lib/link-import.test.ts`,
  `frontend/src/components/v4/part/stored-check-model.test.ts`.
