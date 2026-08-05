"""Public product URLs derived from deployment-owned configuration."""

from __future__ import annotations

import os


def dashboard_origin() -> str:
    """Return the configured product origin without inventing a public domain."""
    return os.getenv("DASHBOARD_ORIGIN", "http://localhost:3000").rstrip("/")


def api_origin() -> str:
    """Return the API origin used for external identity-provider callbacks."""
    return os.getenv("API_ORIGIN", "http://localhost:8000").rstrip("/")


def error_doc_url(code: str) -> str:
    """Link an API error to documentation on the deployment's own origin."""
    return f"{dashboard_origin()}/docs#{code}"
