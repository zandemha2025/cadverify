/**
 * Same-origin logout. Clears this browser's first-party httpOnly cookie and
 * best-effort notifies the backend. Account-wide revocation uses backend
 * session_version via /auth/logout-all or the admin revoke-sessions route.
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
  return NextResponse.json(
    { ok: true },
    { headers: { "cache-control": "no-store" } },
  );
}
