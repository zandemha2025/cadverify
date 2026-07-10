/**
 * Stable identities for the app's hidden `<input type="file">` elements — the
 * ONE place that names each uploader so co-located inputs can never be confused
 * for one another.
 *
 * Why this exists (W7-1): the Calibration & truth screen mounts inside the
 * verify shell, so two hidden file inputs are co-located in the DOM — the
 * verify-part CAD uploader (first) and the ground-truth actuals-CSV importer
 * (second). Without distinct, queryable identities an import (drag target, a11y
 * tool, or automation) can land a CSV on the CAD uploader, which the engine
 * rejects with a confusing 400 "unsupported file type" from /validate/cost
 * instead of importing the quotes. Each input below carries a distinct id /
 * name / data-testid / aria-label so an import always reaches the right handler.
 *
 * Pure (no React/DOM) so the distinctness contract is unit-tested with
 * `node --test`.
 */

export interface FileInputIdentity {
  /** DOM id — unique per document. */
  readonly id: string;
  /** form field name. */
  readonly name: string;
  /** data-testid for automation/e2e targeting. */
  readonly testId: string;
  /** accessible label describing exactly what this uploader takes. */
  readonly ariaLabel: string;
}

/** The verify-part CAD uploader (STL/STEP/IGES) — the primary "Verify a part". */
export const VERIFY_PART_CAD_INPUT: FileInputIdentity = {
  id: "verify-part-cad-input",
  name: "verify-part-cad",
  testId: "verify-part-cad-input",
  ariaLabel: "Upload a CAD part to verify (STL, STEP or IGES)",
};

/** The ground-truth actuals-CSV importer on Calibration & truth. */
export const GROUND_TRUTH_CSV_INPUT: FileInputIdentity = {
  id: "ground-truth-actuals-csv-input",
  name: "ground-truth-actuals-csv",
  testId: "ground-truth-csv-input",
  ariaLabel: "Import ground-truth actuals CSV (send actuals back)",
};

/** All hidden file-input identities that may be co-located in the DOM. */
export const FILE_INPUT_IDENTITIES: readonly FileInputIdentity[] = [
  VERIFY_PART_CAD_INPUT,
  GROUND_TRUTH_CSV_INPUT,
];

/**
 * True when every identity field (id, name, testId, ariaLabel) is unique across
 * the given inputs — i.e. no two uploaders share any queryable handle, so an
 * import can never be routed to the wrong input.
 */
export function fileInputIdentitiesAreDistinct(
  identities: readonly FileInputIdentity[] = FILE_INPUT_IDENTITIES,
): boolean {
  const fields: (keyof FileInputIdentity)[] = ["id", "name", "testId", "ariaLabel"];
  for (const field of fields) {
    const seen = new Set<string>();
    for (const identity of identities) {
      const value = identity[field];
      if (seen.has(value)) return false;
      seen.add(value);
    }
  }
  return true;
}
