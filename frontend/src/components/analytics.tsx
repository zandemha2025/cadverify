"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import posthog from "posthog-js";
import { ANALYTICS_CONSENT, analyticsAllowed, track } from "@/lib/analytics";
import { cleanAnalyticsEvent, publicReplayAllowed, routeLabel } from "@/lib/analytics-privacy";

export function Analytics({ token }: { token: string }) {
  const path = usePathname();
  const [choice, setChoice] = React.useState<string | null>(null);
  const [ready, setReady] = React.useState(false);

  React.useEffect(() => {
    try { setChoice(localStorage.getItem(ANALYTICS_CONSENT)); } catch { setChoice("no"); }
    setReady(true);
  }, []);

  React.useEffect(() => {
    if (!token || !ready) return;
    if (choice !== "yes" || !analyticsAllowed()) {
      if (posthog.__loaded) { posthog.stopSessionRecording(); posthog.opt_out_capturing(); posthog.reset(); }
      window.dispatchEvent(new Event("scalecad-analytics-ready"));
      return;
    }
    if (!posthog.__loaded) posthog.init(token, {
      api_host: "https://us.i.posthog.com", ui_host: "https://us.posthog.com",
      defaults: "2026-05-30", person_profiles: "identified_only",
      capture_pageview: false, capture_pageleave: true,
      autocapture: { dom_event_allowlist: ["click"], element_allowlist: ["a", "button"] },
      mask_all_text: true, mask_all_element_attributes: true,
      respect_dnt: true, capture_exceptions: true, capture_heatmaps: false,
      capture_performance: { web_vitals: true },
      disable_session_recording: true, enable_recording_console_log: false,
      session_recording: {
        maskAllInputs: true, maskTextSelector: "*", maskAllElementAttributes: true,
        blockSelector: "form,input,textarea,select,canvas,[data-private]",
        captureCanvas: { recordCanvas: false }, recordCrossOriginIframes: false,
        recordHeaders: false, recordBody: false,
        maskCapturedNetworkRequestFn: () => null,
      },
      before_send: event => {
        if (event?.event === "$snapshot" && !publicReplayAllowed(location.pathname, location.search, location.hash)) return null;
        const cleaned = cleanAnalyticsEvent(event);
        if (cleaned && !publicReplayAllowed(location.pathname, location.search, location.hash)) delete cleaned.properties.$heatmap_data;
        return cleaned;
      },
    });
    posthog.opt_in_capturing({ captureEventName: false });
    const params = new URLSearchParams(location.search);
    const attribution = Object.fromEntries(["utm_source", "utm_medium", "utm_campaign"].map(key => [key, (params.get(key) || "").slice(0, 100)]));
    try {
      if (!sessionStorage.getItem("scalecad_attribution")) sessionStorage.setItem("scalecad_attribution", JSON.stringify(attribution));
      posthog.register_once(JSON.parse(sessionStorage.getItem("scalecad_attribution") || "{}"));
    } catch { /* Storage may be disabled. */ }
    window.dispatchEvent(new Event("scalecad-analytics-ready"));
  }, [choice, ready, token]);

  React.useEffect(() => {
    if (!posthog.__loaded || !analyticsAllowed()) return;
    const replay = publicReplayAllowed(path, location.search, location.hash);
    posthog.set_config({ capture_heatmaps: replay && ["/", "/pricing", "/pilot"].includes(path) });
    if (replay) posthog.startSessionRecording(); else posthog.stopSessionRecording();
    posthog.register({ surface: publicReplayAllowed(path, "", "") ? "site" : "app" });
    track("$pageview", { $current_url: `${location.origin}${routeLabel(path)}`, $pathname: routeLabel(path), surface: publicReplayAllowed(path, "", "") ? "site" : "app" });
    return () => {
      track("$pageleave", { $current_url: `${location.origin}${routeLabel(path)}`, $pathname: routeLabel(path), surface: publicReplayAllowed(path, "", "") ? "site" : "app" });
      posthog.stopSessionRecording();
    };
  }, [path, choice, ready]);

  function choose(value: string) {
    try { localStorage.setItem(ANALYTICS_CONSENT, value); } catch { return; }
    setChoice(value);
  }
  if (!token || !ready) return null;
  return <aside aria-label="Analytics preferences" data-private className="ph-no-capture fixed bottom-4 left-4 right-4 sm:right-auto z-50 max-w-sm rounded-xl border border-black/15 bg-white p-4 text-sm text-black shadow-lg">
    {choice === null ? <>
      <p>Allow analytics and masked recordings of public pages to help us improve ScaleCad? Passwords and CAD content are excluded. <a href="/privacy" className="underline">Privacy details</a></p>
      <div className="mt-3 flex gap-3"><button type="button" onClick={() => choose("yes")} className="rounded bg-black px-3 py-2 text-white">Allow analytics</button><button type="button" onClick={() => choose("no")} className="rounded border px-3 py-2">Decline</button></div>
    </> : <button type="button" onClick={() => setChoice(null)}>Analytics preferences</button>}
  </aside>;
}
