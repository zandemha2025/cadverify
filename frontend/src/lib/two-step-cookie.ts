/**
 * The two-step sign-in challenge cookie (SERVER ONLY).
 *
 * After a correct password, email link or Google sign-in, an account that owes
 * an authenticator code gets a short-lived signed challenge from the backend
 * instead of a session. The Next server keeps it in this httpOnly cookie (never
 * readable by browser JavaScript) and posts it back with the code.
 */
import { cookies } from "next/headers";

export const TWO_STEP_COOKIE = "cv_two_step";
const TEN_MINUTES = 10 * 60;

export function isChallenge(value: unknown): value is string {
  return typeof value === "string" && value.startsWith("ts1.") && value.length >= 16 && value.length <= 1024;
}

export type TwoStepPurpose = "verify" | "setup";

export function isPurpose(value: unknown): value is TwoStepPurpose {
  return value === "verify" || value === "setup";
}

export async function setTwoStepChallenge(token: string): Promise<void> {
  (await cookies()).set(TWO_STEP_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: TEN_MINUTES,
  });
}

export async function getTwoStepChallenge(): Promise<string | null> {
  const value = (await cookies()).get(TWO_STEP_COOKIE)?.value ?? null;
  return isChallenge(value) ? value : null;
}

export async function clearTwoStepChallenge(): Promise<void> {
  (await cookies()).delete(TWO_STEP_COOKIE);
}
