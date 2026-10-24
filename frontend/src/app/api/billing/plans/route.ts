/** Same-origin read of the public plan facts (free allowances, Pro price) for client screens. */
import { backendUrl } from "@/lib/api-base";
import { FALLBACK_PLANS, parsePlans } from "@/lib/billing";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  try {
    const upstream = await fetch(backendUrl("/billing/plans"), { cache: "no-store", redirect: "error", signal: AbortSignal.timeout(8000) });
    if (!upstream.ok) return Response.json(FALLBACK_PLANS, { status: 200, headers: { "cache-control": "private, no-store", "x-plans-fallback": "1" } });
    return Response.json(parsePlans(await upstream.json()), { headers: { "cache-control": "private, max-age=60" } });
  } catch {
    return Response.json(FALLBACK_PLANS, { headers: { "cache-control": "private, no-store", "x-plans-fallback": "1" } });
  }
}
