# Big files

How a single CAD part of up to 2 GB gets to ScaleCAD and is checked, how large a
file one worker can check, and what it would take to check larger ones.

## The path

1. **Upload, straight to storage, resumable.** The browser hashes the file
   (SHA-256, read in 8 MiB slices) and starts a multipart upload,
   `POST /api/v1/uploads/multipart` with purpose `part`. It sends up to three
   parts at a time; each part is retried with backoff; an expired presigned
   URL is renewed. The upload is remembered in the browser (name, size,
   modified time, its Idempotency-Key): picking the same file again after a
   dropped connection or a reload asks which parts arrived
   (`GET /uploads/{id}/parts`) and sends only the rest.
   - Production (S3): each part goes to a presigned S3 URL, never through
     the web server.
   - Local storage (staging): each part goes through the API,
     `PUT /api/v1/uploads/{id}/parts/{n}`, streamed to
     `src/storage/local_multipart.py`. A released process never uses this.
2. **Check, on the worker.** `POST /api/v1/checks {direct_upload_id}` creates a
   `jobs` row (`stored_check`) and an arq task. The web request never reads
   the file. Stages, written to the job as they start and shown in the work bar
   on every page:
   `verifying` (download, size and SHA-256) -> `unpacking` (a `.gz`, or a ZIP
   with one part) -> `sizing` (memory needed against what the worker can give)
   -> `measuring` (the DFM analysis) -> `pricing` (the cost decision) -> done.
3. **The part.** The analysis keeps the file as the organization's source, the
   worker keeps the 3D preview next to it, and the part's page opens from the
   saved records. The incoming copy is deleted.

Files under 20 MB that aren't compressed keep the one-request check
(`STORED_CHECK_FROM_MB` in `frontend/src/lib/upload-limit.ts`), except a
STEP or IGES file the web process can't hold in memory (below), which goes
to the worker the same way.

A part can also come from a share link (Google Drive, Dropbox, OneDrive or
SharePoint, an S3 object URL): `POST /api/v1/uploads/from-link`, and the
worker's first stage is `fetching` (the link's file to its disk under the
outbound rules) instead of `verifying`; the rest is the same.
`docs/IMPORT_FROM_LINK.md` has the rules.

## Limits

| Limit | Value | Where |
|---|---|---|
| One file, any plan | 2 GiB | `DIRECT_UPLOAD_PART_MAX_BYTES`; `CAD_MAX_BYTES` in `upload-limit.ts` |
| A file unpacked from `.gz`/`.zip` | 2 GiB, at most 200x its compressed size, ZIP at most 64 entries, one part | `src/services/part_archive.py` |
| Uploads at once, per organization | free 2 and 4 GiB; other plans 4 and 10 GiB | `active_upload_count_limit`, `active_upload_bytes_limit` |
| A web request's own upload | 100 MB (`MAX_UPLOAD_MB`) | re-checks from a file in the tab, fixes, Fit |
| What a web request checks | the same memory model against the web process's own budget; on a 4 GB web machine about 9 MB of STEP or IGES, 72 MB of binary STL | `routes.refuse_over_memory_budget` |
| What one worker can check | memory-bound, below | `stored_check_service.check_memory_budget_bytes` |

Over the memory budget the check stops before parsing and says so, for example:
"This file needs about 6.1 GB of memory to check; the largest STEP file
ScaleCAD checks today is about 3 MB. Nothing was charged."

## The web process's memory gate

A web request that checks a file itself (`/validate` and its siblings:
`/validate/cost`, `/validate/preview-mesh`, `/validate/quick`,
`/validate/fit`, `/validate/assembly`, `/validate/demo`, `/validate/repair`,
and the BOM assembly ingest) sizes an STL, STEP or IGES upload with the
worker's model below (`estimate_memory_bytes_for_data`, from the same
bytes) against what its own process gives one check
(`CHECK_MEMORY_BUDGET_MB`, or `CHECK_MEMORY_FRACTION` of its machine). Over
it, the request is refused before parsing: 413 `CHECK_TOO_LARGE`, the
worker's own message, and the big-file endpoints
(`big_file_check: {upload, check}`). `MAX_UPLOAD_MB` stays the outer cap.
On a 4 GB web machine that is about 9 MB of STEP or IGES and 72 MB of binary
STL, so the 20 MB rule alone would leave STEP and IGES files between about
9 and 20 MB refused by the web path.

The app therefore sends a STEP or IGES file to the worker path whenever its
estimated memory is over the web budget, from its size alone
(`overWebCheckMemory` in `frontend/src/lib/upload-limit.ts`: the backend's
`STEP_MEMORY_POINTS` with its 10% headroom, against 0.6 of the 2 GB
production web machine; a test pins both to the backend and `fly.toml`).
When the web path still answers 413 (a web machine with less memory than
that), the live check hands the same file to the worker path and the check
page follows it. A file is then checked by the
worker, or refused there with the same plain message when it is over the
worker's own budget; never just refused by the web path.

## The compute budget: what runs at once

The gates above size one check. What a process holds at once is bounded by its
compute budget (`src/services/compute_budget.py`), one per process (API and
worker), in two dimensions:

- **Memory.** Each piece of work reserves its need from the model below
  (`estimate_memory_bytes_for_data`, with its headroom). The capacity is
  `COMPUTE_MEMORY_BUDGET_MB` when set, otherwise `COMPUTE_MEMORY_FRACTION`
  (default 0.7) of the machine's or container's memory: about 2.8 GB on a
  4 GB web machine and 5.6 GB on an 8 GB worker.
- **Compute slots.** One per piece of work, `COMPUTE_SLOTS` (default
  `max(2, os.cpu_count())`): 2 on a 2-CPU web machine, 4 on a 4-CPU worker.

A piece of work is a check, not a call: a catalog part's analysis, body
split and price share one reservation; so do a request's parse and
analysis, a repair's analyses and repair, a fit's two parts (their needs
added). A cached analysis takes none.

**Held until the work really ends.** `asyncio.wait_for` stops waiting for an
executor thread at its timeout, but the thread computes on and keeps its
arrays. The reservation is given back in the thread's own `finally`, when the
computation returns or raises, never when an await is cancelled; the worker
logs `abandoned_compute_finished` with its duration when such a thread ends.
So a part that ran out of time keeps its room, and its retry waits for room
beside it. Work bigger than the whole budget runs only when nothing else
runs (the per-check refusal above comes first); waiters are served in order.

**Waiting.** Waiting for room is not part of a check's time limit: the timer
starts when the work does.

- A web request (`/validate`, `/validate/cost` and their siblings, the stored
  part's preview, bodies, orientation, repair and fixes) waits at most
  `COMPUTE_WAIT_SECONDS` (default 15) and then answers the existing 429
  `server_busy` with Retry-After. The count gate (`MAX_CONCURRENT_ANALYSES`)
  stays as it was, in front of it: it protects the database pool.
- The worker never fails for room. A batch or catalog item waits as long as
  its arq job (600 s) leaves after its own work (`job_wait_seconds`: for a
  catalog part, 600 s less twice its time limit, less 30 s), then goes back to
  the run as pending, that delivery not counted as a try
  (`batch_tasks._put_back_for_room`). A big file's check or a kept part's job
  goes back to the queue the same way (`stored_check_tasks.requeue_for_room`);
  a check from a share link, whose file was fetched once and isn't kept,
  instead waits as long as its hour allows. A batch's `concurrency_limit`
  (10) is unchanged: the items beyond the budget wait.

## Measurements

Each file was checked by the real worker task (`run_stored_check`: download
and SHA-256, parse, DFM analysis, cost decision, kept source) in a fresh
process with the parse pool warmed and one parse worker
(`PARSE_POOL_WORKERS=1`, as on a 2-CPU machine), one check at a time, niced,
on the shared 4-core staging box (load average 5-10 from other work, so the
times are slower than an idle machine). Memory is the peak resident set of the
process tree (worker plus parse child), sampled every 50 ms; "added" is that
peak minus the warmed worker's own 340-370 MB. Files: dense, watertight
STL meshes; STEP and IGES assemblies of N copies of a bracket (plate, boss,
four holes and a bore; about 58,000 triangles per MB of STEP). Harness:
`measure_check.py` in the session scratchpad.

| File | MB | Triangles | Parse s | Analysis s | Pricing s | Total s | Peak MB | Added MB |
|---|---|---|---|---|---|---|---|---|
| STL | 0.5 | 10,240 | 0.1 | 7.3 | 4.3 | 12 | 499 | 158 |
| STL | 3.9 | 81,920 | 0.3 | 37.9 | 3.4 | 42 | 806 | 461 |
| STL, ASCII | 22.7 | 91,691 | 1.3 | 24.1 | 3.5 | 31 | 810 | 461 |
| STL | 15.6 | 327,680 | 2.0 | 83.8 | 11.0 | 99 | 1,332 | 975 |
| STL | 62.5 | 1,310,720 | 11.4 | 25.0 | 56.6 | 106 | 2,388 | 2,016 |
| STEP, 1 body | 0.04 | - | 9.0 | 3.3 | 1.2 | 23 | 615 | 275 |
| STEP, 30 bodies | 1.2 | - | 11.7 | 13.8 | 18.8 | 56 | 1,087 | 745 |
| STEP, 125 bodies | 4.9 | 345,500 | 35.6 | 13.2 | 71.0 | 120 | 1,879 | 1,531 |
| STEP, 250 bodies | 10.1 | 610,902 | 102.2 | 64.7 | 228.3 | 396 | 2,747 | 2,396 |
| IGES, 30 bodies (open shell) | 1.4 | - | 53.4 | 8.1 | 0.4 | 62 | 756 | 414 |
| IGES, 125 bodies (open shell) | 5.7 | 167,448 | 194.8 | 7.5 | 0.6 | 203 | 1,007 | 660 |

What the numbers say:

- Memory follows the triangle count, not the file size: an ASCII STL of
  91,691 triangles (22.7 MB) needs the same 461 MB as a binary one of 81,920
  (3.9 MB). About 2-4 KB per triangle up to a few hundred thousand, about
  1 KB per triangle past a million (the analysis decimates to
  `MAX_ANALYSIS_FACES`, 250,000; parsing and pricing see the whole mesh).
- STEP is the expensive format: about 160-200 MB of memory per MB of file for
  these assemblies, because one MB of STEP becomes tens of thousands of
  triangles and the parse holds the OpenCASCADE model as well.
- Time: STL about 1.6-6 s per MB at these sizes; STEP about 25-40 s per MB.
  For STEP, pricing re-tessellates the part (the parsed-mesh cache doesn't
  hold meshes this large), which is more than half of the 10 MB case; reusing
  the analysis mesh would roughly halve big STEP checks.
- The IGES files tessellated as open shells (trimmed surfaces, not solids),
  so they were never priced and needed less memory than a solid would; IGES
  is sized with STEP's curve. Their parse is the slowest: about 35 s per MB.
- Today's web limit, 100 MB, is beyond what a 2 GB machine holds: a 100 MB
  STL is 2 M triangles (about 3 GB); a 10 MB STEP assembly needed 2.4 GB.

## Proposed caps

The worker gives one big check `CHECK_MEMORY_FRACTION` (0.6) of its machine's
memory (or `CHECK_MEMORY_BUDGET_MB`), leaving the rest for the worker itself
and the parts it checks for batch and catalog runs at the same time. The need
is interpolated from the table above with 10% headroom
(`stored_check_service.estimate_memory_bytes`).

| Worker memory | Budget for one check | Largest binary STL | Largest STEP or IGES (assemblies like these) |
|---|---|---|---|
| 2 GB (production before 2026-10-22) | 1.2 GB | 22 MB (0.46 M triangles) | 3 MB |
| 4 GB (web machines, fly.toml) | 2.4 GB | 72 MB (1.5 M) | 9 MB |
| 8 GB (worker machines, fly.toml and infra/aws) | 4.8 GB | 173 MB (3.6 M) | 22 MB |
| 16 GB | 9.6 GB | 374 MB (7.9 M) | 49 MB |
| 32 GB | 19.2 GB | 777 MB (16 M) | 102 MB |

STEP caps depend on how much geometry a MB holds: a single freeform part can
tessellate denser than these brackets, a simple prismatic one sparser. The
estimate is by file size because the triangle count is only known after the
parse; an over-estimate is refused honestly rather than run out of memory.
Rows past 2.4 GB of need are extrapolated from the last measured slope.

Time budget for one big check: 120 s plus 5 s per MB of STL, 90 s per MB of
STEP and 100 s per MB of IGES (about twice the measured), capped at 55 minutes
(the task's own arq ceiling is 60).

## Larger files: a worker that starts only when one arrives

Not built; no infrastructure config was changed. What it would take on Fly:

- **A second arq queue.** `BigWorkerSettings` in `src/jobs/worker.py`:
  `queue_name = "arq:queue:big"`, `functions = [run_stored_check]`,
  `max_jobs = 1`, `burst = True` (it exits when the queue is empty),
  `job_timeout = 3600`. `POST /api/v1/checks` sends a file whose need is
  over the normal worker's budget but under the big machine's to that queue
  instead of refusing it.
- **A big machine that is stopped until needed.** One Fly Machine in the API
  app, process `arq src.jobs.worker.BigWorkerSettings`, size for example
  `performance-4x` with 16 GB (budget about 9.6 GB: STL to ~370 MB, STEP to
  ~50 MB) or `performance-8x` with 32 GB (STEP to ~100 MB), created once and
  left stopped. A stopped machine costs only its root filesystem.
- **Starting it.** When a job lands on the big queue, the API (or the normal
  worker's cron, every 30 s) calls the Machines API,
  `POST /v1/apps/cadvrfy-api/machines/{id}/start`, with a deploy-scoped
  `FLY_API_TOKEN` secret. A stopped machine starts in a few seconds; it
  drains the queue and exits (`burst`), and Fly marks it stopped. If two
  big files arrive, the second waits in the queue (`max_jobs = 1`), and the
  work bar says "Waiting for a worker".
- **Releases.** The deploy workflow must update the big machine's image with
  the others (`fly machine update --image` in `saas-promote.yml`), and the
  health gate must not count a stopped big machine as down.
- **The honest message stays** for files over even the big machine's budget,
  naming its size.

Cost (Fly list prices as I last knew them; check fly.io/docs/about/pricing
before deciding): a `performance-4x` machine is about $0.17 an hour plus about
$5 a month per GB of RAM over its included 8 GB, so 16 GB is about $0.23 an
hour while running; `performance-8x` with 32 GB about $0.46 an hour. Billing is
per second while started. A 50 MB STEP at the measured ~40 s per MB is about
35 minutes, so roughly $0.13 on 16 GB; 100 such checks a month about $13. Idle
cost is the stopped machine's root filesystem, cents a month. Work to build:
about two days (queue routing, the starter, the deploy and health-gate changes,
tests with a fake Machines API).

## A big kept part: re-priced and repaired on the worker

A saved part is re-priced (`POST /parts/{hash}/recheck`: another material,
quantities, machines, orientation) and repaired (`POST /parts/{hash}/repair`)
from the file its organization kept. When the kept file is 20 MB or more
(`KEPT_PART_WORKER_FROM_MB`), over `MAX_UPLOAD_MB`, or needs more memory than
the web process gives one check, the route never reads it
(`src/services/kept_part_jobs.py` sizes it from its size and first bytes): it
starts the same job type as a big check (`stored_check`, `params.source =
kept`) and answers 202 with the job's status. The worker
(`src/jobs/kept_part_tasks.py`, run by `run_stored_check`) sizes the file
against its own memory (`sizing`), then runs the route's own code under the
big-check limits (`pricing` or `repairing`; a worker repair takes up to
`REPAIR_MAX_FACES_WORKER`, 5 M faces, and the time budget for the file's
size). `GET /api/v1/checks/{id}` returns the route's response as `result`
once done; the work bar shows it on every page. Nothing is charged: neither
uses a check.

## A catalog run's large ZIP: unpacked on the worker

A catalog run's ZIP of 20 MB or more uploads to storage in parts
(`direct_upload_id`). `POST /api/v1/catalog-runs` no longer reads it back:
it checks the upload (a finished batch ZIP of this organization, within the
run's size limit, and no other free run of the account going), attaches it to
a new run whose options (material, quantity, parts list) go with the batch,
and answers 202 with `preparing: true`. The worker's direct-upload preparation
(`batch_tasks.prepare_direct_upload_batch`) downloads it (size and SHA-256
verified), unpacks it with the same extraction limits as a posted ZIP, gives
each part its quantities and material, and reserves the free allowance with
the items in one transaction (`catalog_run_service.prepare_items`,
`reserve_prepared_run`). A refusal there (the allowance, a damaged upload, a
bad ZIP) ends the run with its reason on it: the board's `failure`, which the
app shows where the run was started. Deploy the worker with or before the
API: an older worker would prepare such a run as a pilot batch.

## Not done here
- Import from a link is built (`docs/IMPORT_FROM_LINK.md`); the providers'
  pickers for files that aren't shared publicly are not.
