"""CADVerify — Manufacturing Validation API."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from src.api.routes import router


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

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "cadverify", "version": app.version}
