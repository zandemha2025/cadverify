/**
 * inspection-bind — PURE mapping from the richer Findings-API `Issue`
 * serialization to the shapes the Inspection experience renders. No React, no
 * DOM, no runtime imports (type-only, erased under `node --test` type
 * stripping), so it shares one implementation with the render layer and is
 * unit-tested directly.
 *
 * Every function binds ONLY to fields the backend actually serializes today
 * (`src/analysis/serialization.py::serialize_issue` / `serialize_citation`) and
 * preserves that serializer's honesty contract — nothing is invented:
 *
 *   1. `citationRef`         — the structured `{standard?, clause?, text?}`
 *      citation object promoted to a render-ready ref: a real STANDARD chip when
 *      `standard` is present, else the honest DESCRIPTOR text, else null.
 *   2. `affectedFacesSummary` — the TRUE affected-face count (`affected_face_count`,
 *      no longer clipped) plus an honest indicator when the sample was capped at
 *      the 2000 serializer limit (`affected_faces_truncated`).
 *   3. `costBlockerLocators`  — the cost-side DFM blockers' new structured Issue
 *      references (`CostEstimate.dfm_blocker_details`) flattened into the same
 *      locatable `IndexedIssue` shape the DFM panel already drives on the 3D
 *      stage — the backend relink surfaced client-side.
 */
import type { Issue, IssueCitation, CostEstimate } from "@/lib/api";
import type { IndexedIssue } from "@/lib/dfm-scope";

/* ------------------------------------------------------------------ */
/*  1 — structured citation → render-ready reference                   */
/* ------------------------------------------------------------------ */

/**
 * A citation ready to render. `kind: "standard"` is a real source (chip:
 * `standard` + optional `clause`); `kind: "descriptor"` is the honest fallback
 * where the analyzer's `cite=` string did not parse to a source, so only free
 * `text` survives — rendered as plain text, NEVER as a fake citation chip.
 */
export type CitationRef =
  | { kind: "standard"; standard: string; clause?: string; text?: string }
  | { kind: "descriptor"; text: string };

/**
 * Promote a serialized `Issue.citation` to a `CitationRef`, or null when the
 * issue is uncited (or the object carried nothing renderable).
 *
 * Honesty: a `standard` (present only when the backend parsed a real source)
 * makes it a chip; otherwise, if any `text` survives, it is a descriptor; an
 * empty/absent citation yields null — no empty chip masquerading as a source.
 */
export function citationRef(
  citation: IssueCitation | null | undefined
): CitationRef | null {
  if (!citation) return null;
  const standard = citation.standard?.trim();
  const clause = citation.clause?.trim();
  const text = citation.text?.trim();
  if (standard) {
    return {
      kind: "standard",
      standard,
      ...(clause ? { clause } : {}),
      ...(text ? { text } : {}),
    };
  }
  if (text) return { kind: "descriptor", text };
  return null;
}

/** Convenience: the citation ref for an Issue (or null). */
export function issueCitationRef(issue: Issue): CitationRef | null {
  return citationRef(issue.citation);
}

/** A one-line label for a standard chip: "AMS 4928 · §3.1" / "ISO 2768". */
export function citationChipLabel(ref: CitationRef): string {
  if (ref.kind !== "standard") return ref.text;
  return ref.clause ? `${ref.standard} · ${ref.clause}` : ref.standard;
}

/* ------------------------------------------------------------------ */
/*  2 — honest affected-faces summary                                  */
/* ------------------------------------------------------------------ */

export interface AffectedFacesSummary {
  /** TRUE total affected faces (the un-clipped `affected_face_count`). */
  count: number;
  /** how many indices actually rode in the sample (≤ 2000 cap). */
  sampleCount: number;
  /** the sample was capped by the serializer: shown < count. */
  truncated: boolean;
  /** short honest label, e.g. "47 faces" or "2,000 of 5,231 faces shown". */
  label: string;
}

/**
 * The honest affected-faces summary for an issue, or null when the issue has no
 * affected faces (a whole-part / unlocalizable finding — `affected_face_count`
 * absent). The label never lies: it states the TRUE total, and when the sample
 * was capped it says so with both the shown and the true numbers.
 */
export function affectedFacesSummary(issue: Issue): AffectedFacesSummary | null {
  const count = issue.affected_face_count;
  if (count == null || count <= 0) return null;
  const sampleCount = issue.affected_faces_sample?.length ?? 0;
  const truncated = issue.affected_faces_truncated === true;
  const n = count.toLocaleString();
  const label = truncated
    ? `${sampleCount.toLocaleString()} of ${n} faces shown`
    : `${n} face${count === 1 ? "" : "s"}`;
  return { count, sampleCount, truncated, label };
}

/** True when the finding is honestly unlocalizable (applies to the whole part). */
export function isWholePart(issue: Issue): boolean {
  return issue.scope === "whole_part";
}

/* ------------------------------------------------------------------ */
/*  3 — cost-blocker relink → locatable IndexedIssue rows              */
/* ------------------------------------------------------------------ */

/**
 * Flatten a cost estimate's structured DFM blockers
 * (`CostEstimate.dfm_blocker_details`, the backend relink) into the SAME
 * locatable `IndexedIssue` shape the DFM panel drives on the 3D stage — so a
 * cost-side blocker can be highlighted on the part, not merely restated as text.
 *
 * Dedup + face-union mirror `dfm-scope` (identity = `code|message`), and the
 * keys are namespaced by the estimate's process so a cost-view selection never
 * collides with an analysis-panel key. Returns [] when the report predates the
 * relink (no `dfm_blocker_details`).
 */
export function costBlockerLocators(estimate: CostEstimate): IndexedIssue[] {
  const details = estimate.dfm_blocker_details;
  if (!details || details.length === 0) return [];
  const proc = estimate.process || "cost";
  const seen = new Map<string, IndexedIssue>();
  details.forEach((issue, i) => {
    const id = `${issue.code}|${issue.message}`;
    const faces = issue.affected_faces_sample ?? [];
    const existing = seen.get(id);
    if (existing) {
      existing.faces = Array.from(new Set([...existing.faces, ...faces]));
    } else {
      seen.set(id, { key: `cost:${proc}#${i}`, issue, faces: [...faces] });
    }
  });
  return Array.from(seen.values());
}

/** Any cost-side blocker across a report's estimates carries a locatable ref. */
export function hasLocatableCostBlocker(estimates: readonly CostEstimate[]): boolean {
  return estimates.some((e) =>
    (e.dfm_blocker_details ?? []).some(
      (i) => (i.affected_faces_sample?.length ?? 0) > 0
    )
  );
}
