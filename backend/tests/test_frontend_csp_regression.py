from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_verify_blob_mesh_is_allowed_by_content_security_policy():
    # Regression: ISSUE-003 — STEP processing completed, but the browser could
    # not fetch its generated blob URL and replaced the result with an error page.
    # Found by /qa on 2026-07-11.
    # Report: GitHub Actions run 29167984609, browser E2E artifact.
    proxy = (ROOT / "frontend/src/proxy.ts").read_text(encoding="utf-8")

    assert "connect-src 'self' blob:" in proxy
