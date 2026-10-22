import posthog from "posthog-js";
import { LEGACY_KEY, effectiveChoices } from "./privacy-choices.ts";

/** The bundled v2 key; the three separate choices live in ./privacy-choices. */
export const ANALYTICS_CONSENT = LEGACY_KEY;
/** Dispatch on window to open the privacy choices (the footer's "Privacy choices", the account menu). */
export const ANALYTICS_PREFERENCES_EVENT = "scalecad:analytics-preferences";
/** Product analytics (PostHog) is allowed: chosen, and no Do Not Track. */
export function analyticsAllowed(): boolean {
  return effectiveChoices().analytics;
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
