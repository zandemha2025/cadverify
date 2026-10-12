import posthog from "posthog-js";

export const ANALYTICS_CONSENT = "scalecad_analytics_consent";
export function analyticsAllowed(): boolean {
  try { return localStorage.getItem(ANALYTICS_CONSENT) === "yes" && navigator.doNotTrack !== "1"; }
  catch { return false; }
}

export function track(event: string, properties: Record<string, string | number | boolean> = {}) {
  if (posthog.__loaded && analyticsAllowed()) posthog.capture(event, properties);
}

export function identifyAccount(id: number) {
  if (posthog.__loaded && analyticsAllowed()) posthog.identify(`scalecad-user-${id}`);
}

export function signupMetadata() {
  const params = new URLSearchParams(window.location.search);
  let attribution: Record<string, string> = {};
  if (analyticsAllowed()) {
    try { attribution = JSON.parse(sessionStorage.getItem("scalecad_attribution") || "{}"); } catch { /* Storage is optional. */ }
  }
  return {
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    analytics_consent: analyticsAllowed(),
    utm_source: analyticsAllowed() ? (attribution.utm_source || params.get("utm_source") || "").slice(0, 100) : "",
    utm_medium: analyticsAllowed() ? (attribution.utm_medium || params.get("utm_medium") || "").slice(0, 100) : "",
    utm_campaign: analyticsAllowed() ? (attribution.utm_campaign || params.get("utm_campaign") || "").slice(0, 100) : "",
  };
}
