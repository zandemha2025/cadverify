"use client";

import * as React from "react";
import Script from "next/script";
import { usePathname } from "next/navigation";
import posthog from "posthog-js";
import { ANALYTICS_CONSENT, analyticsAllowed, track } from "@/lib/analytics";
import { cleanAnalyticsEvent, publicReplayAllowed, routeLabel } from "@/lib/analytics-privacy";
import { RB2B_SCRIPT, rb2bAllowed } from "@/lib/rb2b";

export function Analytics({ token, nonce }: { token: string; nonce?: string }) {
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

  const visitorTracking = ready && rb2bAllowed(
    typeof location === "undefined" ? "" : location.hostname, path,
    typeof location === "undefined" ? "" : location.search,
    typeof location === "undefined" ? "" : location.hash,
    choice === "yes" && analyticsAllowed(),
  );

  React.useEffect(() => {
    if (!visitorTracking) return;
    // RB2B has no documented stop API; fresh documents keep it out of app/auth pages.
    const navigate = (event: MouseEvent) => {
      const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(anchor instanceof HTMLAnchorElement) || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || anchor.target === "_blank" || anchor.hasAttribute("download")) return;
      const url = new URL(anchor.href);
      if (url.origin !== location.origin || (url.pathname === location.pathname && url.search === location.search && url.hash)) return;
      event.preventDefault();
      event.stopPropagation();
      location.assign(url.href);
    };
    const reload = () => location.reload();
    document.addEventListener("click", navigate, true);
    window.addEventListener("popstate", reload);
    return () => { document.removeEventListener("click", navigate, true); window.removeEventListener("popstate", reload); };
  }, [visitorTracking]);

  function choose(value: string) {
    try { localStorage.setItem(ANALYTICS_CONSENT, value); } catch { return; }
    setChoice(value);
    if (value !== "yes" && "reb2b" in window) location.reload();
  }
  if (!ready) return null;
  return <>
    {visitorTracking && <Script id="scalecad-rb2b" nonce={nonce} strategy="afterInteractive">{RB2B_SCRIPT}</Script>}
    <aside aria-label="Analytics preferences" data-private className="ph-no-capture fixed bottom-4 left-4 right-4 sm:right-auto z-50 max-w-sm rounded-xl border border-black/15 bg-white p-4 text-sm text-black shadow-lg">
    {choice === null ? <>
      <p>Allow analytics, masked public-page recordings and RB2B business visitor identification for sales follow-up? Passwords and CAD content are excluded. <a href="/privacy" className="underline">Privacy details</a></p>
      <div className="mt-3 flex gap-3"><button type="button" onClick={() => choose("yes")} className="rounded bg-black px-3 py-2 text-white">Allow analytics</button><button type="button" onClick={() => choose("no")} className="rounded border px-3 py-2">Decline</button></div>
    </> : <button type="button" onClick={() => setChoice(null)}>Analytics preferences</button>}
    </aside>
  </>;
}
