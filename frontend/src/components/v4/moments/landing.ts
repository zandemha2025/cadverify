/**
 * Where a signed-in person lands with v4 on (behind UI_V4 only; today's pages
 * keep /verify and /onboarding). Return paths still go through safeLocalPath.
 */
import { R } from "../routes.ts";
import { MOMENT_ROUTES } from "./routes.ts";

/** After sign-in, magic link and invite acceptance. */
export const V4_HOME = R.home;
/** After creating an account: Home, which before any part shows the three ways to a first check itself (N5). */
export const V4_SIGNUP_HOME = R.home;
/** A part held on the sign-in screen waits here (phone check first when needed). */
export const V4_HELD_PART = MOMENT_ROUTES.phone;

/**
 * Where a new account goes once it exists: the phone check when sign-up sent a
 * code (or tried to), or when a part is waiting (it checks from there); else `next`.
 */
export function afterSignup({ next, phone, held }: { next: string; phone: "sent" | "failed" | null; held: boolean }): string {
  if (!phone && !held) return next;
  return next && next !== V4_HELD_PART ? `${V4_HELD_PART}?next=${encodeURIComponent(next)}` : V4_HELD_PART;
}

/** Today's post-auth default (/verify) becomes Home; any other server path is kept. */
export function v4Landing(path: string): string {
  return path === "/verify" || path.startsWith("/verify?") || path.startsWith("/verify#") ? V4_HOME : path;
}

export const SUPPORT_MAILTO = "mailto:nazeem@scalecad.ai?subject=ScaleCAD%20sign-in%20help";
