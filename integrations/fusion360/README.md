# ScaleCAD Check — Fusion 360 add-in

One command, **Check with ScaleCAD**, inside Fusion: silent STEP AP242
export of the active design → one API-key check (DFM verdict + should-cost
with honest bands) → task-pane palette with the issues, the costs, and a
deep link to the full report.

## Install (direct distribution, v1)

1. Package (or download the released zip): `./package.sh` →
   `dist/scalecad-fusion-addin.zip`
2. Fusion 360 → **UTILITIES → ADD-INS → Add-Ins tab** → green ➕ → select
   the unzipped folder (the one containing `ScaleCADCheck.py`).
3. Run **Check with ScaleCAD** once — it opens the palette and asks for:
   - **API origin** — the public API address shown on the web app's
     `/developers` page (e.g. `https://scalecad-api.onrender.com`)
   - **API key** — web app → **Settings → Developer → New key**, scope
     **read+write** (checks are writes). The key is stored only on this
     machine, `~/.scalecad-addin/settings.json`, mode 600.
4. Open a part, run the command again.

Uninstall: remove the add-in in the same panel and delete
`~/.scalecad-addin/`.

## What it never does

- No proprietary-format parsing: Fusion's own exporter writes the STEP.
- Nothing leaves the machine except the STEP bytes of the part you checked,
  to the origin you configured, over the API key you pasted.
- The friction log (`~/.scalecad-addin/friction.jsonl`) is a LOCAL file; it
  is shared only if you choose to attach it.

## The activation gate (definition of done)

> The add-in is done when an engineer who has never seen it completes a
> check unaided on their own design.

Protocol for the tester:

1. A practicing engineer (not the author) receives only the zip and the
   one-line pitch: *"check a part's manufacturability and cost inside
   Fusion."*
2. They install and run it with no help. Every stumble is a friction event.
3. Afterwards, attach `~/.scalecad-addin/friction.jsonl`. The log records:
   add-in load, settings missing/saved, check started, STEP export size,
   upload path taken (direct vs resumable), check latency, check done, and
   every error with its plain-words advice.
4. Failures of the gate: any "settings_missing" after the settings screen
   was shown, any error the tester could not self-resolve from the advice
   text, or an abandoned run (check_started with no check_ok/check_error).

Status: **PENDING — no stranger has run it yet** (the in-Fusion layer,
`ScaleCADCheck.py` + `step_export.py`, needs a real Fusion install; the
client, view model, and their contract tests run in CI).

## Repository layout

- `ScaleCADCheck.py` — Fusion entry (all `adsk` imports live here)
- `step_export.py` — the ExportManager shim (thin; covered by the in-tool smoke)
- `scalecad_client.py` — pure stdlib API client (direct + resumable flows,
  plain-words error mapping, friction log)
- `view_model.py` — pure response → palette model
- `palette.html` — the task-pane UI (settings + results)
- `tests/` — contract tests against a live local stub of the API (CI)

CI: `python -m pytest integrations/fusion360/tests/` (Backend Tests job).
