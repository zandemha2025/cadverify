/**
 * Verify-UI gate — the single flag that mounts the product "light instrument"
 * verification surface (the founder-approved `Product - Verify` design, recreated
 * in the production stack and wired to the real engine).
 *
 * ON by default now that the route is part of the product surface. Operators can
 * still set `NEXT_PUBLIC_VERIFY_UI=0` or `false` as an emergency kill switch;
 * flag-off, the `(verify)` route group's server layout calls `notFound()` before
 * rendering anything.
 *
 * `NEXT_PUBLIC_*` is inlined at build → a compile-time constant, identical on the
 * server and the first client paint.
 */
export const VERIFY_UI =
  process.env.NEXT_PUBLIC_VERIFY_UI !== "0" &&
  process.env.NEXT_PUBLIC_VERIFY_UI !== "false";
