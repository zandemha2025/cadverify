# External Integrations

**Analysis Date:** 2026-04-15

## APIs & External Services

**CAD File Processing:**
- Mesh geometry analysis: Built-in via trimesh library
- STEP file parsing: Optional cadquery SDK (not bundled, install separately for Phase 2 support)
- STL file parsing: Native via trimesh

**3D Model Visualization:**
- Three.js ecosystem: Client-side 3D rendering (no external API)
- STL model loading: STLLoader from Three.js examples

## Data Storage

**Databases:**
- None - Stateless API, no persistent database layer

**File Storage:**
- Local filesystem only (temporary upload handling)
- Files stored in memory or temporary buffers during request lifecycle
- Maximum file size: Configurable via `MAX_UPLOAD_MB` environment variable (default: 100MB)

**Configuration/Profiles:**
- In-memory data structures for materials and machines
- Location: `src/profiles/database.py` - Contains hardcoded MATERIALS and MACHINES definitions
- Rule packs: YAML-based, loaded at runtime from `src/analysis/rules/` directory

**Caching:**
- None - Each request independently analyzes the uploaded file

## Authentication & Identity

**Auth Provider:**
- None - API is stateless, no user authentication required
- CORS handling for cross-origin requests from frontend
- No session management or API keys

## Monitoring & Observability

**Error Tracking:**
- None detected - Standard Python logging only

**Logs:**
- Python standard logging module
- Configuration: `main.py` (lines 23-27) sets up basicConfig with format: `%(asctime)s %(levelname)s %(name)s %(message)s`
- Log level: Configurable via `LOG_LEVEL` environment variable (default: INFO)
- Logger name: "cadverify" for application logs, module-specific loggers for subsystems
- Example: `logger.exception()` used in `src/api/routes.py` for error handling

## CI/CD & Deployment

**Hosting:**
- Docker containers (deployable to any container orchestration platform)
- Frontend: Standalone Next.js server on port 3000
- Backend: Uvicorn ASGI server on port 8000 (configurable via PORT env var)

**CI Pipeline:**
- None detected in codebase

**Build Automation:**
- npm scripts (frontend): `dev`, `build`, `start`, `lint`
- Python execution via shell script in Dockerfile: `uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2`

## Environment Configuration

**Required Environment Variables:**

*Frontend (`frontend/.env.example`):**
- `NEXT_PUBLIC_API_URL` - Backend API base URL (default: http://localhost:8000/api/v1)

*Backend (`backend/.env.example`):`*
- `ALLOWED_ORIGINS` - Comma-separated list of allowed CORS origins (default: http://localhost:3000)
- `MAX_UPLOAD_MB` - Maximum upload file size in megabytes (default: 100)
- `LOG_LEVEL` - Logging level: DEBUG, INFO, WARNING, ERROR (default: INFO)
- `SAM3D_ENABLED` - Boolean for SAM-3D segmentation GPU worker (default: false, disabled in Phase 1)

**Secrets/Credentials:**
- None required (stateless API, no external service credentials)

**Configuration Files:**
- `.env.example` files present in both frontend and backend - copy to `.env` for local configuration
- `.env` files should NOT be committed to version control

## File Upload Handling

**Supported Formats:**
- `.stl` - Stereolithography format (fully supported via trimesh)
- `.step`, `.stp` - STEP CAD format (requires cadquery, disabled in Phase 1)

**Upload Flow:**
1. Browser uploads file via multipart/form-data to `/api/v1/validate` endpoint (`src/api/routes.py`)
2. Backend streams and validates file size (rejects >MAX_UPLOAD_MB)
3. Parser determines format by file extension
4. Mesh parsed into trimesh.Trimesh object
5. Analysis performed, results serialized to JSON

**Request Validation:**
- Empty file check (line 80, `src/api/routes.py`)
- File size check with capped streaming (lines 56-81, `src/api/routes.py`)
- File type validation by extension (lines 84-107, `src/api/routes.py`)

## API Endpoints

**Validation:**
- `POST /api/v1/validate` - Full analysis with process-specific checks, optional rule pack
- `POST /api/v1/validate/quick` - Quick pass/fail check (universal checks only)
- `GET /api/v1/rule-packs` - List available industry rule packs
- `GET /api/v1/processes` - List supported manufacturing processes
- `GET /api/v1/materials` - List supported materials with properties
- `GET /api/v1/machines` - List supported machines with capabilities
- `GET /health` - Health check endpoint

## Webhooks & Callbacks

**Incoming:**
- None detected

**Outgoing:**
- None detected

## External Service Dependencies

**None** - The application is self-contained. All analysis is performed locally:
- Geometry processing via trimesh (local)
- Feature detection via custom analyzers (local)
- Manufacturing process matching via custom scorers (local)
- 3D visualization via Three.js (browser-based, no external APIs)

**Optional Components (Phase 2):**
- cadquery - For STEP file parsing (currently disabled)
- GPU worker - For SAM-3D segmentation (currently disabled)

---

*Integration audit: 2026-04-15*
