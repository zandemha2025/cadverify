#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
RUN_ID="${E2E_RUN_ID:-$(date -u +%Y-%m-%d)}"
OUT_DIR="${E2E_ARTIFACT_DIR:-$ROOT/.gstack/qa-reports}"
mkdir -p "$OUT_DIR"

REPORT="$OUT_DIR/postgres-restore-drill-$RUN_ID.json"
DATABASE_URL="${DATABASE_URL:-}"

if [ -z "$DATABASE_URL" ]; then
  echo "DATABASE_URL is required" >&2
  exit 1
fi

for bin in pg_dump pg_restore psql; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "$bin is required for restore drill" >&2
    exit 1
  fi
done

eval "$(
  python3 - "$DATABASE_URL" <<'PY'
import re
import sys
from urllib.parse import urlparse, urlunparse

raw = sys.argv[1]
parsed = urlparse(raw)
if parsed.scheme not in ("postgresql", "postgresql+asyncpg"):
    raise SystemExit("DATABASE_URL must be a postgres URL")
host = parsed.hostname or ""
if host not in ("localhost", "127.0.0.1", "postgres") and not raw.startswith("postgresql://cadverify:cadverify_ci@localhost:"):
    if not bool(__import__("os").environ.get("RESTORE_DRILL_ALLOW_REMOTE")):
        raise SystemExit("refusing restore drill against non-local host %r" % host)
dbname = (parsed.path or "/").lstrip("/")
if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", dbname):
    raise SystemExit("unsafe database name %r" % dbname)
restore_db = re.sub(r"[^A-Za-z0-9_]", "_", dbname + "_restore_drill")
admin = parsed._replace(scheme="postgresql", path="/postgres")
restore = parsed._replace(scheme="postgresql", path="/" + restore_db)
source = parsed._replace(scheme="postgresql")
print("ADMIN_URL=%s" % urlunparse(admin))
print("RESTORE_URL=%s" % urlunparse(restore))
print("RESTORE_DB=%s" % restore_db)
print("SOURCE_URL=%s" % urlunparse(source))
print("DBNAME=%s" % dbname)
PY
)"

# ---------------------------------------------------------------------------
# In-place full-cycle drill (RESTORE_DRILL_MODE=inplace)
#
# Unlike the default side-DB verification below (which restores into a scratch
# "<db>_restore_drill" database and checks table/alembic counts), the in-place
# mode exercises the REAL disaster-recovery path against the target database:
#   (a) apply migrations (alembic upgrade head) + seed a KNOWN marker row
#   (b) pg_dump --format=custom
#   (c) DROP + CREATE the target DB itself (template0, UTF8)
#   (d) pg_restore into the recreated DB
#   (e) verify the known marker row survived the round-trip
# This DESTROYS and rebuilds the target DB, so it is opt-in and only runs
# against a dedicated ops database. It is safe on the CADVerify ops DB.
# ---------------------------------------------------------------------------
if [ "${RESTORE_DRILL_MODE:-sidedb}" = "inplace" ]; then
  ROOT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  BACKEND_DIR="${BACKEND_DIR:-$ROOT_DIR/backend}"
  PYTHON_BIN="${RESTORE_DRILL_PYTHON:-$BACKEND_DIR/.venv/bin/python}"
  MARKER_ID="drill-$(date -u +%Y%m%dT%H%M%SZ)-$$"
  DUMP="$(mktemp -d)/cadverify_inplace.dump"

  echo "== CADVerify in-place restore drill =="
  echo "target_db=$DBNAME  host=$(python3 -c 'import sys,urllib.parse as u;print(u.urlparse(sys.argv[1]).hostname)' "$SOURCE_URL")  marker=$MARKER_ID"
  echo

  echo "-- (a) apply migrations: alembic upgrade head --"
  ( cd "$BACKEND_DIR" && DATABASE_URL="$SOURCE_URL" "$PYTHON_BIN" -m alembic upgrade head )
  ALEMBIC_HEAD="$( ( cd "$BACKEND_DIR" && DATABASE_URL="$SOURCE_URL" "$PYTHON_BIN" -m alembic current 2>/dev/null ) | tail -1 )"
  echo "alembic current: ${ALEMBIC_HEAD:-<none>}"
  echo

  echo "-- (a) seed known marker row --"
  psql "$SOURCE_URL" -v ON_ERROR_STOP=1 -c \
    "CREATE TABLE IF NOT EXISTS ops_restore_drill_marker (marker_id text PRIMARY KEY, note text, created_at timestamptz NOT NULL DEFAULT now());"
  psql "$SOURCE_URL" -v ON_ERROR_STOP=1 -c \
    "INSERT INTO ops_restore_drill_marker (marker_id, note) VALUES ('$MARKER_ID', 'restore-drill known row');"
  PRE_COUNT="$(psql "$SOURCE_URL" -tAc "SELECT count(*) FROM ops_restore_drill_marker WHERE marker_id = '$MARKER_ID';" | tr -d '[:space:]')"
  echo "seeded marker rows (pre-dump): $PRE_COUNT"
  echo

  echo "-- (b) pg_dump --format=custom --"
  START="$(date +%s)"
  pg_dump --format=custom --no-owner --file "$DUMP" "$SOURCE_URL"
  DUMP_BYTES="$(wc -c < "$DUMP" | tr -d ' ')"
  DUMP_SHA="$(sha256sum "$DUMP" 2>/dev/null | awk '{print $1}')"
  echo "dump bytes=$DUMP_BYTES sha256=$DUMP_SHA"
  echo

  echo "-- (c) DROP + CREATE target DB (template0, UTF8) --"
  psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"$DBNAME\" WITH (FORCE);"
  psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$DBNAME\" TEMPLATE template0 ENCODING 'UTF8';"
  RECREATED_ENC="$(psql "$SOURCE_URL" -tAc "SHOW server_encoding;" | tr -d '[:space:]')"
  echo "recreated encoding: $RECREATED_ENC"
  echo

  echo "-- (d) pg_restore into recreated DB --"
  pg_restore --no-owner --dbname "$SOURCE_URL" "$DUMP"
  END="$(date +%s)"
  echo

  echo "-- (e) verify known marker row survived --"
  POST_COUNT="$(psql "$SOURCE_URL" -tAc "SELECT count(*) FROM ops_restore_drill_marker WHERE marker_id = '$MARKER_ID';" | tr -d '[:space:]')"
  TABLE_COUNT="$(psql "$SOURCE_URL" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" | tr -d '[:space:]')"
  ALEMBIC_COUNT="$(psql "$SOURCE_URL" -tAc "SELECT count(*) FROM alembic_version;" | tr -d '[:space:]')"
  echo "marker rows (post-restore): $POST_COUNT"
  echo "public tables (post-restore): $TABLE_COUNT"
  echo "alembic_version rows (post-restore): $ALEMBIC_COUNT"
  echo "duration_sec: $((END - START))"
  echo

  rm -f "$DUMP"
  if [ "${POST_COUNT:-0}" = "1" ] && [ "${TABLE_COUNT:-0}" -gt 0 ] && [ "${ALEMBIC_COUNT:-0}" -gt 0 ] && [ "${RECREATED_ENC}" = "UTF8" ]; then
    echo "RESULT: PASS (known row survived drop+recreate+restore)"
    exit 0
  else
    echo "RESULT: FAIL"
    exit 1
  fi
fi

TMP_DIR="$(mktemp -d)"
DUMP="$TMP_DIR/cadverify.dump"
cleanup() {
  psql "$ADMIN_URL" -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS \"$RESTORE_DB\" WITH (FORCE);" >/dev/null 2>&1 || true
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

START="$(date +%s)"
pg_dump --format=custom --no-owner --file "$DUMP" "$SOURCE_URL"
DUMP_BYTES="$(wc -c < "$DUMP" | tr -d ' ')"
DUMP_SHA="$(shasum -a 256 "$DUMP" | awk '{print $1}')"

psql "$ADMIN_URL" -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"$RESTORE_DB\" WITH (FORCE);" >/dev/null
psql "$ADMIN_URL" -v ON_ERROR_STOP=1 \
  -c "CREATE DATABASE \"$RESTORE_DB\";" >/dev/null
pg_restore --no-owner --dbname "$RESTORE_URL" "$DUMP"

TABLE_COUNT="$(psql "$RESTORE_URL" -tAc "select count(*) from information_schema.tables where table_schema = 'public';" | tr -d '[:space:]')"
ALEMBIC_COUNT="$(psql "$RESTORE_URL" -tAc "select count(*) from alembic_version;" | tr -d '[:space:]')"
END="$(date +%s)"

STATUS="PASS"
if [ "${TABLE_COUNT:-0}" -le 0 ] || [ "${ALEMBIC_COUNT:-0}" -le 0 ] || [ "${DUMP_BYTES:-0}" -le 0 ]; then
  STATUS="FAIL"
fi

cat > "$REPORT" <<JSON
{
  "status": "$STATUS",
  "generated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "run_id": "$RUN_ID",
  "source_database_host": "$(python3 - "$SOURCE_URL" <<'PY'
from urllib.parse import urlparse
import sys
print(urlparse(sys.argv[1]).hostname or "")
PY
)",
  "restore_database": "$RESTORE_DB",
  "dump_bytes": $DUMP_BYTES,
  "dump_sha256": "$DUMP_SHA",
  "public_table_count": ${TABLE_COUNT:-0},
  "alembic_version_rows": ${ALEMBIC_COUNT:-0},
  "duration_sec": $((END - START))
}
JSON

cat "$REPORT"
[ "$STATUS" = "PASS" ]
