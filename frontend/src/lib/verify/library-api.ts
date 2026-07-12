/**
 * Parts-master LIBRARY calls — POST /identity/library/onboard (bulk cold-start
 * onboarding) + GET /identity/library (corpus size) through the same-origin authed
 * proxy. Split from the pure `library.ts` (which stays import-free so its selectors
 * run under `node --test`) because this touches `fetch` + the API base — the same
 * split as `identity.ts` / `identity-api.ts`.
 *
 * Honest at the call site: a failure is RETURNED (never thrown from onboard) so the
 * panel can show a quiet error and keep the surface intact; the summary it returns
 * is the backend's real counts, never fabricated.
 */
import { API_BASE } from "@/lib/api-base";
import { readOnboardSummary, type OnboardSummary, type LibraryStatus } from "@/lib/verify/library";

export type OnboardResult =
  | { ok: true; summary: OnboardSummary; error: null }
  | { ok: false; summary: null; error: string };

/** POST a part library (CAD files + an optional identity mapping) to the onboarding
 *  feeder. The mapping is a CSV or JSON file binding each filename to its declared
 *  part_id/name/program/material_class. */
export async function onboardLibrary(
  files: File[],
  mapping: File | null
): Promise<OnboardResult> {
  const form = new FormData();
  for (const f of files) form.append("files", f, f.name);
  if (mapping) form.append("mapping", mapping, mapping.name);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/identity/library/onboard`, {
      method: "POST",
      body: form,
    });
  } catch (e) {
    return { ok: false, summary: null, error: e instanceof Error ? e.message : "Network error" };
  }
  if (res.ok) {
    const summary = readOnboardSummary(await res.json().catch(() => null));
    if (!summary) return { ok: false, summary: null, error: "Malformed onboard response" };
    return { ok: true, summary, error: null };
  }
  const body: Record<string, unknown> = await res.json().catch(() => ({}));
  const detail =
    (body.detail as string) || (body.message as string) || `Onboard failed (${res.status})`;
  return { ok: false, summary: null, error: typeof detail === "string" ? detail : JSON.stringify(detail) };
}

/** The org's current library size + a recent slice. Throws on failure (the caller
 *  renders a quiet "—"). */
export async function fetchLibrary(): Promise<LibraryStatus> {
  const res = await fetch(`${API_BASE}/identity/library`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = (body && (body.detail || body.message)) || `Request failed (${res.status})`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}
