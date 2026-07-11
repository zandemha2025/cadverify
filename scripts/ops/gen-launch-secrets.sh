#!/usr/bin/env bash
# Generate fresh, random values for every CadVerify backend secret that needs
# one, and print ready-to-paste `fly secrets set` lines for the `cadvrfy-api`
# Fly app. Secrets that must come from an external provider (Neon, Upstash/Fly
# Redis, Resend, Cloudflare Turnstile, S3, Sentry) are printed as
# `<FILL_ME: ...>` placeholders with a one-line note on where to get them --
# this script never invents those.
#
# The exact secret list mirrors scripts/ops/fly-required-secrets-gate.mjs
# (the CI gate that fails the deploy if any of these are missing on the Fly
# app), plus the object-store S3 secrets, which are optional (local-volume is
# the default backend) but recommended -- see docs/LAUNCH_RUNBOOK.md section 4.
#
# Usage:
#   bash scripts/ops/gen-launch-secrets.sh
#   bash scripts/ops/gen-launch-secrets.sh > /tmp/cadvrfy-secrets.sh   # then fill placeholders, review, run
#
# Safety:
#   - Every value below is generated locally in this process and printed once
#     to stdout -- nothing is sent anywhere, nothing is written to a file by
#     this script itself, and no real secret is hardcoded in this file.
#   - Redirect stdout to a file OF YOUR OWN CHOOSING if you want to edit the
#     placeholders before running the `fly secrets set` lines; that file will
#     contain real secrets once generated, so treat it like a credential file
#     (do not commit it, delete it after use).
set -euo pipefail

APP="${CADVERIFY_FLY_APP:-cadvrfy-api}"

# -- random-value generation -------------------------------------------------
# Standard (RFC 4648 "+/") base64 of 32 random bytes. This is what
# backend/main.py's _assert_production_secrets() and src/auth/hashing.py
# expect for SESSION_SECRET-adjacent values: base64.b64decode(...) must decode
# to >= 32 bytes. Prefers python3 (no extra deps needed, just stdlib base64);
# falls back to openssl.
gen_b64_32() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
  elif command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 32
  else
    echo "ERROR: need python3 or openssl to generate secrets" >&2
    exit 1
  fi
}

# URL-safe base64 of 32 random bytes -- the Fernet key format required
# specifically by CONNECTOR_SECRET_KEY (src/services/connector_credentials_service.py
# calls Fernet(key), which requires urlsafe base64 of exactly 32 bytes; the
# standard '+/' alphabet from gen_b64_32 will fail that check whenever the
# random bytes happen to need a '+' or '/'). This does NOT require the
# `cryptography` package to generate -- only to later consume it, which the
# backend image already has (it's a direct import, not lazy, in that module).
gen_fernet_key() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
  elif command -v openssl >/dev/null 2>&1; then
    # Translate standard base64 to the url-safe alphabet Fernet requires.
    openssl rand -base64 32 | tr '+/' '-_'
  else
    echo "ERROR: need python3 or openssl to generate secrets" >&2
    exit 1
  fi
}

SESSION_SECRET="$(gen_b64_32)"
DASHBOARD_SESSION_SECRET="$(gen_b64_32)"
API_KEY_PEPPER="$(gen_b64_32)"
MAGIC_LINK_SECRET="$(gen_b64_32)"
CONNECTOR_SECRET_KEY="$(gen_fernet_key)"
CONNECTOR_FINGERPRINT_KEY="$(gen_b64_32)"

cat <<BANNER
# ==========================================================================
# CadVerify launch secrets for Fly app: ${APP}
# Generated at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
#
# This output contains REAL random secrets below (the "generated" block).
# Treat it like a credential file: don't paste it into chat, don't commit it,
# don't leave it in shell history longer than you need to.
#
# Review, fill in the <FILL_ME: ...> placeholders from the noted source, then
# run the fly secrets set lines (or pipe this whole block through a shell
# after editing). See docs/LAUNCH_RUNBOOK.md section 3 for full context.
# ==========================================================================

# --- Generated (random, safe to use as-is) --------------------------------

fly secrets set --app ${APP} \\
  SESSION_SECRET='${SESSION_SECRET}' \\
  DASHBOARD_SESSION_SECRET='${DASHBOARD_SESSION_SECRET}' \\
  API_KEY_PEPPER='${API_KEY_PEPPER}' \\
  MAGIC_LINK_SECRET='${MAGIC_LINK_SECRET}' \\
  CONNECTOR_SECRET_KEY='${CONNECTOR_SECRET_KEY}' \\
  CONNECTOR_FINGERPRINT_KEY='${CONNECTOR_FINGERPRINT_KEY}'

# --- External: database (Neon) --------------------------------------------
# Get both from the Neon project dashboard -> Connection Details.
# DATABASE_URL: the POOLED connection string (Neon's pgbouncer endpoint,
#   "...-pooler..." host) -- used for normal app traffic.
# DATABASE_URL_DIRECT: the DIRECT (non-pooled) connection string -- used only
#   by the Fly release_command (alembic upgrade head), which bypasses
#   PgBouncer for DDL (backend/fly.toml's [deploy] block).

fly secrets set --app ${APP} \\
  DATABASE_URL='<FILL_ME: Neon pooled connection string, postgresql://...>' \\
  DATABASE_URL_DIRECT='<FILL_ME: Neon direct (unpooled) connection string>'

# --- External: Redis (Upstash or Fly Redis) --------------------------------
# Get from your Upstash Redis dashboard (rediss://... TLS URL), or run
# "fly redis status <name>" if using Fly's own Redis. Powers arq jobs, rate
# limiting, magic-link tokens, and /health's async-tier probe.

fly secrets set --app ${APP} \\
  REDIS_URL='<FILL_ME: redis(s)://... connection string>'

# --- External: Resend (magic-link email) -----------------------------------
# RESEND_API_KEY: Resend dashboard -> API Keys.
# RESEND_FROM: a verified sender address on a domain you verified in Resend
#   (Resend dashboard -> Domains); unverified senders will fail to send.

fly secrets set --app ${APP} \\
  RESEND_API_KEY='<FILL_ME: Resend API key, re_...>' \\
  RESEND_FROM='<FILL_ME: verified sender, e.g. login@yourdomain.com>'

# --- External: your production domain --------------------------------------
# DASHBOARD_ORIGIN: the frontend's public origin (e.g. https://app.yourco.com
# or https://cadvrfy-web.fly.dev if using the *.fly.dev domain directly). Used
# to build magic-link URLs, OAuth/OIDC/SAML redirect targets, and login
# redirects -- src/auth/magic_link.py, src/auth/oauth.py, src/auth/oidc.py,
# src/auth/saml.py all read it.

fly secrets set --app ${APP} \\
  DASHBOARD_ORIGIN='<FILL_ME: https://your-production-frontend-origin>'

# --- External: Cloudflare Turnstile (captcha on magic-link send) -----------
# Cloudflare dashboard -> Turnstile -> your widget -> Secret Key.
# NOTE: the backend reads TURNSTILE_SECRET (src/auth/turnstile.py), NOT
# TURNSTILE_SECRET_KEY -- some docs/.env.example files in this repo use the
# wrong name; using the wrong name here will silently defeat the secrets gate
# (fly-required-secrets-gate.mjs checks the same TURNSTILE_SECRET name).

fly secrets set --app ${APP} \\
  TURNSTILE_SECRET='<FILL_ME: Cloudflare Turnstile secret key>'

# --- Optional but recommended: Sentry (error reporting) ---------------------
# sentry.io -> your project -> Settings -> Client Keys (DSN).
# SENTRY_DSN (backend, main.py sentry_sdk.init): a plain Fly secret works --
# read live from process.env at request time. Set it here:

fly secrets set --app ${APP} \\
  SENTRY_DSN='<FILL_ME: optional, Sentry DSN for the backend project>'

# NEXT_PUBLIC_SENTRY_DSN (frontend, frontend/instrumentation-client.ts +
# frontend/sentry.server.config.ts) is DIFFERENT: Next.js inlines
# NEXT_PUBLIC_* vars into the BROWSER bundle at build time, at "next build"
# (verified empirically against this repo's build). Running fly secrets set
# --app cadvrfy-web NEXT_PUBLIC_SENTRY_DSN=... would only affect the
# frontend's server-side Sentry -- it would NEVER reach the browser, silently.
# To actually enable browser-side Sentry you must set a GitHub Actions
# REPOSITORY secret (not a Fly secret) named NEXT_PUBLIC_SENTRY_DSN --
# Settings -> Secrets and variables -> Actions -- which .github/workflows/
# ci.yml's "Build frontend production image" step passes as a Docker
# build-arg (see frontend/Dockerfile). See docs/LAUNCH_RUNBOOK.md section 3
# for the full explanation. Nothing to run here; this is a one-time GitHub
# Settings change, not a fly secrets set command.

# --- Optional but recommended: S3 object storage (durability) --------------
# Only needed if you set OBJECT_STORE_BACKEND=s3 (see docs/LAUNCH_RUNBOOK.md
# section 4 for why this is recommended over the default local Fly volume,
# and for a required requirements.txt change before this works in prod).
# AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY: from your AWS IAM user (or your
#   S3-compatible provider's equivalent), scoped to only this bucket.
# OBJECT_STORE_S3_BUCKET: the bucket name you created.
# OBJECT_STORE_S3_REGION: the bucket's region (omit for some non-AWS S3
#   providers; see OBJECT_STORE_S3_ENDPOINT below).
# OBJECT_STORE_S3_ENDPOINT: only set for a non-AWS S3-compatible endpoint
#   (e.g. MinIO, Cloudflare R2, Backblaze B2); omit entirely for real AWS S3.

# fly secrets set --app ${APP} \\
#   OBJECT_STORE_BACKEND='s3' \\
#   AWS_ACCESS_KEY_ID='<FILL_ME: IAM access key id>' \\
#   AWS_SECRET_ACCESS_KEY='<FILL_ME: IAM secret access key>' \\
#   OBJECT_STORE_S3_BUCKET='<FILL_ME: your-bucket-name>' \\
#   OBJECT_STORE_S3_REGION='<FILL_ME: e.g. us-east-1>'
BANNER
