/**
 * Same-origin logout. Clears the first-party httpOnly cookie (the authoritative
 * action — the session is a stateless HMAC token, nothing to revoke server-side)
 * and best-effort notifies the backend.
 */
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { clearSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST() {
  await clearSession();
  try {
    await fetch(backendUrl("/auth/logout"), { method: "POST", cache: "no-store" });
  } catch {
    // best-effort; the first-party cookie is already cleared
  }
  return NextResponse.json({ ok: true });
}
