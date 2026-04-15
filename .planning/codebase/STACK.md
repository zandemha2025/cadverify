# Technology Stack

**Analysis Date:** 2026-04-15

## Languages

**Primary:**
- TypeScript 5 - Frontend application, React components, API client types
- Python 3.12 - Backend API, geometry analysis, CAD processing

**Secondary:**
- JavaScript (ES2017 target) - Build outputs, Node.js server runtime

## Runtime

**Environment:**
- Node.js 20 (Alpine) - Frontend application server
- Python 3.12 (slim image) - Backend ASGI server

**Package Manager:**
- npm - Frontend package management
- pip - Backend package management

## Frameworks

**Core:**
- Next.js 16.2.3 - React-based frontend framework with server-side rendering
- FastAPI 0.115.0+ - Python ASGI web framework for backend API
- Uvicorn 0.30.0+ - ASGI server for FastAPI application

**UI/Rendering:**
- React 19.2.4 - Frontend component library
- React DOM 19.2.4 - DOM rendering for React components
- Three.js 0.183.2 - 3D graphics library for model visualization
- @react-three/fiber 9.5.0 - React renderer for Three.js
- @react-three/drei 10.7.7 - Utilities and helpers for Three.js scenes

**Styling:**
- Tailwind CSS 4 - Utility-first CSS framework
- @tailwindcss/postcss 4 - PostCSS integration for Tailwind

**Testing:**
- pytest - Python test framework configured in `backend/pyproject.toml`

## Key Dependencies

**Critical:**
- trimesh 4.4.0+ - Mesh geometry processing, STL/STEP parsing, topology analysis
- numpy 1.26.0+ - Numerical computing, array operations for geometric calculations
- scipy 1.13.0+ - Scientific computing, optimization algorithms
- shapely 2.0.0+ - Geometric operations, spatial analysis
- pydantic 2.7.0+ - Data validation and serialization in API models
- PyYAML 6.0+ - Configuration and rule pack parsing

**Infrastructure:**
- python-multipart 0.0.9+ - Multipart form data handling for file uploads
- STLLoader (Three.js) - Client-side STL file loading and visualization

## Build Tools

**Frontend:**
- TypeScript compiler - Type checking and transpilation
- ESLint 9 - JavaScript/TypeScript linting (eslint-config-next)
- Next.js build system - Bundling, optimization, static generation
- PostCSS - CSS processing with Tailwind CSS

**Backend:**
- Python setuptools - Package management (via pip)

## Configuration Files

**Frontend:**
- `frontend/tsconfig.json` - TypeScript compiler configuration (ES2017 target, strict mode)
- `frontend/next.config.ts` - Next.js configuration with standalone output mode
- `frontend/.env.example` - Environment variable template with `NEXT_PUBLIC_API_URL`

**Backend:**
- `backend/pyproject.toml` - Python project metadata and pytest configuration
- `backend/.env.example` - Environment variables: `ALLOWED_ORIGINS`, `MAX_UPLOAD_MB`, `LOG_LEVEL`, `SAM3D_ENABLED`

## Containerization

**Frontend Docker:**
- Base: `node:20-alpine` (multi-stage build)
- Builder: Installs dependencies and runs Next.js build
- Runner: Serves built application with `node server.js` on port 3000
- Output mode: Standalone (self-contained runtime)

**Backend Docker:**
- Base: `python:3.12-slim`
- Dependencies: Build essentials for geometry libraries (libgl1-mesa-glx, libglib2.0-0)
- Server: Uvicorn with 2 workers on port 8000
- Command: Dynamic port configuration via `${PORT:-8000}`

## Platform Requirements

**Development:**
- Node.js 20.x
- Python 3.12.x
- npm or compatible package manager
- STEP file parsing requires optional `cadquery` package (not in base requirements)

**Production:**
- Docker runtime (both frontend and backend containerized)
- For STEP support: cadquery package required in backend (disabled by default in Phase 1)
- GPU worker for SAM-3D segmentation (feature disabled in Phase 1)

## API Communication

**Client-Server:**
- HTTP/REST via `fetch` API
- Base URL: `NEXT_PUBLIC_API_URL` (environment variable, defaults to `http://localhost:8000/api/v1`)
- Content-Type: multipart/form-data for file uploads

**CORS Configuration:**
- Enforced at `main.py` with `CORSMiddleware`
- Credentials disabled (stateless API)
- Configurable origins via `ALLOWED_ORIGINS` env var

---

*Stack analysis: 2026-04-15*
