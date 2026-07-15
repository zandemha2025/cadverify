"""Contracts for a writable, production-shaped local launcher."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_local_launcher_overrides_container_only_blob_path() -> None:
    launcher = (ROOT / "scripts/run-local-app.sh").read_text(encoding="utf-8")

    assert (
        'export OBJECT_STORE_LOCAL_ROOT="${OBJECT_STORE_LOCAL_ROOT:-$REPO_ROOT/data/local-blobs}"'
        in launcher
    )
    assert 'mkdir -p "$OBJECT_STORE_LOCAL_ROOT"' in launcher
    assert '[ -w "$OBJECT_STORE_LOCAL_ROOT" ]' in launcher
    assert (
        'export PDF_CACHE_DIR="${PDF_CACHE_DIR:-$REPO_ROOT/data/pdf-cache}"'
        in launcher
    )
    assert 'mkdir -p "$PDF_CACHE_DIR"' in launcher
    assert '[ -w "$PDF_CACHE_DIR" ]' in launcher


def test_local_launcher_gives_services_durable_log_sinks() -> None:
    launcher = (ROOT / "scripts/run-local-app.sh").read_text(encoding="utf-8")

    assert 'LOCAL_LOG_DIR="${LOCAL_LOG_DIR:-$REPO_ROOT/data/local-logs}"' in launcher
    assert 'mkdir -p "$LOCAL_LOG_DIR"' in launcher
    assert '>>"$BACKEND_LOG" 2>&1' in launcher
    assert '>>"$WORKER_LOG" 2>&1' in launcher
    assert '>>"$FRONTEND_LOG" 2>&1' in launcher
