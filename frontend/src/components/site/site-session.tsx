import { headers } from "next/headers";
import { getUser } from "@/lib/dal";
import { getSessionToken } from "@/lib/session";
import { backendUrl } from "@/lib/api-base";
import { SiteSessionProvider, type SiteSession } from "./site-shell";

export async function SiteSessionBoundary({ children }: { children: React.ReactNode }) {
  const user = await getUser();
  let usage: SiteSession["usage"] = null;
  if (user) {
    try {
      const token = await getSessionToken();
      const res = await fetch(backendUrl("/auth/me/usage"), { headers: { Cookie: `dash_session=${token}` }, cache: "no-store", signal: AbortSignal.timeout(5000) });
      if (res.ok) {
        const data = await res.json();
        if (Number.isSafeInteger(data.cap) && data.cap >= 0 && Number.isSafeInteger(data.remaining) && data.remaining >= 0 && data.remaining <= data.cap) usage = { cap: data.cap, remaining: data.remaining };
      }
    } catch { /* Usage is optional; never invent an allowance during an outage. */ }
  }
  return <SiteSessionProvider value={{ user: user ? { email: user.email } : null, usage, siteKey: process.env.MAGIC_LINK_UI_ENABLED === "1" ? process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || process.env.TURNSTILE_SITE_KEY || "" : "", nonce: (await headers()).get("x-nonce") || undefined, ssoLoginPath: (process.env.SSO_LOGIN_PATH || "").trim() }}>{children}</SiteSessionProvider>;
}
