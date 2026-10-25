/**
 * Where a part's cost breakdown lives: under the part, /app/part/{key}/cost,
 * beside its history. `?tab=` names the tab (summary | lines | compare |
 * history; the older decision, glass, routing and dfm still open the same
 * view) and deep-link extras ride along (proc, q, decision).
 *
 * The cost breakdown used to sit at /app/make/workbench?part={key}. That
 * address still works: it redirects here with every other parameter kept, so
 * old links, bookmarks and their ?tab= values open the same view.
 *
 * Pure: no React, no fetch (runs under node --test).
 */
import { R } from "../routes.ts";

/** Internal tab ids. "routing" is the old DFM tab: it now opens the part page's problem list. */
export type WbTab = "decision" | "routing" | "glass" | "compare" | "history";

/** What a tab is called in the address bar. Older names (decision, glass, routing) still open the same view. */
const URL_NAME: Record<WbTab, string> = { decision: "summary", routing: "dfm", glass: "lines", compare: "compare", history: "history" };
const FROM_URL: Record<string, WbTab> = { summary: "decision", decision: "decision", lines: "glass", glass: "glass", dfm: "routing", routing: "routing", compare: "compare", history: "history" };

/** The tab a `?tab=` value names (current or older spelling), or null. */
export function tabOf(v: string | null | undefined): WbTab | null {
  return v ? FROM_URL[v] ?? null : null;
}

export function tabUrlName(tab: WbTab): string {
  return URL_NAME[tab];
}

/** A part's cost breakdown URL. Extra params (proc, q, decision) ride along for deep links. */
export function wbHref(tab: WbTab | null, part: string, extra?: Record<string, string | number | null | undefined>): string {
  const p = new URLSearchParams();
  if (tab) p.set("tab", URL_NAME[tab]);
  for (const [k, v] of Object.entries(extra ?? {})) if (v != null && v !== "" && k !== "tab" && k !== "part") p.set(k, String(v));
  const qs = p.toString();
  return qs ? `${R.cost(part)}?${qs}` : R.cost(part);
}

/** The cost breakdown's old address. */
export const LEGACY_WORKBENCH = "/app/make/workbench";

/**
 * Where an old /app/make/workbench address goes: with `?part=`, that part's
 * cost breakdown with every other parameter as it was (tab, decision, proc,
 * q, issue…); without one, null (the page there decides).
 */
export function legacyWorkbenchTarget(search: URLSearchParams | Record<string, string | string[] | undefined>): string | null {
  const sp = search instanceof URLSearchParams ? search : toParams(search);
  const part = sp.get("part")?.trim();
  if (!part) return null;
  const rest = new URLSearchParams();
  sp.forEach((v, k) => {
    if (k !== "part") rest.append(k, v);
  });
  const qs = rest.toString();
  return qs ? `${R.cost(part)}?${qs}` : R.cost(part);
}

function toParams(o: Record<string, string | string[] | undefined>): URLSearchParams {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) {
    if (v == null) continue;
    for (const x of Array.isArray(v) ? v : [v]) sp.append(k, x);
  }
  return sp;
}
