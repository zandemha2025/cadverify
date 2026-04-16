# =============================================================================
# Stage 1 — builder: install build tools + compile C extensions into a venv
# =============================================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps for building C extensions (pymeshfix, scipy) + WeasyPrint build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# =============================================================================
# Stage 2 — runtime: slim image with only runtime deps + venv + app code
# =============================================================================
FROM python:3.12-slim

WORKDIR /app

# Runtime-only system deps (no build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user (T-06A-01 mitigation)
RUN useradd --create-home --shell /bin/bash cadverify

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy app code
COPY . .

# Copy compliance files (from repo root, placed in build context)
COPY NOTICE THIRD_PARTY_LICENSES.md /app/

# Switch to non-root user
USER cadverify

EXPOSE 8000

# Web entrypoint (default). Worker overrides CMD to: arq src.jobs.worker.WorkerSettings
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
