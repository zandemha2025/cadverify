# Run ProofShape as a local web app

One step. No terminal knowledge needed. The full platform is account-gated, so
create a local email/password account on first launch. Your CAD files stay on
your Mac and the app talks only to your local backend unless you configure
external services yourself.

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
3. Your browser opens automatically to **http://localhost:3000**.
4. Sign up or log in with a local account. Passwords need at least 8 characters,
   one letter, and one digit.
5. Use the app navigation to open **Cost**, **Analyze**, **Batch**, **Verify**,
   **Cost Decisions**, **RFQ Packages**, or **Integrations**. Drag a CAD file
   (`.stl`, `.step`, `.stp`, `.iges`, or `.igs`) into the relevant workflow to
   get DFM results, should-cost, provenance, and make-vs-buy evidence.

The very first time you drop a file the page may take a few seconds to "warm
up" (compile) — that is normal and only happens once per launch.

## Stop it

Press **Ctrl-C** in the Terminal window that opened. Both the web app and the
backend shut down cleanly and the ports are released. (Re-running the launcher
also frees the ports first, so it is always safe to run again.)

## Local-only guarantee

- A local account is required for the full platform because saved decisions,
  org settings, RFQ packages, notifications, and audit trails are tenant-scoped.
- The historical public cost-demo endpoint (`/api/v1/validate/cost/demo`) remains
  local-only, but the product surface is intentionally auth-gated.
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
