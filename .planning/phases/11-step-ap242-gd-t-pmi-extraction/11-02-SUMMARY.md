---
phase: 11
plan: "02"
subsystem: analysis/parsers
tags: [gdt, pmi, tolerance, iso-1101, ap242, xde]
dependency_graph:
  requires: [step_ap242_parser, AP242Document]
  provides: [tolerance_models, gdt_extractor, extract_gdt, extract_surface_finish, ToleranceType, ToleranceEntry, ToleranceReport]
  affects: [analysis pipeline, achievability checks]
tech_stack:
  added: [OCP.XCAFDimTolObjects]
  patterns: [feature-gating, partial-extraction, enum-mapping, dataclass-result]
key_files:
  created:
    - backend/src/analysis/tolerance_models.py
    - backend/src/parsers/gdt_extractor.py
    - backend/tests/test_gdt_extractor.py
  modified: []
decisions:
  - "Used integer-keyed _OCP_TYPE_MAP with string fallback for OCP GeomToleranceType resolution"
  - "Partial extraction: individual annotation failures produce warnings, not exceptions"
  - "Auto-generated TOL-NNN IDs include failed extractions in counter to maintain stable numbering"
metrics:
  duration_seconds: 221
  completed: "2026-04-17T01:57:42Z"
  tasks_completed: 3
  tasks_total: 3
  test_count: 9
  files_created: 3
---

# Phase 11 Plan 02: GD&T/PMI Extraction + Tolerance Data Model Summary

ISO 1101 tolerance data model (14 types, 5 dataclasses) with GD&T extractor using OCP XDE DimTolTool, partial-extraction resilience, and datum reference resolution.

## Task Summary

| Task | Title | Commit | Key Files |
|------|-------|--------|-----------|
| 11-02-01 | Create tolerance data model | `0fdc098` | `backend/src/analysis/tolerance_models.py` |
| 11-02-02 | Implement GD&T extractor | `5812d0e` | `backend/src/parsers/gdt_extractor.py` |
| 11-02-03 | Create GD&T extractor tests | `e07c72a` | `backend/tests/test_gdt_extractor.py` |

## What Was Built

### Tolerance Data Model (`tolerance_models.py`)
- `ToleranceType` enum: 14 ISO 1101 categories (form, orientation, location, profile, runout)
- `AchievabilityVerdict` enum: achievable / marginal / not_achievable
- `ToleranceEntry` dataclass: tolerance_id, type, value_mm, deviations, datum_refs, surface_finish_ra
- `ToleranceAchievability` dataclass: links tolerance to process capability with margin
- `ToleranceReport` dataclass: aggregates has_pmi, tolerances, achievability, summary_score

### GD&T Extractor (`gdt_extractor.py`)
- Feature-gated OCP imports (`_HAS_XDE` flag) -- graceful degradation without OCP
- `_OCP_TYPE_MAP`: integer-keyed map covering all 14 tolerance types
- `_NAME_TYPE_MAP`: string fallback for name-based type resolution
- `extract_gdt()`: traverses DimTolTool GDT labels, extracts geometric/dimensional tolerances
- `_collect_datums()`: builds datum label-to-letter mapping
- `_extract_datum_refs()`: resolves datum references for each tolerance
- `extract_surface_finish()`: reads Ra surface finish annotations from PMI
- Partial extraction: individual annotation failures logged as warnings, extraction continues

### Tests (9 passing)
- Enum coverage, empty document, partial failure, ID generation, field typing, surface finish

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed test patching for OCP-absent environment**
- **Found during:** Task 3
- **Issue:** `unittest.mock.patch` cannot patch module attributes that don't exist when OCP is not installed (TDF_LabelSequence, XCAFDimTolObjects_* not present)
- **Fix:** Used `patch(..., create=True)` and context-manager-style patching instead of decorator-style
- **Files modified:** `backend/tests/test_gdt_extractor.py`
- **Commit:** `e07c72a`

## Verification Results

- `ToleranceType` enum count: 14 (confirmed)
- `extract_gdt` imports without error (confirmed)
- `pytest backend/tests/test_gdt_extractor.py -v`: 9/9 passed
- All 14 ISO 1101 types represented in both ToleranceType and _OCP_TYPE_MAP

## Self-Check: PASSED
