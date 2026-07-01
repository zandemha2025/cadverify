# Run CadVerify as a local web app

One step. No terminal knowledge needed. No signup, no API key. Your CAD files
stay on your Mac — they are parsed in memory and never uploaded anywhere.

## Start it

Either:

- **Double-click** `scripts/run-local-app.sh` in Finder, **or**
- Open Terminal and run:

  ```bash
  bash scripts/run-local-app.sh
  ```

> First-run note: if double-clicking opens the file in a text editor instead of
> running it, right-click the file → **Open With → Terminal**, or use the
> `bash scripts/run-local-app.sh` command above.

## What happens

1. The backend (the cost/decision engine) starts on `http://127.0.0.1:8000`.
2. The web app (the page you use) starts on `http://localhost:3000`.
3. Your browser opens automatically to **http://localhost:3000/cost**.
4. Drag a CAD file (`.stl`, `.step`, or `.stp`) onto the page. In a few seconds
   you get the **should-cost** ($/unit by quantity), **lead time**, and the
   **make-vs-buy** decision with a full, provenance-tagged driver breakdown.

The very first time you drop a file the page may take a few seconds to "warm
up" (compile) — that is normal and only happens once per launch.

## Stop it

Press **Ctrl-C** in the Terminal window that opened. Both the web app and the
backend shut down cleanly and the ports are released. (Re-running the launcher
also frees the ports first, so it is always safe to run again.)

## Local-only guarantee

- No account, no login, no API key required.
- The cost page uses a public **local** endpoint (`/api/v1/validate/cost/demo`)
  that does **not** save your files, does **not** write to any database, and
  makes **no** network calls with your CAD. Everything runs on `localhost`.
- Nothing about your part leaves this machine.

## If something doesn't start

- "uvicorn not installed" — run once:
  ```bash
  backend/.venv/bin/python -m pip install "uvicorn[standard]"
  ```
- "frontend/node_modules missing" — run once:
  ```bash
  (cd frontend && npm install)
  ```
- Ports busy / a previous run is stuck — just run the launcher again; it frees
  ports 8000 and 3000 before starting.
