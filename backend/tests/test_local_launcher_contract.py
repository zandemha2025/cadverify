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
