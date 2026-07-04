/**
 * Verify-UI gate — the single flag that mounts the product "light instrument"
 * verification surface (the founder-approved `Product - Verify` design, recreated
 * in the production stack and wired to the real engine).
 *
 * OFF by default. Flag-off, the `(verify)` route group's server layout calls
 * `notFound()` before rendering anything, so no new surface is reachable and the
 * existing app is byte-identical (this module adds no globals, no shared imports).
 *
 * `NEXT_PUBLIC_*` is inlined at build → a compile-time constant, identical on the
 * server and the first client paint.
 */
export const VERIFY_UI =
  process.env.NEXT_PUBLIC_VERIFY_UI === "1" ||
  process.env.NEXT_PUBLIC_VERIFY_UI === "true";
