# Phase 10: Image-to-Mesh Pipeline — UI Design Contract

**Generated:** 2026-04-15
**Mode:** auto (derived from CONTEXT.md decisions D-16 through D-18)

## Overview

New `/reconstruct` page under the dashboard with a 4-step wizard: Upload, Processing, Mesh Preview, Analysis Dashboard redirect. Reuses existing Three.js viewer and analysis result components.

## Route

- **Path:** `app/(dashboard)/reconstruct/page.tsx`
- **Nav label:** "Image to 3D" (sidebar, between "Analyze" and "History")
- **Icon:** Camera/image icon

## Components

### 1. ImageUploader

- **Location:** `app/(dashboard)/reconstruct/components/ImageUploader.tsx`
- **Behavior:** Drag-and-drop zone + file picker button. Accepts JPEG/PNG/WebP, max 20MB each, 1-4 images.
- **States:**
  - Empty: dashed border drop zone with camera icon and "Drop images here or click to upload"
  - Populated: grid of preview thumbnails (max 4) with remove button per image
  - Error: red border, error message below ("File too large", "Unsupported format", "Maximum 4 images")
- **Actions:** "Reconstruct" primary button (disabled until >= 1 image)
- **Validation:** Client-side: file type check, size check, count check

### 2. ReconstructionProgress

- **Location:** `app/(dashboard)/reconstruct/components/ReconstructionProgress.tsx`
- **Behavior:** Polls `GET /api/v1/jobs/{id}` every 3 seconds. Shows estimated time countdown.
- **States:**
  - Preprocessing: "Preparing image..." with spinner
  - Reconstructing: "Building 3D model..." with progress bar (estimated_seconds countdown)
  - Failed: Error message with "Retry" button
- **Transition:** On job status `done`, advance to MeshPreview step

### 3. MeshPreview

- **Location:** `app/(dashboard)/reconstruct/components/MeshPreview.tsx`
- **Behavior:** Displays reconstructed mesh in Three.js viewer (reuse existing MeshViewer component). Shows ConfidenceBadge overlay.
- **Layout:** Mesh viewer (70% width) + sidebar with confidence score, face count, "View Analysis" button
- **Auto-advance:** Analysis auto-fires on reconstruction completion. "View Analysis" button links to `/analyses/{analysis_id}`.

### 4. ConfidenceBadge

- **Location:** `app/(dashboard)/reconstruct/components/ConfidenceBadge.tsx`
- **Props:** `score: number`, `level: 'high' | 'medium' | 'low'`
- **Variants:**
  - High (>= 0.7): green background, "High Confidence" label
  - Medium (0.4-0.7): yellow/amber background, "Medium Confidence" label, warning text
  - Low (< 0.4): red background, "Low Confidence" label, prominent warning

## Page Flow (Wizard Steps)

```
Step 1: Upload ──────► Step 2: Processing ──────► Step 3: Preview ──────► Step 4: Analysis
(ImageUploader)        (ReconstructionProgress)    (MeshPreview)          (redirect to /analyses/{id})
```

State machine managed by React `useState` with step enum: `upload | processing | preview | complete`.

## API Integration

```typescript
// POST /api/v1/reconstruct → 202 { job_id, poll_url, estimated_seconds }
// GET /api/v1/jobs/{id} → { status, result: { reconstruction: {...}, analysis_id, analysis_url } }
// GET /api/v1/reconstructions/{id}/mesh.stl → binary STL
```

## Responsive Behavior

- Desktop: side-by-side mesh viewer + details panel
- Mobile: stacked layout (mesh viewer full-width above details)
- Upload area: full-width on all screens

## Accessibility

- Drop zone: keyboard accessible (Enter/Space to open file picker)
- Progress: `aria-live="polite"` for status updates
- Mesh viewer: "3D reconstruction preview" alt text for screen readers
- Confidence badge: color + text label (not color-only)

---

*UI-SPEC generated from CONTEXT.md decisions D-16, D-17, D-18*
