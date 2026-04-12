"""CADVerify — Manufacturing Validation API."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from src.analysis.models import AnalysisResult, ProcessType
from src.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown logic."""
    yield


app = FastAPI(
    title="CADVerify",
    description="Manufacturing validation for STEP and STL files",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "cadverify"}
