"""Interactive API docs and the OpenAPI schema: on in development, opt-in in a release.

In a release (RELEASE set to a non-dev value) FastAPI's /docs, /redoc and
/openapi.json and the /scalar console are served only with API_DOCS_ENABLED=1.
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from src.config.production import is_production

logger = logging.getLogger("cadverify.api_docs")

_TRUTHY = {"1", "true", "yes", "on"}


def api_docs_enabled() -> bool:
    if not is_production():
        return True
    return os.getenv("API_DOCS_ENABLED", "0").strip().lower() in _TRUTHY


def fastapi_docs_kwargs() -> dict:
    """FastAPI constructor arguments for the docs routes (None turns one off)."""
    if api_docs_enabled():
        return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


def mount_scalar(app: FastAPI) -> bool:
    """Serve the Scalar console at /scalar when docs are on and it is installed."""
    if not api_docs_enabled() or not app.openapi_url:
        return False
    try:
        from fastapi.responses import HTMLResponse
        from scalar_fastapi import get_scalar_api_reference
    except ImportError:
        return False  # scalar-fastapi not installed; /scalar is not available

    @app.get("/scalar", include_in_schema=False)
    async def scalar_docs():
        return HTMLResponse(get_scalar_api_reference(openapi_url=app.openapi_url, title=app.title))

    return True


def log_docs_state() -> None:
    logger.info("API docs (/docs, /redoc, /openapi.json, /scalar) %s",
                "served" if api_docs_enabled() else "off in this release (API_DOCS_ENABLED=1 turns them on)")
