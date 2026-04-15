# Architecture

**Analysis Date:** 2026-04-15

## Pattern Overview

**Overall:** Layered Pipeline Architecture with Plug-in Process Analyzer Registry

**Key Characteristics:**
- Single-request file upload → mesh parsing → universal checks → parallel process analysis → scoring & ranking
- Process analyzers are discoverable via runtime registry (`@register` decorator pattern in Phase 2, legacy function-based adapter in Phase 1)
- Shared `GeometryContext` precomputes expensive geometry operations once and reuses across all process analyzers
- Industry-specific rule packs overlay validation thresholds and escalate severity post-analysis
- Frontend consumes JSON API, renders 3D mesh with Three.js, displays analysis dashboard with interactive results

## Layers

**API / Orchestration:**
- Purpose: HTTP request routing, file upload handling, process dispatcher
- Location: `backend/src/api/routes.py`
- Contains: FastAPI router, upload chunking, mesh parsing dispatch, process orchestration
- Depends on: All analysis modules, parsers, rule packs, profile matcher
- Used by: Frontend client via `/api/v1/validate` and `/api/v1/validate/quick`

**Geometry Analysis Base:**
- Purpose: Universal checks and geometry extraction applicable to all processes
- Location: `backend/src/analysis/base_analyzer.py`, `backend/src/analysis/context.py`
- Contains: Watertight checks, normal consistency, degenerate face detection, self-intersection detection, disconnected body detection, `GeometryContext` builder
- Depends on: trimesh, numpy, scipy
- Used by: All process-specific analyzers via shared context

**Process-Specific Analyzers (Registry):**
- Purpose: DFM (Design for Manufacturing) checks per manufacturing category
- Location: `backend/src/analysis/processes/` (21 analyzer classes grouped by type)
  - Additive: `backend/src/analysis/processes/additive/` (FDM, SLA, DLP, SLS, MJF, DMLS, SLM, EBM, Binder Jetting, DED, WAAM)
  - Subtractive: `backend/src/analysis/processes/subtractive/` (CNC 3/5-axis, Turning, Wire EDM)
  - Formative: `backend/src/analysis/processes/formative/` (Injection Molding, Die Casting, Investment Casting, Sand Casting, Sheet Metal, Forging)
- Contains: ProcessAnalyzer protocol-compliant classes with `analyze(context) → list[Issue]` methods
- Depends on: `GeometryContext`, analysis models, geometry utilities
- Used by: Routes dispatcher via `get_analyzer(ProcessType)` registry lookup

**Legacy Analyzer Adapter (Phase 1):**
- Purpose: Backward compatibility for processes not yet ported to Phase 2 registry
- Location: `backend/src/analysis/additive_analyzer.py`, `backend/src/analysis/cnc_analyzer.py`, `backend/src/analysis/molding_analyzer.py`, `backend/src/analysis/casting_analyzer.py`, `backend/src/analysis/sheet_metal_analyzer.py`
- Contains: Process-specific checker functions (e.g., `check_wall_thickness`, `check_overhang`)
- Depends on: trimesh, geometry helpers
- Used by: Routes dispatcher as fallback when registry lookup returns None

**Feature Detection:**
- Purpose: Segment and identify geometric features (holes, bosses, ribs, fillets, etc.)
- Location: `backend/src/analysis/features/` (base, cylinders, flats, detector)
- Contains: Feature base class, cylinder detection via Hough transform, flat surface detection, top-level detector orchestrator
- Depends on: numpy, scipy, trimesh
- Used by: Routes to populate `features` array in response (optional)

**Segmentation & Instance Segmentation (SAM 3D):**
- Purpose: AI-powered geometric segmentation; fallback to heuristic clustering
- Location: `backend/src/segmentation/sam3d_segmenter.py`, `backend/src/segmentation/sam3d/`, `backend/src/segmentation/fallback.py`
- Contains: SAM 3D renderer, lifter, pipeline; fallback geometry-based segmentation
- Depends on: External SAM 3D model, trimesh, numpy
- Used by: Context builder to populate `segments` field; optional Phase 3 feature

**Rule Packs (Industry Overlays):**
- Purpose: Post-process analyzer issues with industry-specific thresholds and severity escalation
- Location: `backend/src/analysis/rules/` (aerospace, automotive, medical, oil_gas)
- Contains: RulePack dataclass, RuleOverride rules, registration decorator
- Depends on: Analysis models
- Used by: Routes after process analysis to apply optional tightening

**Profile Database & Matching:**
- Purpose: Material and machine inventory; score processes against part geometry
- Location: `backend/src/profiles/database.py`, `backend/src/profiles/materials/`, `backend/src/matcher/profile_matcher.py`
- Contains: Material library (41 materials), Machine library (19 machines), process-material-machine mappings, scoring logic
- Depends on: Analysis models, geometry info
- Used by: Routes to recommend materials/machines; feature `/processes`, `/materials`, `/machines` endpoints

**Parsers:**
- Purpose: Convert file bytes to trimesh.Trimesh objects
- Location: `backend/src/parsers/step_parser.py`, `backend/src/parsers/stl_parser.py`
- Contains: STEP parser (cadquery-optional), STL parser (trimesh)
- Depends on: trimesh, cadquery (optional)
- Used by: Routes to parse uploads

**Frontend (Next.js):**
- Purpose: SPA for file upload, 3D visualization, results dashboard
- Location: `frontend/src/`
- Contains: Page layout, file drop zone, 3D model viewer (Three.js/React Three Fiber), analysis dashboard, issue list, process cards, rule pack selector
- Depends on: Next.js 16, React 19, Three.js, Tailwind CSS
- Used by: Browser clients

## Data Flow

**Upload & Analysis Request:**

1. Browser user uploads STEP/STL file via `FileDropZone` component (`frontend/src/components/FileDropZone.tsx`)
2. Frontend calls `validateFile()` from `frontend/src/lib/api.ts` with optional process filter and rule pack name
3. HTTP POST to `POST /api/v1/validate?processes=...&rule_pack=...` with multipart file body
4. Backend `validate_file()` in `backend/src/api/routes.py` receives request

**File Parsing & Preparation:**

5. Chunked streaming read of upload with size cap (default 100 MB)
6. Calls `_parse_mesh(data, filename)` to dispatch to STEP or STL parser
7. Calls `parse_step_from_bytes()` or `parse_stl_from_bytes()` → returns `trimesh.Trimesh`
8. Calls `analyze_geometry(mesh)` → extracts bounding box, volume, surface area, watertightness, etc.
9. Calls `GeometryContext.build(mesh, geometry)` → precomputes:
   - Per-face normals, centroids, areas, angles from up
   - Wall thickness via inward ray cast (vectorized)
   - Edge lengths, dihedral angles, concavity mask
   - Connected body count, coplanar facet groups
   - All results cached as numpy arrays for reuse

**Universal Checks:**

10. Calls `run_universal_checks(mesh)` → checks watertightness, normal consistency, degenerate faces, self-intersections, disconnected bodies
11. Returns list of `Issue` objects with severity ERROR/WARNING

**Feature Detection (Optional):**

12. Calls `detect_features(mesh)` → invokes cylinder, flat, and general feature detectors
13. Populates `ctx.features` and `ctx.segments`

**Process-Specific Analysis (Parallel in concept):**

14. Resolves target process list from query param (or all 21 if omitted)
15. For each process:
    - Calls `get_analyzer(ProcessType)` → returns registered ProcessAnalyzer or None
    - If registered: calls `analyzer.analyze(ctx)` → returns process issues
    - Else: falls back to legacy function (e.g., `run_additive_checks(mesh, geometry, proc, segments)`)
16. If rule pack specified, calls `pack.apply(proc_issues, proc)` to overlay severity & thresholds
17. Calls `score_process(proc_issues, geometry, proc)` → computes viability score (0.0–1.0), verdict (pass/issues/fail), material/machine recommendations

**Response Construction:**

18. Assembles `AnalysisResult` dataclass with:
    - File metadata (name, type)
    - Geometry summary
    - Universal issues
    - Process scores (one per process)
    - Best process (highest score)
    - Analysis time
19. Serializes to JSON
20. Returns 200 OK with `AnalysisResult` JSON

**Frontend Rendering:**

21. Component `AnalysisDashboard` receives `ValidationResult`
22. Renders verdict banner, geometry summary, priority fixes
23. Component `ModelViewer` (Three.js) loads and displays mesh
24. Component `IssueList` renders `universal_issues` and per-process issues grouped by severity
25. Components `ProcessScoreCard` render one card per process with score, verdict, material/machine suggestions

## Key Abstractions

**GeometryContext:**
- Purpose: Immutable, precomputed geometry state shared across all analyzers
- Attributes: Mesh, geometry info, per-face/per-edge arrays, topology, features, segments
- Pattern: Builder pattern (`GeometryContext.build(mesh, info)`) with safe defaults on compute failure
- File: `backend/src/analysis/context.py`

**ProcessAnalyzer Protocol:**
- Purpose: Interface contract for process-specific analyzers
- Methods: `analyze(ctx: GeometryContext) → list[Issue]`
- Attributes: `process: ProcessType`, `standards: list[str]`
- Pattern: Runtime protocol check; @register decorator for discovery
- File: `backend/src/analysis/processes/base.py`

**Issue:**
- Purpose: Represents one DFM problem (error, warning, or info)
- Fields: code, severity, message, process, affected_faces, fix_suggestion, measured_value, required_value
- Pattern: Dataclass; mutable in-place during rule pack application
- File: `backend/src/analysis/models.py`

**RulePack & RuleOverride:**
- Purpose: Industy-specific overlay rules applied post-analysis
- Pattern: Decorator-registered packs; overrides matched by issue code + process
- File: `backend/src/analysis/rules/__init__.py`

**ProcessScore:**
- Purpose: Composite result of one process: viability, issues, recommendations
- Fields: process, score, verdict, issues, recommended_material, recommended_machine, cost_factor
- Pattern: Built by `score_process()` in matcher
- File: `backend/src/analysis/models.py`

## Entry Points

**API Endpoint: POST /api/v1/validate**
- Location: `backend/src/api/routes.py::validate_file()`
- Triggers: HTTP POST from browser with multipart file upload
- Responsibilities: Parse request → load & parse file → run all analysis → apply rule pack (optional) → score processes → return JSON

**API Endpoint: POST /api/v1/validate/quick**
- Location: `backend/src/api/routes.py::validate_quick()`
- Triggers: HTTP POST with minimal response expectation
- Responsibilities: Parse file → run universal checks only → return verdict + issues (subset of full analysis)

**API Endpoint: GET /api/v1/processes**
- Location: `backend/src/api/routes.py::list_processes()`
- Returns: Available processes with material and machine counts

**API Endpoint: GET /api/v1/materials** / **/machines** / **/rule-packs**
- Location: `backend/src/api/routes.py`
- Returns: Profile database inventory and rule pack metadata

**Frontend Entry: Home (Next.js Page)**
- Location: `frontend/src/app/page.tsx`
- Triggers: Browser navigation to `/`
- Responsibilities: State management for file, result, loading; render upload UI or dashboard

## Error Handling

**Strategy:** Graceful degradation with detailed error messages

**Patterns:**

- **Parse Errors:** HTTPException(400) with parser-provided message; logged at exception level
- **Geometry Errors:** Safe defaults in context builder (inf for thickness, empty arrays for topology) so malformed meshes don't crash analyzers
- **Analyzer Exceptions:** Caught and logged per-process; analysis continues for other processes
- **Upload Size:** Stream-read with per-chunk validation; HTTPException(413) if exceeds MAX_UPLOAD_MB
- **Rule Pack Lookup:** HTTPException(400) if pack name unrecognized; lists available packs
- **Process Resolution:** HTTPException(400) if process token invalid; lists valid processes

## Cross-Cutting Concerns

**Logging:** 
- Python logging module with configurable level (env: LOG_LEVEL, default INFO)
- All loggers named under "cadverify" hierarchy
- Routes log request metadata (filename, file size, analysis time), parse failures, analyzer exceptions

**Validation:**
- Pydantic models for API requests and responses (models.py)
- File type validation by extension (.stl, .step, .stp)
- Process type validation via ProcessType enum
- Geometry validation in context builder (bounds checks, array shape validation)

**CORS:**
- Middleware configured from env ALLOWED_ORIGINS (default localhost:3000)
- Methods: GET, POST, OPTIONS
- Credentials disabled (stateless API)

---

*Architecture analysis: 2026-04-15*
