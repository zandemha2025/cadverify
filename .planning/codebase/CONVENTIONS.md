# Coding Conventions

**Analysis Date:** 2026-04-15

## Naming Patterns

**Files:**
- TypeScript components: PascalCase (e.g., `FileDropZone.tsx`, `AnalysisDashboard.tsx`)
- TypeScript utilities: camelCase (e.g., `api.ts`)
- Python modules: snake_case (e.g., `base_analyzer.py`, `fix_suggester.py`)
- Test files: `test_*.py` prefix for Python (pytest convention)

**Functions:**
- TypeScript/JavaScript: camelCase (e.g., `validateFile`, `handleFileSelect`, `extractCitationTags`)
- Python: snake_case (e.g., `analyze_geometry`, `run_universal_checks`, `_parse_mesh`)
- Private/internal functions: Prefix with underscore (e.g., `_max_upload_bytes`, `_read_capped`, `_try_csg`)

**Variables:**
- camelCase in TypeScript (e.g., `isDragOver`, `selectedFile`, `isLoading`)
- snake_case in Python (e.g., `rule_pack`, `process_scores`, `overall_verdict`)

**Types:**
- TypeScript interfaces: PascalCase with `Props` suffix for component props (e.g., `FileDropZoneProps`, `AnalysisDashboardProps`)
- Python dataclasses: PascalCase (e.g., `Issue`, `ProcessScore`, `GeometryInfo`)
- Python Enums: UPPER_CASE values (e.g., `ProcessType.FDM`, `Severity.ERROR`)
- API response interfaces: PascalCase (e.g., `ValidationResult`, `GeometryInfo`, `ProcessScore`)

## Code Style

**Formatting:**
- TypeScript: Inferred from Next.js defaults (16.2.3)
- Python: Standard PEP 8 conventions observed
- Indentation: 2 spaces (TypeScript), 4 spaces (Python)

**Linting:**
- TypeScript: ESLint 9 with Next.js core-web-vitals and TypeScript configs
  - Config: `eslint.config.mjs` (flat config format, not legacy `.eslintrc`)
  - Enforces Next.js best practices and strict TypeScript
- Python: No explicit linter configured; code follows standard Python conventions

**Strict Mode:**
- TypeScript: `strict: true` in `tsconfig.json`
  - All types explicitly declared
  - No implicit `any`
  - Null checks enforced

## Import Organization

**Order (TypeScript):**
1. React/Next.js imports (`import { useState } from "react"`)
2. Next.js utilities (`import dynamic from "next/dynamic"`)
3. Component imports (relative, from `@/components/*`)
4. Type imports (`import type { ValidationResult }`)
5. Utility imports (`import { validateFile }`)

**Example from `src/app/page.tsx`:**
```typescript
"use client";

import { useState, useCallback } from "react";
import dynamic from "next/dynamic";
import FileDropZone from "@/components/FileDropZone";
import AnalysisDashboard from "@/components/AnalysisDashboard";
import { validateFile, type ValidationResult } from "@/lib/api";
```

**Path Aliases:**
- `@/*` → `./src/*` (defined in `tsconfig.json`)
- Always use `@/` prefix for imports within `src/`

**Order (Python):**
1. Standard library (`import os`, `from pathlib import Path`)
2. Third-party (`import trimesh`, `from fastapi import FastAPI`)
3. Local imports (`from src.analysis.models import Issue`)
4. Future annotations (`from __future__ import annotations`) at very top when needed

## Error Handling

**TypeScript:**
- Errors caught and converted to user-facing messages
- Example from `src/app/page.tsx`:
  ```typescript
  try {
    const data = await validateFile(selectedFile, undefined, selectedRulePack ?? undefined);
    setResult(data);
  } catch (err) {
    setError(err instanceof Error ? err.message : "Analysis failed");
  }
  ```
- Promise errors handled with `.catch()` in API calls
  ```typescript
  const err = await res.json().catch(() => ({ detail: res.statusText }));
  throw new Error(err.detail || "Validation failed");
  ```

**Python:**
- HTTPException for API errors with descriptive messages
  - Example: `raise HTTPException(status_code=400, detail="...")`
- ValueError for parsing errors (safe to expose in routes)
- Generic Exception caught and logged, then generic error response
  ```python
  except Exception:
      logger.exception("Mesh parsing failed for %s", filename)
      raise HTTPException(status_code=400, detail="Failed to parse mesh file")
  ```

## Logging

**Framework:** Python uses standard `logging` module

**Patterns:**
- Logger instantiation: `logger = logging.getLogger(__name__)` or with specific name
- Log level configuration via `LOG_LEVEL` env var (default: `INFO`)
- Format: `"%(asctime)s %(levelname)s %(name)s %(message)s"`
- Example from `main.py`:
  ```python
  logging.basicConfig(
      level=getattr(logging, LOG_LEVEL, logging.INFO),
      format="%(asctime)s %(levelname)s %(name)s %(message)s",
  )
  logger = logging.getLogger("cadverify")
  ```
- Use `logger.info()`, `logger.exception()` for errors
- No logging in TypeScript (frontend) — use browser console

## Comments

**When to Comment:**
- Complex algorithms or non-obvious logic
- Section headers with visual separators (seen in Python code):
  ```python
  # ──────────────────────────────────────────────────────────────
  # Upload handling
  # ──────────────────────────────────────────────────────────────
  ```
- Explain "why" not "what" (code shows what, comments show why)
- Edge case handling and workarounds

**JSDoc/TSDoc:**
- TypeScript: Function-level comments rare; TypeScript types are self-documenting
- Python: Docstrings used for modules and complex functions
  - Example from `src/api/routes.py`:
    ```python
    def _read_capped(file: UploadFile) -> bytes:
        """Stream-read the upload, rejecting anything over MAX_UPLOAD_MB."""
    ```
  - Module-level docstrings: `"""Description of module purpose."""`

## Function Design

**Size:** Prefer small, focused functions
- Example: `_parse_mesh()` handles file suffix detection and parser selection
- Example: `_resolve_target_processes()` handles query parameter parsing

**Parameters:**
- Explicit over implicit
- Type hints required in TypeScript and Python
- Optional parameters use `Optional[Type] = None` pattern

**Return Values:**
- Explicitly typed
- Python uses dataclass instances for structured returns (e.g., `GeometryInfo`)
- TypeScript uses interfaces for structured returns (e.g., `ValidationResult`)

## Module Design

**Exports:**
- TypeScript components: Default export of the component function
  ```typescript
  export default function FileDropZone({ ... }: FileDropZoneProps) { ... }
  ```
- TypeScript utilities: Named exports for types and functions
  ```typescript
  export interface GeometryInfo { ... }
  export async function validateFile(...): Promise<ValidationResult> { ... }
  ```
- Python: Module imports via absolute paths from project root
  ```python
  from src.analysis.models import Issue, Severity
  from src.api.routes import router
  ```

**Barrel Files:**
- `src/lib/api.ts` exports all API interfaces and functions
- `src/analysis/models.py` exports all data model classes
- Not used extensively; mostly direct imports

**Organization:**
- Features grouped by domain (e.g., `additive_analyzer.py`, `cnc_analyzer.py`, `molding_analyzer.py`)
- Shared utilities in `base_analyzer.py`, `context.py`
- API routes centralized in `src/api/routes.py`

---

*Convention analysis: 2026-04-15*
