# Import a part from a link (design note, not built)

Status: proposal. Nothing in this note is implemented. It extends the big-file
path in `docs/BIG_FILES.md`: a link becomes one more way to put a file into the
incoming store, and everything after that (checksum, unpacking, sizing, the
check on the worker, the kept source) is unchanged.

## What the user does

Paste a share link to one CAD file (or a one-part ZIP) from Google Drive,
Dropbox, OneDrive/SharePoint, or an S3 presigned URL. ScaleCAD fetches it on the
worker and checks it. Nothing is downloaded to the browser.

## Flow

1. `POST /api/v1/uploads/from-link {url, filename?}`: validates the URL (below)
   and creates a `direct_uploads` row with a new purpose value `link`
   (migration) in status `fetching`, plus a `jobs` row `link_fetch`.
2. The worker fetches the bytes into the incoming store (the same key layout
   as `part`), counting bytes against `part_max_size_bytes()` (2 GiB) and
   computing SHA-256 as it streams. The digest is the upload's checksum; the
   upload becomes `completed`.
3. The same `stored_check` job runs on it. The work bar shows "Fetching
   from Dropbox", then the check's own stages.

## SSRF guard

The server is fetching a URL the user chose, so the fetch must not reach
anything private.

- HTTPS only, port 443 only, no userinfo in the URL.
- Resolve the host once, reject any address that is private, loopback,
  link-local, CGNAT, multicast, unspecified or the cloud metadata range
  (169.254.169.254, fd00:ec2::254), then connect to that exact address (pin
  it) with SNI and Host set to the name. This defeats DNS rebinding between
  the check and the connect. `src/services/url_guard.validate_outbound_url`
  (used for webhooks today) does the address classification; the fetch needs
  the pinned connect on top of it.
- Redirects: at most 3, each one re-validated with the same rules and the
  same host allowlist (Drive and Dropbox redirect to content hosts).
- No cookies, no `Authorization` header from ScaleCAD, a fixed User-Agent,
  `Accept-Encoding: identity` (the size cap counts real bytes).
- Timeouts: 10 s to connect, 30 s between bytes, and a total budget by size.
- Logs and errors never contain the query string (presigned URLs and share
  tokens are secrets); store the host and path only.
- Egress goes through the same allowlisted path as webhooks on the regulated
  plane; the regulated plane keeps link import off.

## Allowed hosts (allowlist, not a blocklist)

| Source | Link the user pastes | What is fetched |
|---|---|---|
| Google Drive | `drive.google.com/file/d/<id>/view` | `drive.usercontent.google.com/download?id=<id>&export=download` (large files answer with a virus-scan interstitial; follow its confirm form once) |
| Dropbox | `www.dropbox.com/s/...` or `/scl/fi/...` | same URL with `dl=1`, redirected to `*.dl.dropboxusercontent.com` |
| OneDrive / SharePoint | `1drv.ms/...`, `onedrive.live.com/...`, `<tenant>.sharepoint.com/:u:/...` | the share link with `download=1` (SharePoint), or the Graph `shares/{encoded}/driveItem/content` endpoint |
| S3 presigned | `<bucket>.s3.<region>.amazonaws.com/...?X-Amz-Signature=...` | as given; refuse ScaleCAD's own buckets |

Anything else is refused with "Paste a share link from Google Drive, Dropbox,
OneDrive or an S3 presigned URL".

## Links that need sign-in

Public share links cover most cases. For files that aren't shared publicly,
use each provider's own picker in the browser (Google Picker, Dropbox Chooser,
OneDrive File Picker). The picker returns a short-lived download URL (and, for
Google, an access token scoped to that one file). The browser sends it with the
request; the worker uses the token for that fetch only and never stores it.
No standing OAuth connection, no refresh tokens.

## Limits and abuse

- The same per-org upload admission as a direct upload (count and bytes), and
  a per-user rate limit (for example 20 links an hour on a free account).
- `Content-Length` over 2 GiB is refused before the body is read; without
  one, the stream is cut at 2 GiB.
- The fetched bytes go through the same magic-byte check, unpacking rules and
  memory sizing as an upload.
- A link that answers HTML instead of a file (a sign-in page, an
  interstitial) is refused with "That link opens a page, not a file. Share the
  file itself, or use the picker."

## What it takes

A migration (purpose `link`, status `fetching`), the fetch task with the
pinned-address client, the per-provider link rewriting with tests against
recorded responses, the picker integrations in the browser, and a CSP update
for the pickers' scripts. Roughly three to four days with tests.
