"""CADVerify — Manufacturing Validation API."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.sessions import SessionMiddleware

import structlog

from src.api.history import router as history_router
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

# Rate limiting (slowapi). Must be wired before routers are included so the
# middleware sees every request. See src/auth/rate_limit.py for the key_func.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
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
app.include_router(history_router, prefix="/api/v1/analyses", tags=["history"])
app.include_router(share_router, prefix="/api/v1/analyses")
app.include_router(public_share_router, prefix="/s")
app.include_router(oauth_router, prefix="/auth")
app.include_router(magic_router, prefix="/auth")
app.include_router(keys_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "cadverify", "version": app.version}
