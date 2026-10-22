/**
 * Whether this deployment serves its interactive API docs. A release serves
 * them only when the API is configured to (they are off by default), so the
 * app asks the API rather than assuming: `/docs` answers 200 when they are on.
 * Server-side only; a short timeout, and "off" when the API doesn't answer.
 */
import { backendUrl } from "./api-base";

export async function apiDocsServed(): Promise<boolean> {
  try {
    const res = await fetch(backendUrl("/docs"), { cache: "no-store", redirect: "manual", signal: AbortSignal.timeout(2500) });
    await res.body?.cancel().catch(() => undefined);
    return res.status === 200;
  } catch {
    return false;
  }
}
