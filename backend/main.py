"""CADVerify — Manufacturing Validation API."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.gzip import GZipMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.sessions import SessionMiddleware

import structlog

from src.api.errors import structured_http_error_handler, structured_validation_error_handler
from src.api.health import router as health_router
from src.api.history import router as history_router
from src.api.middleware import RequestIDMiddleware
from src.api.security_headers import SecurityHeadersMiddleware
from src.api.pdf import router as pdf_router
from src.api.batch_router import router as batch_router
from src.api.jobs_router import router as jobs_router
from src.api.reconstruct_router import router as reconstruct_router
from src.api.admin_routes import router as admin_router
from src.api.routes import router
from src.api.cost_decisions import public_cost_share_router, router as cost_decisions_router
from src.api.catalog import router as catalog_router
from src.api.rate_library import router as rate_library_router
from src.api.shop_library import router as shop_library_router
from src.api.governance import router as governance_router
from src.api.part_context import router as part_context_router
from src.api.groundtruth import router as groundtruth_router
from src.api.share import public_share_router, share_router
from src.auth.keys_api import router as keys_router
from src.auth.magic_link import router as magic_router
from src.auth.oauth import router as oauth_router
from src.auth.password import router as password_router
from src.auth.saml import router as saml_router
from src.auth.rate_limit import limiter, rate_limit_handler
from src.auth.scrubbing import scrub_processor, sentry_before_send


def _parse_origins(raw: str) -> list[str]:
    return [o.strip() for o in raw.split(",") if o.strip()]


# Default CORS regex: prod apex/www + Vercel preview subdomains.
# Override via CORS_ORIGIN_REGEX env for dev/localhost if needed.
# When the local labeling tool is enabled (LABELING_ENABLED=1) the regex also
# allows localhost/127.0.0.1 origins so the /label viewer can stream STLs from
# the local backend (CAD stays on localhost). An explicit CORS_ORIGIN_REGEX env
# always wins.
LABELING_ENABLED = os.getenv("LABELING_ENABLED") == "1"
_DEFAULT_CORS_REGEX = r"^https://(cadverify\.com|www\.cadverify\.com|[a-z0-9-]+\.vercel\.app)$"
if LABELING_ENABLED:
    _DEFAULT_CORS_REGEX = (
        r"^(https://(cadverify\.com|www\.cadverify\.com|[a-z0-9-]+\.vercel\.app)"
        r"|https?://(localhost|127\.0\.0\.1)(:\d+)?)$"
    )
CORS_ORIGIN_REGEX = os.getenv("CORS_ORIGIN_REGEX", _DEFAULT_CORS_REGEX)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def _is_production() -> bool:
    """True when RELEASE names a real deployment (not a dev/test/local build)."""
    return os.getenv("RELEASE", "dev").strip().lower() not in {
        "",
        "dev",
        "development",
        "local",
        "test",
        "ci",
    }


def _assert_production_secrets() -> None:
    """Fail closed in production if auth secrets are still at dev defaults (S5).

    Mirrors the DASHBOARD_SESSION_SECRET fail-closed pattern (refuse to run
    without a real secret), but as a startup guard so a misconfigured deploy
    crashes loudly instead of silently signing sessions with a well-known key.
    Off-switch: SECRET_ENFORCEMENT_ENABLED=0 (default on).
    """
    if os.getenv("SECRET_ENFORCEMENT_ENABLED", "1") == "0" or not _is_production():
        return
    session_secret = os.getenv("SESSION_SECRET", "").strip()
    if not session_secret or session_secret == "dev-only":
        raise RuntimeError(
            "SESSION_SECRET is unset or 'dev-only' in a production build "
            f"(RELEASE={os.getenv('RELEASE')!r}); refusing to start."
        )
    auth_mode = os.getenv("AUTH_MODE", "google")
    if auth_mode in ("google", "hybrid"):
        for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
            if os.getenv(var, "dummy").strip() in ("", "dummy"):
                raise RuntimeError(
                    f"{var} is unset or the 'dummy' default in a production "
                    f"build with AUTH_MODE={auth_mode}; refusing to start."
                )


_assert_production_secrets()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("cadverify")

# structlog configured with scrub_processor as the penultimate step (before
# JSONRenderer) so cv_live_* + Authorization headers never reach stdout/Sentry.
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        scrub_processor,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, LOG_LEVEL, logging.INFO)
    ),
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

if os.getenv("SENTRY_DSN"):
    import sentry_sdk

    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        before_send=sentry_before_send,
        send_default_pii=False,
        release=os.getenv("RELEASE", "dev"),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CADVerify starting | cors_regex=%s", CORS_ORIGIN_REGEX)
    yield
    logger.info("CADVerify stopping")


app = FastAPI(
    title="CADVerify",
    description="Manufacturing validation for STEP and STL files",
    version="0.2.0",
    lifespan=lifespan,
)

# Request-ID middleware — outermost so every request gets a correlation ID
# before CORS, rate-limiting, or any router sees it.
app.add_middleware(RequestIDMiddleware)

# Rate limiting (slowapi). Must be wired before routers are included so the
# middleware sees every request. See src/auth/rate_limit.py for the key_func.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_exception_handler(HTTPException, structured_http_error_handler)
app.add_exception_handler(StarletteHTTPException, structured_http_error_handler)
app.add_exception_handler(RequestValidationError, structured_validation_error_handler)
app.add_middleware(SlowAPIMiddleware)

# CORS: regex origin matches prod apex/www + Vercel preview subdomains.
# Explicit allow_headers (no wildcard); allow_credentials=False (stateless API,
# dashboard session lives on a different subdomain).
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    allow_credentials=False,
    max_age=600,
)
app.add_middleware(GZipMiddleware, minimum_size=1024)

# authlib OAuth state/nonce persistence requires Starlette SessionMiddleware.
# Scoped to /auth endpoints only via per-cookie SameSite=lax + backend origin.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev-only"),
)

# Security response headers (S6) — added LAST so it is the outermost user
# middleware and stamps every response (incl. CORS preflights, rate-limit 429s,
# and error responses) on the way out. Off-switch: SECURITY_HEADERS_ENABLED=0.
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(router, prefix="/api/v1")
app.include_router(batch_router)
app.include_router(reconstruct_router)
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(history_router, prefix="/api/v1/analyses", tags=["history"])
app.include_router(share_router, prefix="/api/v1/analyses")
app.include_router(pdf_router, prefix="/api/v1/analyses")
app.include_router(public_share_router, prefix="/s")
# Cost-decision persistence surface (Phase 2 gap #3): list/detail/export/share/compare
app.include_router(cost_decisions_router, prefix="/api/v1/cost-decisions")
app.include_router(public_cost_share_router, prefix="/s")
# Catalog read surface (W1 step 4): the org-scoped parts×decisions grid.
app.include_router(catalog_router, prefix="/api/v1/catalog", tags=["catalog"])
# Governed rate-library (W4 slice 1): versioned, effective-dated rate-card asset.
app.include_router(
    rate_library_router, prefix="/api/v1/rate-library", tags=["rate-library"]
)
# Governed shop-library (W4 slice 2): versioned, effective-dated, per-slug
# shop-profile asset (DB successor to data/shop_profiles/*.json).
app.include_router(
    shop_library_router, prefix="/api/v1/shop-library", tags=["shop-library"]
)
# Governance (W4 governance zone): change-request -> review -> publish flow over
# the governed rate-card / shop-profile libraries (approval publishes the draft).
app.include_router(
    governance_router, prefix="/api/v1/governance", tags=["governance"]
)
# Declared part-context (W3.5 rung-1): user-declared program/assembly/volume so
# the portfolio roll-up can state an honest $/year.
app.include_router(
    part_context_router, prefix="/api/v1/part-context", tags=["part-context"]
)
app.include_router(
    groundtruth_router, prefix="/api/v1/ground-truth", tags=["ground-truth"]
)
# Email + password auth (signup/login/logout/me). Mounted UNCONDITIONALLY — it
# is the primary login method that works end-to-end locally with zero external
# infra, independent of AUTH_MODE.
app.include_router(password_router, prefix="/auth")

# AUTH_MODE gating: saml | google | hybrid (default: google)
AUTH_MODE = os.getenv("AUTH_MODE", "google")

if AUTH_MODE in ("google", "hybrid"):
    app.include_router(oauth_router, prefix="/auth")
    app.include_router(magic_router, prefix="/auth")

if AUTH_MODE in ("saml", "hybrid"):
    app.include_router(saml_router, prefix="/auth")
app.include_router(admin_router)
app.include_router(keys_router)
app.include_router(health_router)

# Cycle 4 local labeling tool (dev-gated, prod-safe). Mounted ONLY under
# LABELING_ENABLED=1 so the corpus/label surface never ships to production and
# no CAD egresses. Routes are localhost-only (no API key/role — see corpus_router).
if LABELING_ENABLED:
    from src.api.corpus_router import router as corpus_router

    app.include_router(corpus_router)
    logger.info("Labeling tool ENABLED — corpus routes mounted at /api/v1/corpus")


# Scalar API docs — serves interactive documentation alongside /docs and /redoc
try:
    from scalar_fastapi import get_scalar_api_reference
    from fastapi.responses import HTMLResponse

    @app.get("/scalar", include_in_schema=False)
    async def scalar_docs():
        return HTMLResponse(
            get_scalar_api_reference(
                openapi_url=app.openapi_url,
                title=app.title,
            )
        )
except ImportError:
    pass  # scalar-fastapi not installed; /scalar endpoint not available
