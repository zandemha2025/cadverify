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

from src.api.routes import router
from src.auth.keys_api import router as keys_router
from src.auth.magic_link import router as magic_router
from src.auth.oauth import router as oauth_router
from src.auth.rate_limit import limiter, rate_limit_handler


def _parse_origins(raw: str) -> list[str]:
    return [o.strip() for o in raw.split(",") if o.strip()]


ALLOWED_ORIGINS = _parse_origins(os.getenv("ALLOWED_ORIGINS", "http://localhost:3000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("cadverify")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("CADVerify starting | origins=%s", ALLOWED_ORIGINS)
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

# CORS: credentials disabled because wildcard + credentials is rejected by browsers,
# and this API is currently stateless (no cookie auth). Tighten ALLOWED_ORIGINS for prod.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
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
app.include_router(oauth_router, prefix="/auth")
app.include_router(magic_router, prefix="/auth")
app.include_router(keys_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "cadverify", "version": app.version}
