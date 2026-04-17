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
from src.api.pdf import router as pdf_router
from src.api.batch_router import router as batch_router
from src.api.jobs_router import router as jobs_router
from src.api.reconstruct_router import router as reconstruct_router
from src.api.routes import router
from src.api.share import public_share_router, share_router
from src.auth.keys_api import router as keys_router
from src.auth.magic_link import router as magic_router
from src.auth.oauth import router as oauth_router
from src.auth.rate_limit import limiter, rate_limit_handler
from src.auth.scrubbing import scrub_processor, sentry_before_send


def _parse_origins(raw: str) -> list[str]:
    return [o.strip() for o in raw.split(",") if o.strip()]


# Default CORS regex: prod apex/www + Vercel preview subdomains.
# Override via CORS_ORIGIN_REGEX env for dev/localhost if needed.
CORS_ORIGIN_REGEX = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"^https://(cadverify\.com|www\.cadverify\.com|[a-z0-9-]+\.vercel\.app)$",
)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

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

app.include_router(router, prefix="/api/v1")
app.include_router(batch_router)
app.include_router(reconstruct_router)
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(history_router, prefix="/api/v1/analyses", tags=["history"])
app.include_router(share_router, prefix="/api/v1/analyses")
app.include_router(pdf_router, prefix="/api/v1/analyses")
app.include_router(public_share_router, prefix="/s")
app.include_router(oauth_router, prefix="/auth")
app.include_router(magic_router, prefix="/auth")
app.include_router(keys_router)
app.include_router(health_router)


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
