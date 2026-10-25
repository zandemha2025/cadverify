/** Where a sign-in that still owes a two-step code goes, keeping its landing page. */
export const TWO_STEP_PATH = "/login/two-step";

export function twoStepHref(next: string | null | undefined): string {
  return next ? `${TWO_STEP_PATH}?next=${encodeURIComponent(next)}` : TWO_STEP_PATH;
}
