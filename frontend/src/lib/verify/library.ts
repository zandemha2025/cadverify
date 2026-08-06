/**
 * Parts-master LIBRARY — the render-model for the org identity corpus (customer-
 * context Slice 2, the flywheel's cold start). Pure selectors/formatters only (no
 * React, no runtime imports) so they run under the repo's `node --test` type-
 * stripping runner, exactly like `lib/verify/identity`.
 *
 * Honesty (the whole point): the readout states EXACTLY what happened — parts
 * onboarded, how many are honestly UNNAMED (declared no name — never guessed), and
 * every skipped file with its reason. It invents nothing: `library_size` is the
 * backend's real corpus COUNT, and a skip is surfaced verbatim, never hidden.
 */

/** The onboard summary — verbatim from POST /identity/library/onboard. */
export interface OnboardSummary {
  onboarded: number;
  unnamed: number;
  skipped: { filename: string; reason: string }[];
  manifest_registered: number;
  library_size: number;
  mapping_errors: { line?: number; reason: string }[];
}

/** The library status — verbatim from GET /identity/library. */
export interface LibraryStatus {
  library_size: number;
  recent: {
    mesh_hash: string;
    declared_part_id: string | null;
    declared_name: string | null;
    program: string | null;
    source: string | null;
    provenance: string;
    confirmed: boolean;
    updated_at: string | null;
  }[];
}

/** Coerce an unknown API body into an OnboardSummary, or null if it isn't one. */
export function readOnboardSummary(body: unknown): OnboardSummary | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Partial<OnboardSummary>;
  if (typeof b.onboarded !== "number" || typeof b.library_size !== "number") return null;
  return {
    onboarded: b.onboarded,
    unnamed: typeof b.unnamed === "number" ? b.unnamed : 0,
    skipped: Array.isArray(b.skipped) ? b.skipped : [],
    manifest_registered: typeof b.manifest_registered === "number" ? b.manifest_registered : 0,
    library_size: b.library_size,
    mapping_errors: Array.isArray(b.mapping_errors) ? b.mapping_errors : [],
  };
}

/** The one-line headline: "Onboarded N parts · library now M". Honest — it reports
 *  the real counts, and appends the skipped count when any file was skipped so a
 *  partial batch is never silently rounded up to success. */
export function onboardReadout(s: OnboardSummary): string {
  const parts = `Onboarded ${s.onboarded} part${s.onboarded === 1 ? "" : "s"}`;
  const lib = `library now ${s.library_size}`;
  const tail: string[] = [];
  if (s.skipped.length > 0) {
    tail.push(`${s.skipped.length} skipped`);
  }
  if (s.unnamed > 0) {
    tail.push(`${s.unnamed} unnamed`);
  }
  const suffix = tail.length ? ` (${tail.join(" · ")})` : "";
  return `${parts} · ${lib}${suffix}`;
}

/** True when the batch did real work OR reported honest skips — i.e. there is
 *  something to show the user (never a fabricated "success" on an empty result). */
export function hasOnboardOutcome(s: OnboardSummary): boolean {
  return s.onboarded > 0 || s.skipped.length > 0 || s.mapping_errors.length > 0;
}
