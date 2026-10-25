/**
 * The signed-in app's routes. The proxy sends a visitor without a session to
 * log in from any of them, and the privacy-choices panel doesn't open over
 * them on its own (the account menu or a public page's footer opens it).
 */
export const APP_ROUTES = [
  "/analyze",
  "/cost",
  "/cost-decisions",
  "/batch",
  "/history",
  "/integrations",
  "/notifications",
  "/rfq-packages",
  "/analyses",
  "/label",
  "/reconstruct",
  "/keys",
  "/settings",
  "/design-system",
  "/designs",
  "/onboarding",
  "/verify",
  "/app",
] as const;

/** Whether a pathname is one of the app's routes or below one. */
export function isAppPath(pathname: string | null | undefined): boolean {
  if (!pathname) return false;
  return APP_ROUTES.some((route) => pathname === route || pathname.startsWith(`${route}/`));
}
