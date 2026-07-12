# syntax=docker/dockerfile:1.7
# =============================================================================
# Stage 1 — builder: install build tools + compile C extensions into a venv
# =============================================================================
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS builder

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
ENV PYTHONDONTWRITEBYTECODE=1

COPY requirements-prod.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements-prod.lock

# Download SAM-2 Hiera Small checkpoint (~150 MB)
# License: Apache-2.0 (Meta AI)
RUN mkdir -p /build/models
ADD --checksum=sha256:6d1aa6f30de5c92224f8172114de081d104bbd23dd9dc5c58996f0cad5dc4d38 \
    https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt \
    /build/models/sam2_hiera_small.pt

# =============================================================================
# Stage 2 — runtime: slim image with only runtime deps + venv + app code
# =============================================================================
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

WORKDIR /app

# Runtime-only system deps (no build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglu1-mesa \
    libxcursor1 \
    libxfixes3 \
    libxft2 \
    libxinerama1 \
    libgomp1 \
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

# STEP ingestion (B4): the gmsh manylinux wheel (libgmsh.so, embedded
# OpenCASCADE kernel = the LIVE .step/.stp path in src/parsers/step_mesher.py)
# is dlopened at `import gmsh`. It links the FLTK GUI X-stack + OpenMP even
# though we only ever mesh headless (occ.importShapes + mesh.generate(2) are
# CPU-only, no X server / GLX context needed). The python:3.12-slim base ships
# none of these, so import died and is_step_supported() -> False -> the upload
# route 501'd on every STEP. `ldd libgmsh.so` inside the built image (CI run
# 28726614420) enumerated the full set of missing runtime .so's:
#   libGLU.so.1     -> libglu1-mesa
#   libXcursor.so.1 -> libxcursor1
#   libXfixes.so.3  -> libxfixes3
#   libXft.so.2     -> libxft2
#   libXinerama.so.1-> libxinerama1
#   libgomp.so.1    -> libgomp1  (GCC OpenMP; present in builder via
#                                 build-essential, absent from slim runtime)
# The named packages transitively pull libX11/libXrender/libXext/libfontconfig
# etc. Evidence chain: run 28726509921 (fail: libGLU) -> run 28726614420
# (fail: the 4 X libs + libgomp, all surfaced at once via ldd) -> this commit.

# Create non-root user (T-06A-01 mitigation)
RUN useradd --create-home --shell /bin/bash cadverify

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1

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
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header"]
