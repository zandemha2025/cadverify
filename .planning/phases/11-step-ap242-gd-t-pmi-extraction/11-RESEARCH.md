# Phase 11: STEP AP242 + GD&T/PMI Extraction — Research

## RESEARCH COMPLETE

**Date:** 2026-04-15
**Phase:** 11 — STEP AP242 + GD&T/PMI Extraction
**Requirements:** STEP-01, STEP-02, STEP-03, STEP-04, STEP-05

---

## 1. OpenCascade/OCP AP242 PMI API Surface

### XDE Framework for PMI Access

The OCP (OpenCascade Python bindings, shipped via `cadquery-ocp` or `cadquery-ocp-novtk`) exposes the XDE (Extended Data Exchange) framework through these key modules:

- **`OCP.STEPCAFControl.STEPCAFControl_Reader`** — Reads STEP AP242 into an XDE document (preserves PMI, colors, layers, unlike `STEPControl_Reader` which drops PMI).
- **`OCP.TDocStd.TDocStd_Document`** — The XDE document container.
- **`OCP.XCAFDoc`** — Document attribute access:
  - `XCAFDoc_DimTolTool` — Access to GD&T dimensions and tolerances.
  - `XCAFDoc_ShapeTool` — Shape hierarchy traversal.
  - `XCAFDoc_MaterialTool` — Material properties.
- **`OCP.XCAFDimTolObjects`** — Tolerance/dimension data objects:
  - `XCAFDimTolObjects_GeomToleranceObject` — Geometric tolerance (flatness, concentricity, position, etc.)
  - `XCAFDimTolObjects_DimensionObject` — Linear/angular dimensions with deviations.
  - `XCAFDimTolObjects_DatumObject` — Datum feature definitions.

### Reading Flow

```
STEPCAFControl_Reader → TDocStd_Document → XCAFDoc_DimTolTool
                                          → iterate labels → extract tolerance/datum objects
```

Key steps:
1. Create `TDocStd_Document("XDE")` with an `XCAFApp_Application`.
2. Use `STEPCAFControl_Reader` with `reader.ReadFile(path)` and `reader.Transfer(doc)`.
3. Get `DimTolTool` from `XCAFDoc_DimTolTool.GetID()` on the document's main label.
4. Use `GetGDTLabels()` to iterate all GD&T annotations.
5. For each label, get the tolerance object via `GetGeomTolerance()` or `GetDimension()`.
6. Extract: tolerance type, value, datum references, associated shape.

### AP242 vs AP214 Detection

- After reading with `STEPCAFControl_Reader`, check if `DimTolTool.GetGDTLabels()` returns any labels.
- If empty → file has no PMI (likely AP214 or AP242 without embedded tolerances).
- The reader handles both AP214 and AP242 transparently — format detection is automatic.

### OCP Availability

The existing `step_parser.py` already checks `_HAS_OCP` and imports from `OCP.STEPControl`. The AP242 module should follow the same pattern, checking for the additional XDE/XCAF imports needed.

---

## 2. GD&T Data Model (ISO 1101)

### Core Tolerance Types for DFM

| ISO 1101 Type | Symbol | DFM Relevance | OCP Class |
|---------------|--------|---------------|-----------|
| Flatness | ⏥ | Surface finish, mating faces | `XCAFDimTolObjects_GeomToleranceType.GeomToleranceType_Flatness` |
| Straightness | — | Shaft/bore alignment | `GeomToleranceType_Straightness` |
| Circularity | ○ | Turned features, bearings | `GeomToleranceType_Roundness` |
| Cylindricity | ⌭ | Bore/shaft quality | `GeomToleranceType_Cylindricity` |
| Parallelism | ∥ | Mating surface alignment | `GeomToleranceType_Parallelism` |
| Perpendicularity | ⊥ | Hole-to-face, assembly fit | `GeomToleranceType_Perpendicularity` |
| Angularity | ∠ | Angled features | `GeomToleranceType_Angularity` |
| Position | ⊕ | Hole patterns, mounting points | `GeomToleranceType_Position` |
| Concentricity | ⊚ | Rotating components | `GeomToleranceType_Concentricity` |
| Symmetry | ≡ | Keyed features | `GeomToleranceType_Symmetry` |
| Profile (surface) | ⌓ | Complex surfaces | `GeomToleranceType_ProfileOfSurface` |
| Profile (line) | ⌒ | Cross-section profiles | `GeomToleranceType_ProfileOfLine` |
| Runout (circular) | ↗ | Rotating assemblies | `GeomToleranceType_CircularRunout` |
| Runout (total) | ↗↗ | Full rotation check | `GeomToleranceType_TotalRunout` |

### Surface Finish (Ra)

Surface roughness (Ra, arithmetic average) is commonly specified alongside GD&T. OCP exposes surface finish through `XCAFDoc_MaterialTool` or as PMI annotations. Standard Ra values range from 0.1 um (mirror finish) to 25 um (rough machining).

### Data Model Design

```python
@dataclass
class ToleranceEntry:
    tolerance_id: str              # Auto-generated ID (TOL-001, TOL-002, ...)
    tolerance_type: str            # ISO 1101 type name (flatness, position, etc.)
    value_mm: float                # Tolerance zone width in mm
    upper_deviation: float | None  # For dimensional tolerances
    lower_deviation: float | None  # For dimensional tolerances
    datum_refs: list[str]          # Datum labels (A, B, C)
    feature_description: str       # Human-readable feature description
    surface_finish_ra: float | None  # Ra in micrometers, if specified

@dataclass
class ToleranceAchievability:
    tolerance_id: str
    process: ProcessType
    verdict: str                   # "achievable", "marginal", "not_achievable"
    process_capability: float      # Tightest tolerance the process can hold
    margin: float                  # How much slack (positive = achievable)

@dataclass
class ToleranceReport:
    tolerances: list[ToleranceEntry]
    achievability: list[ToleranceAchievability]
    summary_score: float           # 0-100: % of tolerances achievable by best process
    has_pmi: bool                  # Whether PMI data was found
    pmi_note: str | None           # Info/warning about PMI extraction quality
```

---

## 3. Process Capability Tolerance Tables

### Structure

Keyed by process type, then by tolerance type category (form, orientation, location, runout):

```yaml
cnc_3axis:
  form:
    flatness: { achievable_min: 0.005, typical: 0.01-0.05, notes: "Depends on clamping" }
    circularity: { achievable_min: 0.005, typical: 0.01-0.03 }
    cylindricity: { achievable_min: 0.008, typical: 0.01-0.05 }
  orientation:
    parallelism: { achievable_min: 0.005, typical: 0.01-0.05 }
    perpendicularity: { achievable_min: 0.005, typical: 0.01-0.05 }
  location:
    position: { achievable_min: 0.01, typical: 0.02-0.10 }
    concentricity: { achievable_min: 0.01, typical: 0.02-0.05 }
  runout:
    circular_runout: { achievable_min: 0.005, typical: 0.01-0.05 }
  surface_finish:
    ra_min_um: 0.4
    ra_typical_um: 1.6
```

### Process Coverage

All 21 `ProcessType` values should have capability entries. Additive processes generally have looser tolerances (0.1-0.5mm) while subtractive processes are tighter (0.005-0.05mm). Formative processes vary widely.

### Validation Logic

For each extracted tolerance:
1. Look up the process capability for that tolerance type.
2. Compare tolerance value against `achievable_min`:
   - value >= achievable_min * 2 → `achievable`
   - value >= achievable_min → `marginal`
   - value < achievable_min → `not_achievable`
3. Surface finish Ra: compare against `ra_min_um` per process.

---

## 4. B-rep vs Mesh Analysis Trade-offs

### When B-rep is Better

- **Exact geometry**: No tessellation error. A 0.01mm tolerance on a face is meaningless if the tessellation introduces 0.05mm chord error.
- **Feature recognition**: Holes, fillets, chamfers are directly represented in B-rep topology (through edges, faces with analytical surface types).
- **Tolerance validation**: GD&T is defined on B-rep features (faces, edges, datums), not on mesh triangles.

### When Mesh Analysis is Still Needed

- **Universal checks** (watertight, manifold, degenerate faces) still operate on mesh.
- **Visualization** — frontend uses tessellated mesh via Three.js.
- **Process-specific DFM checks** — existing 21 analyzers are mesh-based and work well. Rewriting them for B-rep is out of scope.

### Hybrid Approach (Recommended)

1. Parse STEP AP242 → extract B-rep + PMI.
2. **Tessellate** B-rep → mesh (same as current `step_parser.py`).
3. Run existing mesh-based analysis pipeline on tessellated mesh.
4. **Additionally** run tolerance validation on the B-rep PMI data.
5. Merge both results into a single `AnalysisResult` with the new `tolerances` section.

This approach means **zero changes to existing analyzers** — they continue to receive `trimesh.Trimesh` objects. The tolerance analysis is a parallel, additive enrichment.

---

## 5. Integration Architecture

### File Flow

```
Upload STEP file
    │
    ├── step_parser.py (existing) ──→ trimesh.Trimesh ──→ existing analysis pipeline
    │
    └── step_ap242_parser.py (new) ──→ ToleranceReport ──→ merged into response
```

### Service Layer

`tolerance_service.py`:
1. Receive file bytes + filename.
2. Attempt AP242 parse with `STEPCAFControl_Reader`.
3. If PMI found → extract tolerances → validate against capability tables → return `ToleranceReport`.
4. If no PMI → return `ToleranceReport(has_pmi=False, pmi_note="No GD&T annotations found")`.

`analysis_service.py` (modified):
- After running the existing pipeline, call `tolerance_service` for STEP files.
- Merge `ToleranceReport` into the response dict under a `tolerances` key.

### Response Format Extension

```json
{
  "filename": "part.step",
  "verdict": "issues",
  "geometry": { ... },
  "process_scores": [ ... ],
  "tolerances": {
    "has_pmi": true,
    "summary_score": 85,
    "pmi_note": null,
    "entries": [
      {
        "id": "TOL-001",
        "type": "position",
        "value_mm": 0.05,
        "datum_refs": ["A", "B"],
        "feature": "4x M6 mounting holes",
        "surface_finish_ra": null,
        "achievability": {
          "cnc_3axis": { "verdict": "achievable", "capability": 0.01, "margin": 0.04 },
          "cnc_5axis": { "verdict": "achievable", "capability": 0.01, "margin": 0.04 },
          "fdm": { "verdict": "not_achievable", "capability": 0.2, "margin": -0.15 }
        }
      }
    ]
  }
}
```

---

## 6. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| OCP XDE API coverage incomplete for some tolerance types | Medium | Start with the 8 most common types; add others incrementally |
| AP242 files in the wild rarely have full PMI | Medium | Graceful degradation (D-15, D-16); info note when no PMI |
| Capability table accuracy | Low | Use industry-standard references (Machinery's Handbook); iterate with real engineers |
| OCP version compatibility | Low | Pin cadquery-ocp version; test against known AP242 sample files |
| Performance overhead of XDE parsing | Low | XDE parse runs once alongside tessellation; marginal overhead vs existing STEP parse |

---

## 7. Test Strategy

- **Unit tests**: Mock OCP XDE objects to test tolerance extraction logic.
- **Integration tests**: Use real AP242 sample files (NIST CAD models have public AP242 with PMI).
- **Capability table tests**: Validate all 21 processes have entries; boundary tests on achievable/marginal/not_achievable thresholds.
- **Fallback tests**: AP214 file (no PMI) → graceful degradation with info note.
- **Regression**: Existing STL analysis unchanged after integration.

---

*Research complete: 2026-04-15*
*Phase: 11-step-ap242-gd-t-pmi-extraction*
