/**
 * Routes the moments add (not yet in the foundation's `R`). The coordinator can
 * promote these into `components/v4/routes.ts`.
 */
export const MOMENT_ROUTES = {
  /** Verify a phone before free checks (X2), with a waiting part. */
  phone: "/app/phone",
  /** Every banner and notice in one place (X11). */
  notices: "/app/notices",
} as const;
