# Phase 11: STEP AP242 + GD&T/PMI Extraction - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-04-15
**Phase:** 11-step-ap242-gd-t-pmi-extraction
**Areas discussed:** OpenCascade/OCP B-rep, AP242 vs AP214, GD&T Data Model, Tolerance-to-Process Mapping, Enhanced Analysis Output, Integration Strategy, Fallback Behavior
**Mode:** Auto (all defaults selected by Claude)

---

## STEP AP Standard Targeting

| Option | Description | Selected |
|--------|-------------|----------|
| AP242 primary, AP214 geometry-only fallback | Modern standard with PMI; AP214 read for geometry when no PMI | ✓ |
| AP242 only, reject AP214 | Strict -- only accept files with PMI capability | |
| AP242 + AP214 + AP203 full support | Maximum compatibility but high engineering cost | |

**User's choice:** [auto] AP242 primary, AP214 fallback (recommended default)
**Notes:** AP242 is the only standard with rich embedded PMI. AP214 support for geometry-only is low-cost via OCP.

## GD&T Data Model

| Option | Description | Selected |
|--------|-------------|----------|
| Pydantic models mirroring ISO 1101 | Structured, typed, consistent with codebase patterns | ✓ |
| Raw dict/JSON extraction | Flexible but untyped, harder to validate | |
| Full ASME Y14.5 semantic model | Comprehensive but over-engineered for DFM validation | |

**User's choice:** [auto] Pydantic models mirroring ISO 1101 (recommended default)
**Notes:** Matches existing dataclass/Pydantic patterns in models.py.

## Tolerance-to-Process Mapping

| Option | Description | Selected |
|--------|-------------|----------|
| YAML config file in capabilities/ directory | Human-readable, auditable, expert-editable | ✓ |
| Hardcoded in Python constants | Fast to implement but hard for domain experts to update | |
| Database-backed with admin UI | Most flexible but adds scope (UI + schema + CRUD) | |

**User's choice:** [auto] YAML config file (recommended default)
**Notes:** Consistent with constants centralization pattern. Domain experts can update without code changes.

## Enhanced Analysis Output

| Option | Description | Selected |
|--------|-------------|----------|
| Optional tolerances section on AnalysisResult | Backward-compatible, activates only for AP242+PMI | ✓ |
| Separate tolerance-specific endpoint | Clean separation but fragmentary UX | |
| Always present with empty defaults | Simpler code but confusing for STL-only uploads | |

**User's choice:** [auto] Optional tolerances section (recommended default)
**Notes:** Backward-compatible approach preserves existing API contract.

## Integration Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| New dedicated module + service | Separation of concerns, existing code untouched | ✓ |
| Extend existing step_parser.py | Fewer files but mixes mesh tessellation with PMI extraction | |
| Standalone microservice | Maximum isolation but deployment complexity | |

**User's choice:** [auto] New dedicated module (recommended default)
**Notes:** step_parser.py stays for mesh path; step_ap242_parser.py handles PMI.

## Fallback Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Graceful degradation with info note | Users still get mesh analysis when no PMI present | ✓ |
| Error when PMI missing | Strict -- forces users to provide AP242 with PMI | |
| Silent fallback (no note) | Seamless but users don't know they're missing richer analysis | |

**User's choice:** [auto] Graceful degradation with info note (recommended default)
**Notes:** Most STEP files lack PMI; error would reject most uploads.

## Claude's Discretion

- OCP API call sequences for XDE traversal
- Internal caching strategy for parsed B-rep features
- YAML schema formatting for capability tables
- PDF template layout for tolerance table section
- Unit handling (mm vs inches)

## Deferred Ideas

- GD&T annotation overlay on 3D viewer -- future frontend phase
- Custom tolerance table editor UI -- future configuration phase
- AP203 legacy support -- insufficient PMI content
- Tolerance stack-up analysis -- separate capability
