/**
 * Same-origin logout. The dashboard token is stateless, so deleting only this
 * browser's cookie would leave a copied pre-logout cookie usable until expiry.
 * Revoke the user's current session version server-side before clearing the
 * first-party cookie. This invalidates every outstanding dashboard cookie for
 * the account, which is the safe behavior until sessions have independent IDs.
 */
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { clearSession, getSessionToken } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST() {
  const token = await getSessionToken();
  let revoked = token == null;
  try {
    if (token) {
      const response = await fetch(backendUrl("/auth/logout-all"), {
        method: "POST",
        headers: { cookie: `dash_session=${token}` },
        cache: "no-store",
      });
      // 401/403 means the captured token is already unusable, which satisfies
      // logout's security invariant. Other backend failures cannot claim that
      // replay was revoked, even though the local cookie is still removed.
      revoked = response.ok || response.status === 401 || response.status === 403;
    }
  } catch {
    revoked = false;
  }
  await clearSession();
  return NextResponse.json(
    revoked
      ? { ok: true, sessionsRevoked: true }
      : {
          detail: {
            message: "This browser signed out, but other copied sessions could not be revoked. Try again when the authentication service is available.",
          },
        },
    {
      status: revoked ? 200 : 503,
      headers: { "cache-control": "no-store" },
    },
  );
}
