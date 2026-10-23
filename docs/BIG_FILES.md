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

**Under load.**

- A STEP/IGES parse or assembly extraction waits for one of the parse pool's
  slots (`parse_pool.pool_slot`) before its timer starts, so the assembly
  probe's 60 s and a parse's own limit are spent on its own extraction, not
  behind other parts'.
- The ladder's rung caps (24 / 15 / 15 s for a 60 s budget) are CPU seconds in
  the rung's parse worker (read from `/proc`), the part's own work, the same
  on an idle or a loaded box: a rung that uses its cap doesn't converge, and
  the ladder tries the next strategy, as before. Wall time only bounds the
  whole ladder (the route's budget less 2 s). Running out of it first means the
  worker was starved, not that the part is bad: the ladder stops there, never
  trying another strategy (another mesh) because of time, and the answer is
  busy, not "this file can't be meshed": the API's 429 `server_busy`; a
  catalog part is checked again after the rest of its run; a big file's check
  ends `CHECK_BUSY`, nothing charged. A geometry failure (gmsh raises, no
  surfaces, an open shell) still moves to the next strategy.
- A rung that hits its cap, or whose request went away, no longer SIGKILLs
  the whole shared pool (which broke every other request's parse in flight):
  the pool is retired (`parse_pool.retire_pool`). New work goes to a fresh
  pool, and the old one, the stuck worker with it, is killed once its other
  parses have finished, or after `RETIRE_GRACE_SEC` (30 s).
- After heavy work the process hands freed heap back to the OS
  (`malloc_trim(0)`, at most every 2 s), and the budget never gives more than
  0.9 of the machine's memory less the process tree's own resident memory,
  measured when it was last idle (the interpreter, the warm parse workers and
  whatever the heap kept).

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

### Catalog parts (2026-10-22)

The heaviest parts of the tester's 298-part catalog
(`Ridgeline_bought_parts_2026Q3`), each through the real catalog item task
(`batch_tasks.run_batch_item`: the analysis, the body split, the price with
the org's machines) in a fresh process, the parse pool warmed with one
worker, one part at a time, the process tree sampled every 50 ms, niced, on
the shared 4-core box at load average 6-14 (times are slow). "Added" is the
peak above the warmed process's own 336-341 MB. Model before and after are
the reservation (`estimate_memory_bytes_for_data`, with its 1.1 headroom).
Harness: `m1/measure_catalog_part.py` in the session scratchpad.

| Part | KB | Faces | Outcome | Added MB | Model before | Model after |
|---|---|---|---|---|---|---|
| machined/manifolds/RFS-21513.step | 89 | 161,754 | priced | 509 | 326 | 902 |
| machined/manifolds/RFS-21527.step | 89 | 161,640 | priced | 395 | 326 | 902 |
| machined/manifolds/RFS-21404.step | 36 | 179,408 | priced | 377 | 302 | 902 |
| machined/manifolds/RFS-21437.step | 28 | 189,526 | priced | 414 | 301 | 902 |
| machined/plates/RFS-21347.step | 69 | 129,164 | priced | 314 | 317 | 902 |
| machined/misc/nist_periodic_ctc05.stp | 319 | 112,428 | priced (recovered on a later rung) | 189 | 429 | 902 |
| supplier-iges/RFS-21996.iges | 37 | 179,428 | open shell, not priced | 515 | 302 | 902 |
| supplier-iges/RFS-21998.iges | 18 | 185,386 | priced | 459 | 300 | 902 |
| supplier-iges/bored-block-inch.iges | 18 | 185,296 | priced | 515 | 300 | 902 |
| broken/missing-face-box.step | 24 | 106,768 | GEOMETRY_INVALID | 449 | 301 | 902 |
| broken/open-plane-mm.iges | 2 | 44,570 | GEOMETRY_INVALID | 297 | 297 | 902 |
| broken/wire_only_unmeshable.step | 2 | none | can't be meshed (400) | 185 | 297 | 902 |
| broken/RFS-29071.step | 15 | none | unreadable (400) | 8 | 299 | 902 |
| broken/trap-nonmanifold-missing-face.stl | 1 | 11 | GEOMETRY_INVALID | 12 | 165 | 165 |
| printed/trap-trapped-hollow-sphere.stl | 500 | 10,240 | priced | 50 | 174 | 174 |
| assemblies/bracket-assembly.step | 37 | 129,928 | priced body by body | 1,687 | 303 | 902 |
| broken/unsewn-box.step | 29 | 146,780 (open) | stopped at 6.1 GB | over 5,856 | 299 | 902 |

What the numbers say:

- Memory follows the triangle count, and a small STEP or IGES file says
  nothing about it: the 28-90 KB manifolds and IGES blocks tessellate to
  160-190k faces and need 377-515 MB, up to 3.15 KB a face, where the old
  curve gave a 30 KB file 301 MB. A small file can tessellate up to the
  mesher's face budget (250,000 faces, `step_mesher`), about 790 MB at that
  rate. So the STEP and IGES curve now starts at **820 MB** (902 MB with the
  headroom) and stays there until the bracket assemblies' curve passes it at
  1.52 MB; the 0.036 MB, 275 MB point of a sparse one-body bracket is gone. The
  frontend's copy (`upload-limit.ts`) moved with it.
- The change doesn't move what one check may hold: the largest STEP or IGES
  file is still 2.94 MB at a 1,229 MB budget, 9.10 MB at 2,457 MB (a 4 GB web
  machine) and 22.41 MB at 4,915 MB (an 8 GB worker); above 1.52 MB the curve
  is the same.
- Some parts are over-reserved, and that is kept: nist's periodic part needs
  189 MB (its faces come from a coarse recovery rung), STL is sized by its exact
  triangle count and the small STLs need far less than the model's 150 MB base.
- **Multi-body files are outside the model.** A file that splits into bodies
  is checked body by body (`catalog_bodies.check_file_bodies`), and
  `part_types.describe` measures contact between every pair of bodies:
  `contact_between` calls `trimesh.proximity.closest_point` with up to 3,000
  sample points against the other body's faces in the shared box, and on big
  open sheets every point's candidates are most of the sheet. bracket-assembly
  needed 1.7 GB; unsewn-box's main process grew about 100 MB a second until the
  harness stopped it at 6.1 GB (its parse worker stayed at 230 MB). No
  file-size model can size that; its fix (bounding that call's memory) is
  separate work. Until then a run with such a file can use more than its
  reservation.

### What a long-running process keeps

The proof run's worker held about 3.1 GB in its main process with three
catalog parts (about 0.9 GB reserved) in flight: memory the allocator kept
from earlier parts, not live arrays. Eleven catalog parts priced four at a
time in one process (parsed in pool workers, as a web process does;
`m1/retained_probe.py`), main process RssAnon in MB, two runs each:

| | Peak | Idle after | After gc | After `malloc_trim(0)` |
|---|---|---|---|---|
| default glibc arenas | 1,664 / 1,623 | 1,516 / 1,542 | 1,324 / 1,409 | 318 / 423 |
| `MALLOC_ARENA_MAX=2` | 1,196 / 1,365 | 1,196 / 1,266 | 1,064 / 1,087 | 202 / 178 |

`malloc_trim(0)` gives back about 1 GB; two arenas lower the peak by 15-30%
and leave less behind (the wall times, 343-567 s, moved with the box's load,
not with the setting). The budget trims after heavy work (at most every 2 s),
and its capacity counts the resident memory that no reservation explains.

### A 60-part catalog run on the budget

60 parts of the same catalog, the heavy ones above included, one run on a
private API and worker (`COMPUTE_MEMORY_BUDGET_MB=5734`, `CHECK_MEMORY_BUDGET_MB=4915`,
as an 8 GB worker), run concurrency 10, on the shared box at load average
11-14:

| | Before (staging, 298 parts, 10 in flight) | With the budget (60 parts) |
|---|---|---|
| Peak resident (worker) | killed by the kernel at 6.1 GB, then 8.8 GB; main 6.0 GB | 3.8 GB tree, main 3.1 GB; mean 2.1 GB |
| Threads | 22 -> 43-54 | at most 79 (the 64-thread pool) |
| Finished | OOM-killed twice | 57 checked (3 GEOMETRY_INVALID), 3 refused as broken files, none lost |
| Time | - | 32 min 23 s in all; a part's own time median 87 s, p90 206 s, max 304 s |
| Ran out of time | `cost_timeout` at 180 s, retried beside its running thread | one part's analysis (RFS-21722), its thread ended 6.8 s later, its room held until then; checked again after the run, done in 76 s |

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
