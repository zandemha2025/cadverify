# Phase 11: STEP AP242 + GD&T/PMI Extraction - Context

**Gathered:** 2026-04-15
**Status:** Ready for planning
**Mode:** `--auto` (Claude selected recommended defaults for every gray area -- see each D-## "Rationale" line for the decision basis; user to review and override before `/gsd-plan-phase 11` if desired)

<domain>
## Phase Boundary

This phase moves CadVerify beyond triangle-mesh approximation by parsing STEP AP242 files to extract real engineering data: B-rep (boundary representation) geometry, GD&T (Geometric Dimensioning and Tolerancing) annotations, datum references, and surface finish requirements. Extracted tolerances are validated against manufacturing process capability tables to answer "can this process hold this tolerance on this feature?"

Deliverables:
1. STEP AP242 parser module using OpenCascade (OCP) XDE framework for B-rep + PMI extraction.
2. GD&T/PMI extraction service producing structured tolerance, datum, and surface finish data.
3. Process capability tolerance tables (per-process tolerance limits by feature type).
4. Enhanced analyzer path using parametric B-rep features instead of tessellated mesh.
5. Tolerance achievability report section integrated into existing analysis output.
6. Updated PDF template with tolerance table.

**Explicitly out of scope for this phase:**
- Full CAM toolpath generation from B-rep features
- Editing or modifying STEP geometry (we analyze, we don't author)
- AP203 legacy format support (minimal PMI content; not worth the effort)
- Custom tolerance table editor UI (tables are config-driven, editable by developers)
- Real-time 3D B-rep visualization in frontend (tessellated mesh view is sufficient)
- GD&T annotation overlay rendering on 3D model in browser

</domain>

<decisions>
## Implementation Decisions

### STEP AP Standard Targeting
- **D-01:** Target **AP242 as primary**, with **AP214 as read fallback** for geometry-only extraction (no PMI).
  - Rationale (auto): AP242 is the modern standard that embeds PMI/GD&T data directly. AP214 has geometry but typically lacks embedded tolerances. Supporting AP214 for geometry-only (B-rep extraction, no PMI) is low-cost since OCP reads both. AP203 is too old and has negligible PMI content.
- **D-02:** Use **OCP (OpenCascade Python bindings via cadquery-ocp)** directly, not cadquery's high-level API, for XDE/PMI access.
  - Rationale (auto): cadquery wraps OCP for parametric modeling but does not expose the XDE (Extended Data Exchange) framework needed for PMI extraction. Direct OCP access via `OCP.XDE`, `OCP.XCAFDoc`, and `OCP.STEPCAFControl` is required to read GD&T annotations from AP242 files.

### GD&T Data Model
- **D-03:** Represent extracted GD&T data using **Pydantic models mirroring ISO 1101 structure**.
  - Rationale (auto): Consistent with existing codebase (dataclasses/Pydantic throughout models.py). ISO 1101 is the standard for GD&T; mirroring its structure avoids lossy translation.
- **D-04:** Model hierarchy: `ToleranceSet` contains multiple `Tolerance` entries, each with `tolerance_type` (flatness, concentricity, position, etc.), `value` (nominal + upper/lower deviation), `datum_refs` (list of datum labels), `feature_ref` (which B-rep face/edge), and `surface_finish` (Ra value if specified).
  - Rationale (auto): This captures the essential GD&T fields needed for process capability validation without over-engineering into full ASME Y14.5 semantic representation.
- **D-05:** Store datum references as **string labels** (A, B, C) with optional datum feature geometry linkage.
  - Rationale (auto): Datum labels are the universal reference in engineering drawings; storing them as strings with optional geometry linkage keeps the model simple while enabling future 3D datum visualization.

### Tolerance-to-Process Mapping
- **D-06:** Process capability tables stored as a **YAML config file** in `backend/src/analysis/capabilities/` directory.
  - Rationale (auto): YAML is human-readable, easy to audit, and consistent with how constants.py centralizes thresholds. A config file allows domain experts to update tolerance limits without code changes.
- **D-07:** Capability table structure: keyed by `process_type` (matching existing `ProcessType` enum), then by `tolerance_type`, with fields for `achievable_min` (tightest tolerance the process can hold), `typical_range`, and `notes`.
  - Rationale (auto): This maps directly to the validation question "can process X hold tolerance Y?" and integrates naturally with the existing 21-process analyzer registry.
- **D-08:** Include **surface finish (Ra) achievability** per process in the same capability tables.
  - Rationale (auto): Surface finish is commonly specified alongside GD&T and is a critical DFM check. Bundling it avoids a separate lookup path.

### Enhanced Analysis Output
- **D-09:** Extend `AnalysisResult` with an **optional `tolerances` section** -- present only when STEP AP242 with PMI is provided, absent for STL/plain-STEP uploads.
  - Rationale (auto): Backward-compatible; existing STL/mesh-only analysis is unaffected. The tolerances section activates only when richer input data is available.
- **D-10:** Tolerance achievability reported as a **per-tolerance verdict**: `achievable`, `marginal`, or `not_achievable` for each process, with the tightest-achievable process highlighted.
  - Rationale (auto): Engineers need per-tolerance, per-process answers. Three-level verdict (achievable/marginal/not_achievable) mirrors the existing severity model (info/warning/error).
- **D-11:** Include a **summary tolerance score** (0-100) indicating what percentage of specified tolerances are achievable by the recommended process.
  - Rationale (auto): Provides a quick at-a-glance metric alongside the existing manufacturability verdict.

### Integration Strategy
- **D-12:** Create a **new dedicated module** `backend/src/parsers/step_ap242_parser.py` for AP242+PMI extraction. Existing `step_parser.py` remains untouched for the mesh tessellation path.
  - Rationale (auto): Separation of concerns. The existing step_parser.py handles STEP-to-mesh conversion (tessellation). AP242 PMI extraction is a fundamentally different operation (reading annotations from XDE document, not tessellating shapes). Keeping them separate avoids breaking the existing pipeline.
- **D-13:** Create `backend/src/services/tolerance_service.py` to orchestrate: parse AP242 -> extract PMI -> validate against capability tables -> produce tolerance report.
  - Rationale (auto): Follows the existing service pattern (analysis_service.py, repair_service.py). Service layer wraps the parsing + validation logic.
- **D-14:** The `/api/v1/validate` endpoint gains **automatic AP242 detection**: if the uploaded STEP file contains PMI data, the tolerance analysis runs alongside the existing mesh-based analysis. No new endpoint needed.
  - Rationale (auto): Seamless upgrade path. Users uploading AP242 files get richer results without changing their API call. The existing endpoint already handles STEP files.

### Fallback Behavior
- **D-15:** When a STEP file is uploaded but contains **no PMI/GD&T data**, fall back to the existing mesh-based analysis with an `info`-level note: "No GD&T annotations found; analysis based on geometry only."
  - Rationale (auto): Graceful degradation. Most STEP files in the wild are AP214 or AP242 without PMI. Users should still get useful results, not an error.
- **D-16:** When PMI extraction **partially fails** (some annotations unreadable), extract what is available and report a `warning`-level note listing skipped annotations.
  - Rationale (auto): Real-world AP242 files often have inconsistent PMI quality. Partial extraction is more useful than all-or-nothing failure.

### Claude's Discretion
- Exact OCP API call sequences for XDE traversal (implementation detail)
- Internal caching strategy for parsed B-rep features
- Specific YAML schema formatting for capability tables
- PDF template layout for the tolerance table section
- Unit handling (mm vs inches) during tolerance extraction

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing STEP Parser
- `backend/src/parsers/step_parser.py` -- Current STEP-to-mesh pipeline using cadquery; new AP242 module must coexist without modifying this file
- `backend/src/parsers/__init__.py` -- Parser module structure

### Analysis Pipeline
- `backend/src/analysis/models.py` -- `AnalysisResult`, `Issue`, `ProcessType`, `Severity` models; tolerance extension goes here
- `backend/src/analysis/constants.py` -- Centralized manufacturing thresholds; capability tables follow this pattern
- `backend/src/analysis/context.py` -- `GeometryContext` shared precomputation; B-rep context may extend this
- `backend/src/analysis/cnc_analyzer.py` -- Example process analyzer; shows how tolerances could integrate with process-specific checks

### Service Layer
- `backend/src/services/analysis_service.py` -- Orchestration pattern for parse -> analyze -> persist; tolerance_service follows this
- `backend/src/api/routes.py` -- `/validate` endpoint where AP242 detection hooks in

### Requirements
- `.planning/REQUIREMENTS.md` -- STEP-01 through STEP-05 define acceptance criteria
- `.planning/ROADMAP.md` -- Phase 11 details, success criteria, suggested plan decomposition

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `step_parser.py`: Already imports `OCP.STEPControl` and `cadquery` -- confirms OCP is available in the environment. AP242 module can import from the same OCP package.
- `ProcessType` enum: All 21 processes already defined; capability tables map 1:1 to these.
- `Issue` / `Severity` model: Tolerance validation issues can use the same model (achievable=info, marginal=warning, not_achievable=error).
- `analysis_service.py`: Service orchestration pattern (hash -> cache -> run -> persist) reusable for tolerance results.

### Established Patterns
- **Registry pattern**: Process analyzers register via `@register` decorator. Capability tables should follow a similar discoverable pattern.
- **Optional cadquery**: `_HAS_CADQUERY` flag in step_parser.py shows the pattern for optional dependency gating. AP242 extraction should similarly gate on OCP availability.
- **Service layer**: All business logic goes through `services/` (analysis_service, repair_service, batch_service). Tolerance validation follows this.
- **Constants centralization**: `analysis/constants.py` holds all thresholds. Capability tables extend this concept.

### Integration Points
- `/api/v1/validate` endpoint in `routes.py`: AP242 detection hooks here (check if uploaded STEP has PMI, run tolerance analysis alongside mesh analysis).
- `AnalysisResult` in `models.py`: Extended with optional `tolerances` field.
- PDF template (via `pdf_service.py`): New tolerance table section appended to existing template.
- `analysis_service.py`: Wraps tolerance_service call when AP242 PMI is detected.

</code_context>

<specifics>
## Specific Ideas

- Target customer (Saudi Aramco) has engineering drawings with GD&T callouts -- AP242 extraction directly addresses their workflow of validating legacy part manufacturability.
- Process capability tables should initially cover the most common tolerance types: flatness, parallelism, perpendicularity, concentricity, position, circularity, cylindricity, and surface finish (Ra).
- The tolerance achievability report should be useful as a standalone section in the PDF export (Phase 4 already built WeasyPrint templates).

</specifics>

<deferred>
## Deferred Ideas

- **GD&T annotation overlay on 3D viewer** -- Would require Three.js rendering of tolerance callouts on the mesh; belongs in a future frontend enhancement phase.
- **Custom tolerance table editor UI** -- Enterprise customers may want to customize capability tables via the web UI; belongs in a future configuration phase.
- **AP203 legacy support** -- Minimal PMI content in AP203; not worth engineering effort unless customer demand emerges.
- **Tolerance stack-up analysis** -- Analyzing how individual tolerances combine in assemblies; separate capability beyond single-part DFM.

</deferred>

---

*Phase: 11-step-ap242-gd-t-pmi-extraction*
*Context gathered: 2026-04-15 via auto mode*
