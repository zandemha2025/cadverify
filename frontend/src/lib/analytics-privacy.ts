const PUBLIC_PAGES = new Set(["/", "/pricing", "/pilot", "/contact", "/company", "/about", "/method", "/platform", "/security", "/privacy", "/terms", "/developers", "/teams", "/for-in-house-manufacturing", "/for-shop-owners", "/for-sourcing", "/for-design-engineering", "/for-cost-engineering"]);
const ROUTES = new Set([...PUBLIC_PAGES].flatMap(p => p.split("/")) .concat(["api", "proxy", "auth", "login", "signup", "forgot-password", "reset-password", "verify", "analyze", "analyses", "cost", "cost-decisions", "catalog", "capability-investment", "batch", "history", "onboarding", "settings", "integrations", "notifications", "rfq-packages", "designs", "keys", "reconstruct", "s", "processes", "materials", "machines", "shops", "validate", "validate-quick", "me", "usage", "logout", "pilot-request"]));

export function routeLabel(path: string): string {
  return path.split("?")[0].split("#")[0].split("/").map(p => ROUTES.has(p) ? p : ":id").join("/");
}

export function publicReplayAllowed(path: string, search: string, hash: string): boolean {
  return PUBLIC_PAGES.has(path) && !search && !hash;
}

function cleanUrl(value: unknown, referrer = false): string {
  try {
    const url = new URL(String(value));
    return `${url.origin}${referrer ? "/" : routeLabel(url.pathname)}`;
  } catch { return ""; }
}

// Unknown properties are discarded, including DOM text, identifiers and request bodies.
const SAFE = new Set(["distinct_id", "$anon_distinct_id", "$device_id", "$session_id", "$window_id", "$insert_id", "$lib", "$lib_version", "$browser", "$browser_version", "$os", "$os_version", "$device_type", "$screen_height", "$screen_width", "$viewport_height", "$viewport_width", "$referring_domain", "$is_identified", "$pageview_id", "$prev_pageview_id", "$event_type", "$time", "$web_vitals_LCP_value", "$web_vitals_INP_value", "$web_vitals_CLS_value", "$web_vitals_FCP_value", "surface", "tool", "method", "status", "duration_ms", "error_code", "plan", "auth_provider", "utm_source", "utm_medium", "utm_campaign", "timezone", "$feature_flag", "$feature_flag_response"]);

export function cleanAnalyticsEvent<T extends { event: string; properties: Record<string, unknown> }>(event: T | null): T | null {
  if (!event) return null;
  if (event.event === "$snapshot") return event; // Public pages only; inputs/text/network are masked at capture.
  const properties: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(event.properties)) {
    if (SAFE.has(key) && (typeof value === "string" || typeof value === "number" || typeof value === "boolean")) properties[key] = value;
    else if (["$current_url", "$initial_current_url"].includes(key)) properties[key] = cleanUrl(value);
    else if (["$referrer", "$initial_referrer"].includes(key)) properties[key] = cleanUrl(value, true);
    else if (key === "$pathname") properties[key] = routeLabel(String(value));
  }
  // Heatmap coordinates are SDK-generated; preserve them only on public URLs.
  const heatmapUrl = properties.$current_url;
  if (event.properties.$heatmap_data && typeof heatmapUrl === "string") {
    try {
      const url = new URL(heatmapUrl);
      if (publicReplayAllowed(url.pathname, "", "")) properties.$heatmap_data = event.properties.$heatmap_data;
    } catch { /* Ignore invalid URLs. */ }
  }
  if (event.event === "$exception") {
    // Stack locations still group errors; free-text messages can contain customer CAD data.
    const errors = event.properties.$exception_list;
    if (Array.isArray(errors)) properties.$exception_list = errors.slice(0, 5).map(error => ({
      type: /^[A-Za-z]+Error$/.test(error?.type) ? error.type : "Error",
      value: "Application error (message redacted)",
      stacktrace: { frames: (Array.isArray(error?.stacktrace?.frames) ? error.stacktrace.frames : []).slice(0, 40).map((frame: { filename?: string; lineno?: number; colno?: number }) => ({
        filename: cleanUrl(frame.filename), lineno: frame.lineno, colno: frame.colno,
      })) },
    }));
  }
  return { ...event, properties };
}
