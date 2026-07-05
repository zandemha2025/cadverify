# =============================================================================
# Stage 1 — builder: install build tools + compile C extensions into a venv
# =============================================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps for building C extensions (pymeshfix, scipy) + WeasyPrint build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    xmlsec1 \
    libxmlsec1-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download SAM-2 Hiera Small checkpoint (~150 MB)
# License: Apache-2.0 (Meta AI)
RUN mkdir -p /build/models
ADD https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt /build/models/sam2_hiera_small.pt

# =============================================================================
# Stage 2 — runtime: slim image with only runtime deps + venv + app code
# =============================================================================
FROM python:3.12-slim

WORKDIR /app

# Runtime-only system deps (no build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglu1-mesa \
    libglib2.0-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    xmlsec1 \
    libxmlsec1 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# STEP ingestion (B4): the gmsh manylinux wheel (embedded OpenCASCADE kernel,
# src/parsers/step_mesher.py — the LIVE .step/.stp path) dlopens libGLU at
# import time; the base slim image ships libGL (libgl1) but NOT libGLU, so
# `import gmsh` died with `OSError: libGLU.so.1: cannot open shared object
# file` and is_step_supported() degraded the upload route to 501. libglu1-mesa
# above provides libGLU.so.1. Proven by CI: run 28726509921 (fail, libGLU
# missing) -> this branch (pass). Headless meshing needs no X server / GLX
# context — occ.importShapes + mesh.generate(2) are CPU-only.

# Create non-root user (T-06A-01 mitigation)
RUN useradd --create-home --shell /bin/bash cadverify

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy pre-baked SAM-2 model weights from builder
COPY --from=builder /build/models /app/models

# SAM-3D environment defaults
ENV SAM3D_MODEL_PATH=/app/models/sam2_hiera_small.pt
ENV SAM3D_CACHE_DIR=/data/blobs/sam3d_cache
ENV MESH_BLOB_DIR=/data/blobs/meshes

# Copy app code
COPY . .

# Copy compliance files (from repo root, placed in build context)
COPY NOTICE THIRD_PARTY_LICENSES.md /app/

# Switch to non-root user
USER cadverify

EXPOSE 8000

# Web entrypoint (default). Worker overrides CMD to: arq src.jobs.worker.WorkerSettings
# --no-server-header suppresses uvicorn's `server: uvicorn` banner (S6); the app
# middleware then stamps a neutral Server value.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-server-header"]
