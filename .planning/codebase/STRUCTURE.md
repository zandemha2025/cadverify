# Codebase Structure

**Analysis Date:** 2026-04-15

## Directory Layout

```
cadverify/
├── backend/                           # Python FastAPI server
│   ├── main.py                        # Entry point; FastAPI app setup, middleware, routes include
│   ├── requirements.txt                # Python dependencies (fastapi, uvicorn, trimesh, numpy, scipy)
│   ├── pyproject.toml                 # pytest config
│   ├── Dockerfile                     # Container image definition
│   ├── fly.toml                       # Fly.io deployment config
│   ├── src/
│   │   ├── __init__.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes.py              # HTTP endpoints: /validate, /processes, /materials, /machines, /rule-packs
│   │   ├── analysis/
│   │   │   ├── __init__.py
│   │   │   ├── models.py              # Data models: Severity, ProcessType, Issue, GeometryInfo, ProcessScore, AnalysisResult
│   │   │   ├── base_analyzer.py       # Universal checks: watertightness, normals, degenerate faces, disconnected bodies
│   │   │   ├── context.py             # GeometryContext builder; precomputes geometry state for all analyzers
│   │   │   ├── additive_analyzer.py   # Legacy: wall thickness, overhang, feature size checks for additive processes
│   │   │   ├── cnc_analyzer.py        # Legacy: CNC-specific checks (3/5-axis, turning, EDM)
│   │   │   ├── molding_analyzer.py    # Legacy: injection molding, die casting checks
│   │   │   ├── casting_analyzer.py    # Legacy: sand, investment, die casting checks
│   │   │   ├── sheet_metal_analyzer.py # Legacy: sheet metal bend, gap, thickness checks
│   │   │   ├── processes/             # Phase 2 registry-based analyzers (21 classes)
│   │   │   │   ├── __init__.py        # Imports all subpackages to trigger @register decorators
│   │   │   │   ├── base.py            # ProcessAnalyzer protocol, registry, get_analyzer(), register()
│   │   │   │   ├── checks.py          # Shared check utilities (feature size, wall thickness, overhang, draft, etc.)
│   │   │   │   ├── additive/          # FDM, SLA, DLP, SLS, MJF, DMLS, SLM, EBM, Binder Jetting, DED, WAAM classes
│   │   │   │   ├── subtractive/       # CNC 3/5-axis, Turning, Wire EDM classes
│   │   │   │   └── formative/         # Injection Molding, Die Casting, Investment Casting, Sand Casting, Sheet Metal, Forging classes
│   │   │   ├── features/              # Feature detection (holes, bosses, ribs, etc.)
│   │   │   │   ├── base.py            # Feature base class
│   │   │   │   ├── cylinders.py       # Cylinder/hole detection via Hough transform
│   │   │   │   ├── flats.py           # Flat surface detection
│   │   │   │   └── detector.py        # Top-level detector orchestrator
│   │   │   └── rules/                 # Industry-specific rule packs
│   │   │       ├── __init__.py        # RulePack, RuleOverride, register_pack(), available_rule_packs()
│   │   │       ├── aerospace.py       # Aerospace rule pack (tighter tolerances, HIP, traceability)
│   │   │       ├── automotive.py      # Automotive rule pack
│   │   │       ├── medical.py         # Medical rule pack (biocompatibility, fatigue)
│   │   │       └── oil_gas.py         # Oil & gas rule pack (NACE standards, corrosion resistance)
│   │   ├── parsers/                   # File format parsers
│   │   │   ├── __init__.py
│   │   │   ├── stl_parser.py          # STL → trimesh (binary & ASCII)
│   │   │   └── step_parser.py         # STEP/STP → trimesh (cadquery-optional)
│   │   ├── profiles/                  # Material & machine inventory
│   │   │   ├── __init__.py
│   │   │   ├── database.py            # 41 materials, 19 machines; process-material-machine mappings; query functions
│   │   │   ├── loader.py              # YAML loader for material/machine definitions
│   │   │   └── materials/             # YAML files per material category (polymers, metals, etc.)
│   │   ├── segmentation/              # Geometric segmentation
│   │   │   ├── __init__.py
│   │   │   ├── sam3d_segmenter.py     # SAM 3D integration entry point
│   │   │   ├── fallback.py            # Heuristic segmentation (coplanar facets, connected components)
│   │   │   └── sam3d/                 # SAM 3D ML pipeline (renderer, lifter, predictor)
│   │   ├── matcher/                   # Process scoring & recommendations
│   │   │   ├── __init__.py
│   │   │   └── profile_matcher.py     # score_process(), rank_processes(), geometry affinity scoring
│   │   └── fixes/                     # Fix suggestion enhancement
│   │       ├── __init__.py
│   │       └── fix_suggester.py       # Enhance issue fix suggestions; suggest priority fixes
│   └── tests/                         # pytest test suite
│       ├── __init__.py
│       ├── test_*.py files            # Tests organized by module
│       └── fixtures/                  # Test data (sample STL/STEP files, mock profiles)
│
└── frontend/                          # Next.js web client
    ├── package.json                   # Dependencies: next, react, three, tailwind
    ├── tsconfig.json                  # TypeScript config with @ alias to src/
    ├── src/
    │   ├── app/                       # Next.js app directory (v13+ route handlers)
    │   │   ├── layout.tsx             # Root layout; metadata, fonts
    │   │   ├── page.tsx               # Home page; state management for upload/analysis
    │   │   └── globals.css            # Global styles (Tailwind imports)
    │   ├── components/                # Reusable React components
    │   │   ├── FileDropZone.tsx       # File upload drop zone
    │   │   ├── ModelViewer.tsx        # 3D mesh viewer (Three.js + React Three Fiber, SSR-disabled)
    │   │   ├── AnalysisDashboard.tsx  # Main results view; layout for verdict, geometry, issues
    │   │   ├── IssueList.tsx          # Issue cards grouped by severity and process
    │   │   ├── ProcessScoreCard.tsx   # One card per process with score, verdict, recommendations
    │   │   ├── FeaturesList.tsx       # Detected features (holes, bosses, etc.) in table
    │   │   └── RulePackSelector.tsx   # Dropdown to select industry rule pack
    │   └── lib/
    │       └── api.ts                 # HTTP client; types (ValidationResult, Issue, ProcessScore, etc.); fetch wrappers
    └── public/                        # Static assets

```

## Directory Purposes

**backend/**
- Purpose: Python REST API server for CAD file analysis
- Runtime: Python 3.10+, FastAPI, uvicorn
- Key files: `main.py` (entry point), `src/api/routes.py` (request handlers)

**backend/src/api/**
- Purpose: HTTP request/response handling
- Key files: `routes.py` (all endpoints)

**backend/src/analysis/**
- Purpose: Core DFM analysis engine
- Contains: Base checks, legacy analyzers, Phase 2 registry, feature detection, rules
- Key files: `models.py` (data types), `base_analyzer.py` (universal checks), `context.py` (shared state)

**backend/src/analysis/processes/**
- Purpose: Modular process-specific analyzers (Phase 2)
- Pattern: Each process type has a class decorated with `@register`
- Key files: `base.py` (protocol & registry), `checks.py` (shared utilities)

**backend/src/analysis/features/**
- Purpose: Geometric feature detection
- Detects: Holes, bosses, ribs, fillets, thin walls, overhangs, etc.
- Optional in response but populated if requested

**backend/src/analysis/rules/**
- Purpose: Industry rule packs overlay validation rules
- Files: One per industry (aerospace, automotive, medical, oil_gas)
- Applied: Post-analysis if rule_pack query parameter provided

**backend/src/parsers/**
- Purpose: Convert file bytes to trimesh objects
- Supported: STL (binary & ASCII), STEP/STP (cadquery-optional)

**backend/src/profiles/**
- Purpose: Material and machine inventory
- Contains: 41 materials (PLA to Inconel 718), 19 machines (Bambu Lab to Haas)
- Pattern: YAML-based definitions; loaded once at startup

**backend/src/segmentation/**
- Purpose: SAM 3D ML model integration + fallback heuristic
- Status: Phase 3 feature (optional, under development)

**backend/src/matcher/**
- Purpose: Score processes against part geometry and issues
- Key: `score_process()` computes viability and recommends material/machine

**backend/src/fixes/**
- Purpose: Enhance fix suggestions with standards citations
- Produces: Priority fix list (most critical issues first)

**backend/tests/**
- Purpose: pytest test suite
- Structure: `test_*.py` per module; `fixtures/` for test data

**frontend/src/app/**
- Purpose: Next.js page routing (App Router)
- Key file: `page.tsx` (home page with upload & analysis states)

**frontend/src/components/**
- Purpose: Reusable React UI components
- Scope: File upload, 3D viewer, results dashboard, issue lists

**frontend/src/lib/**
- Purpose: Utilities and API client
- Key file: `api.ts` (HTTP client, TypeScript interfaces)

**frontend/public/**
- Purpose: Static files served as-is

## Key File Locations

**Entry Points:**

- `backend/main.py`: FastAPI application setup; runs on `uvicorn main:app`
- `frontend/src/app/page.tsx`: Next.js home page; starts analysis flow
- `frontend/src/app/layout.tsx`: Root layout wrapper

**Configuration:**

- `backend/requirements.txt`: Python dependencies
- `backend/pyproject.toml`: pytest configuration
- `frontend/package.json`: npm dependencies and scripts
- `frontend/tsconfig.json`: TypeScript compiler options with @ path alias
- `backend/.env.example`: Environment variable template (ALLOWED_ORIGINS, LOG_LEVEL, MAX_UPLOAD_MB)

**Core Logic:**

- `backend/src/api/routes.py`: HTTP request dispatch; file parsing, analysis orchestration
- `backend/src/analysis/base_analyzer.py`: Universal geometry checks
- `backend/src/analysis/context.py`: Precomputed geometry context
- `backend/src/analysis/models.py`: Data model definitions
- `backend/src/analysis/processes/base.py`: Process analyzer registry
- `backend/src/matcher/profile_matcher.py`: Process scoring logic
- `frontend/src/lib/api.ts`: HTTP client and type definitions

**Testing:**

- `backend/tests/`: pytest test modules
- No frontend tests configured (but component tests could be added)

## Naming Conventions

**Files:**

- **Python modules:** lowercase with underscores (`analysis_context.py`, `rule_pack.py`)
- **Python packages:** lowercase directories with `__init__.py`
- **React components:** PascalCase (`.tsx` suffix) — e.g., `AnalysisDashboard.tsx`
- **Utilities:** camelCase in TypeScript (`api.ts`, `validation.ts`)
- **Tests:** `test_<module>.py` in Python; `<component>.test.tsx` convention (not currently used in frontend)

**Directories:**

- **Feature grouping:** Functional areas grouped by concern (`analysis/`, `parsers/`, `profiles/`)
- **Subdomains within analysis:** `processes/`, `features/`, `rules/` as sub-packages
- **Pattern:** One concern per directory; avoid mixing responsibilities

**Classes & Types:**

- **Python classes:** PascalCase (e.g., `GeometryContext`, `ProcessAnalyzer`, `RulePack`)
- **Python enums:** PascalCase (`ProcessType`, `Severity`, `FeatureType`)
- **TypeScript interfaces:** PascalCase (e.g., `ValidationResult`, `Issue`, `ProcessScore`)
- **Data fields:** snake_case in Python, camelCase in TypeScript (JSON serialization)

## Where to Add New Code

**New Manufacturing Process (Phase 2):**
1. Create class in `backend/src/analysis/processes/<category>/<process>.py` (e.g., `additive/fdm.py`)
2. Implement `ProcessAnalyzer` protocol: set `process: ProcessType`, `standards: list[str]`, `analyze(ctx) → list[Issue]`
3. Decorate with `@register` to auto-register in dispatcher
4. Use utilities from `backend/src/analysis/processes/checks.py`
5. Add tests in `backend/tests/test_<process>.py`

**New Feature Detection:**
1. Create class in `backend/src/analysis/features/` extending `Feature` base
2. Implement `detect() → list[Feature]` method
3. Add to `detect_all()` function in `backend/src/analysis/features/detector.py`
4. Tests in `backend/tests/test_features.py`

**New Industry Rule Pack:**
1. Create `backend/src/analysis/rules/<industry>.py`
2. Define `RulePack` instance with name, version, overrides
3. Decorate with `@register_pack` to auto-register
4. Override severity for critical issues, tighten thresholds, add mandatory issues
5. Import in `backend/src/analysis/rules/__init__.py` to trigger registration

**New Material or Machine:**
1. Add YAML definition in `backend/src/profiles/materials/<category>/<name>.yaml`
2. Load triggered automatically by `database.py` on startup
3. Link to processes via material properties

**Frontend UI Component:**
1. Create `.tsx` file in `frontend/src/components/`
2. Use types from `frontend/src/lib/api.ts` for props
3. Style with Tailwind CSS classes
4. Import and integrate in `page.tsx` or other parent components

**API Endpoint:**
1. Add route handler in `backend/src/api/routes.py` to `router` instance
2. Use Pydantic models for request/response types
3. Call analysis functions from appropriate modules
4. Return JSONable response (dataclass auto-serialized by FastAPI)
5. Document with FastAPI docstring and `Query()`/`File()` parameter descriptions

**Utility/Helper:**
1. **Python:** Add function to appropriate module in `backend/src/` or new module if needed
2. **TypeScript:** Add to `frontend/src/lib/api.ts` or create new util file in `frontend/src/lib/`
3. Keep functions pure and testable; avoid side effects

## Special Directories

**backend/tests/**
- Purpose: pytest test suite
- Generated: No (hand-written tests)
- Committed: Yes
- Convention: Test file per module; fixtures as subdirectory or conftest.py

**frontend/public/**
- Purpose: Static assets (images, icons, robots.txt, etc.)
- Generated: No
- Committed: Yes

**backend/.env & .env.example**
- Purpose: Environment configuration
- Generated: `.env` is not committed (secrets); `.env.example` is committed as template
- Never read or include secrets from `.env` in version control

**backend/src/profiles/materials/**
- Purpose: YAML definitions of material properties
- Generated: No
- Committed: Yes
- Pattern: One YAML file per material or category subdirectory

**Ignored directories (not in structure):**
- `backend/node_modules/` — npm packages (should not exist in backend)
- `frontend/node_modules/` — npm packages (not committed)
- `frontend/.next/` — Next.js build output (not committed)
- `backend/__pycache__/`, `*.pyc` — Python cache (not committed)

---

*Structure analysis: 2026-04-15*
