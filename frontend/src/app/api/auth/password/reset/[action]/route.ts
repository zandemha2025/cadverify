import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { signedAuthProxyHeaders } from "@/lib/auth-proxy";
import { clearSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST(req: Request, { params }: { params: Promise<{ action: string }> }) {
  const { action } = await params;
  if (action !== "start" && action !== "complete") {
    return NextResponse.json({ detail: { message: "Unknown recovery action." } }, { status: 404 });
  }
  const body = await req.json().catch(() => ({}));
  const backendPath = `/auth/password/reset/${action}`;
  try {
    const response = await fetch(backendUrl(backendPath), {
      method: "POST",
      headers: { "content-type": "application/json", ...signedAuthProxyHeaders(req, backendPath) },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(55_000),
    });
    const data = await response.json().catch(() => ({}));
    const headers: Record<string, string> = { "cache-control": "no-store" };
    const retryAfter = response.headers.get("retry-after");
    if (retryAfter) headers["retry-after"] = retryAfter;
    if (response.ok && data?.ok !== true) {
      return NextResponse.json({ detail: { message: "Could not confirm password recovery." } }, { status: 502, headers });
    }
    if (response.ok && action === "complete") await clearSession();
    const message = response.status === 422
      ? "Check your email, security check, reset link and password requirements."
      : typeof data?.message === "string" ? data.message
      : typeof data?.detail?.message === "string" ? data.detail.message
      : typeof data?.detail === "string" ? data.detail
      : "Password recovery could not be completed. Try again or request a new link.";
    return NextResponse.json(response.ok ? { ok: true } : { detail: { message } }, { status: response.status, headers });
  } catch {
    return NextResponse.json({ detail: { message: "Password recovery is temporarily unavailable. Please try again." } }, { status: 503, headers: { "cache-control": "no-store" } });
  }
}
