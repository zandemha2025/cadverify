
export const SITE_TAGLINE = "Make the decision. Keep the evidence.";
export const PILOT_HREF = "/pilot";
export const UPLOAD_HREF = "/login?next=/verify";
// "Try free" opens Create account: the password form where public sign-up is
// on, else the one-time email link (the sign-up page says which).
export const SIGNUP_HREF = "/signup";
/** Create account, then go on to `next` (a local app path). */
export function signupHref(next?: string): string {
  return next ? `${SIGNUP_HREF}?next=${encodeURIComponent(next)}` : SIGNUP_HREF;
}
export const APP_HOME_HREF = "/verify";
export const SITE_NAV = [
  { href: "/teams", label: "Workflows" },
  { href: "/method", label: "How it works" },
  { href: "/platform", label: "Platform" },
  { href: "/pricing", label: "Pricing" },
  { href: "/security", label: "Security" },
];

export const PILOT_WORKFLOWS = ["In-house manufacturing", "Design engineering", "Cost engineering", "Sourcing", "Shop owners", "Deployment or integration"];
