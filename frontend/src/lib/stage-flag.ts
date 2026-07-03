/**
 * Stage-UI gate — the single flag that swaps the app onto the "staged hero"
 * register (D5 build brief). OFF by default; it does not flip on until FE-3.
 *
 * While off, every stage change is inert:
 *   - `globals.css` re-token only applies under `[data-stage]` on <html>, which
 *     the root layout emits ONLY when this is on (so flag-off is byte-identical);
 *   - the app-scope font swap only applies under `[data-stage-type]`, emitted by
 *     the authed-app layout on the same condition;
 *   - the cad-viewer lighting rig and PartWorkspace face-highlight hexes branch
 *     on this value at runtime and fall back to today's cool-graphite values.
 *
 * `NEXT_PUBLIC_*` is inlined at build → this is a compile-time constant, safe to
 * read on the server AND in client components with an identical first paint.
 */
export const STAGE_UI =
  process.env.NEXT_PUBLIC_STAGE_UI === "1" ||
  process.env.NEXT_PUBLIC_STAGE_UI === "true";
