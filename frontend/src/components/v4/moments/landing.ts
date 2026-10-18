/**
 * Where a signed-in person lands with v4 on (behind UI_V4 only; today's pages
 * keep /verify and /onboarding). Return paths still go through safeLocalPath.
 */
import { R } from "../routes.ts";
import { MOMENT_ROUTES } from "./routes.ts";

/** After sign-in, magic link and invite acceptance. */
export const V4_HOME = R.home;
/** After creating an account: Home with Get started open. */
export const V4_SIGNUP_HOME = `${R.home}?welcome=1`;
/** A part held on the sign-in screen waits here (phone check first when needed). */
export const V4_HELD_PART = MOMENT_ROUTES.phone;

/** Today's post-auth default (/verify) becomes Home; any other server path is kept. */
export function v4Landing(path: string): string {
  return path === "/verify" || path.startsWith("/verify?") || path.startsWith("/verify#") ? V4_HOME : path;
}

export const SUPPORT_MAILTO = "mailto:nazeem@scalecad.ai?subject=ScaleCAD%20sign-in%20help";
