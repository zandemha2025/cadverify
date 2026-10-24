"use client";

import * as React from "react";
import Script from "next/script";
import { usePathname } from "next/navigation";
import posthog from "posthog-js";
import { ANALYTICS_PREFERENCES_EVENT, track } from "@/lib/analytics";
import { cleanAnalyticsEvent, publicReplayAllowed, routeLabel } from "@/lib/analytics-privacy";
import {
  CHOICES_EVENT,
  CHOICES_KEY,
  LEGACY_KEY,
  NONE,
  effectiveChoices,
  readChoices,
  saveChoices,
  trackingFreePath,
  withdrawn,
  type PrivacyChoices,
} from "@/lib/privacy-choices";
import { RB2B_SCRIPT, rb2bAllowed } from "@/lib/rb2b";
import { isAppPath } from "@/lib/app-routes";

/**
 * Three separate choices (see lib/privacy-choices): product analytics and
 * session recordings (PostHog), and business visitor identification (RB2B).
 * All off until chosen. The first visit to a public page asks; "Privacy
 * choices" in the site footer or the account menu reopens the same panel,
 * showing what is on now. Supplier share pages (/s/...) load nothing and ask
 * nothing: the supplier isn't ScaleCAD's visitor.
 */
export function Analytics({ token, nonce }: { token: string; nonce?: string }) {
  const path = usePathname();
  const [choices, setChoices] = React.useState<PrivacyChoices | null>(null);
  const [ready, setReady] = React.useState(false);
  const [asked, setAsked] = React.useState(false);
  const free = trackingFreePath(path);
  const on = free ? NONE : effectiveChoices(choices);

  React.useEffect(() => {
    setChoices(readChoices());
    setReady(true);
    const reread = () => setChoices(readChoices());
    const fromStorage = (e: StorageEvent) => {
      if (e.key === CHOICES_KEY || e.key === LEGACY_KEY) reread();
    };
    window.addEventListener(CHOICES_EVENT, reread);
    window.addEventListener("storage", fromStorage);
    return () => {
      window.removeEventListener(CHOICES_EVENT, reread);
      window.removeEventListener("storage", fromStorage);
    };
  }, []);

  React.useEffect(() => {
    if (!token || !ready) return;
    if (!on.analytics) {
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
        if (trackingFreePath(location.pathname)) return null;
        if (event?.event === "$snapshot" && (!effectiveChoices().recordings || !publicReplayAllowed(location.pathname, location.search, location.hash))) return null;
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
  }, [on.analytics, ready, token]);

  React.useEffect(() => {
    if (!posthog.__loaded || !on.analytics) return;
    const replay = publicReplayAllowed(path, location.search, location.hash);
    posthog.set_config({ capture_heatmaps: replay && ["/", "/pricing", "/pilot"].includes(path) });
    if (replay && on.recordings) posthog.startSessionRecording(); else posthog.stopSessionRecording();
    posthog.register({ surface: publicReplayAllowed(path, "", "") ? "site" : "app" });
    track("$pageview", { $current_url: `${location.origin}${routeLabel(path)}`, $pathname: routeLabel(path), surface: publicReplayAllowed(path, "", "") ? "site" : "app" });
    return () => {
      track("$pageleave", { $current_url: `${location.origin}${routeLabel(path)}`, $pathname: routeLabel(path), surface: publicReplayAllowed(path, "", "") ? "site" : "app" });
      posthog.stopSessionRecording();
    };
  }, [path, on.analytics, on.recordings, ready]);

  const visitorTracking = ready && !free && rb2bAllowed(
    typeof location === "undefined" ? "" : location.hostname, path,
    typeof location === "undefined" ? "" : location.search,
    typeof location === "undefined" ? "" : location.hash,
    on.visitors,
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

  // "Privacy choices" in the footer or the account menu opens the panel with what is on now.
  React.useEffect(() => {
    const ask = () => setAsked(true);
    window.addEventListener(ANALYTICS_PREFERENCES_EVENT, ask);
    return () => window.removeEventListener(ANALYTICS_PREFERENCES_EVENT, ask);
  }, []);

  function choose(next: PrivacyChoices) {
    const before = effectiveChoices(choices);
    const saved = saveChoices(next);
    setChoices(saved);
    setAsked(false);
    const stop = withdrawn(before, effectiveChoices(saved));
    // Withdrawn choices stop at once: PostHog in place, RB2B (no stop call) by a reload.
    if (stop.stopRecordings && posthog.__loaded) posthog.stopSessionRecording();
    if (stop.reload && "reb2b" in window) location.reload();
  }

  if (!ready || free) return null;
  // Inside the app nothing floats over the work unless asked (account menu, Privacy choices):
  // every signed-in route, the v4 app under /app and the Verify app's pages alike.
  const inApp = isAppPath(path);
  const show = asked || (choices === null && !inApp);
  return <>
    {visitorTracking && <Script id="scalecad-rb2b" nonce={nonce} strategy="afterInteractive">{RB2B_SCRIPT}</Script>}
    {show ? <ChoicesPanel current={choices} first={choices === null} onSave={choose} onClose={asked ? () => setAsked(false) : null} /> : null}
  </>;
}

const ROWS: { key: keyof PrivacyChoices; title: string; what: string }[] = [
  { key: "analytics", title: "Product analytics (PostHog)", what: "Counts pages and button clicks, with all text masked. Never your files, file names or passwords." },
  { key: "recordings", title: "Session recordings (PostHog)", what: "Records public website pages with all text and form fields masked. Never inside the app." },
  { key: "visitors", title: "Business visitor identification (RB2B)", what: "Tells ScaleCAD’s sales team which company visited the public website. Never inside the app." },
];

function ChoicesPanel({ current, first, onSave, onClose }: { current: PrivacyChoices | null; first: boolean; onSave: (c: PrivacyChoices) => void; onClose: (() => void) | null }) {
  const [draft, setDraft] = React.useState<PrivacyChoices>(current ?? NONE);
  const id = React.useId();
  return (
    <aside aria-labelledby={`${id}-t`} data-private className="ph-no-capture fixed bottom-3 left-3 right-3 sm:right-auto z-50 max-w-md max-h-[calc(100dvh-24px)] overflow-auto rounded-xl border border-black/15 bg-white px-3.5 py-3 text-[13px] leading-snug text-black shadow-lg">
      <p id={`${id}-t`} className="font-semibold">Privacy choices</p>
      <p className="mt-0.5 text-black/65">{first ? "Each is off until you turn it on. Your files and passwords are never included." : "What this browser allows now. Change any of them."}</p>
      <div className="mt-2 flex flex-col gap-2">
        {ROWS.map((r) => {
          const needs = r.key === "recordings" && !draft.analytics;
          return (
            <label key={r.key} className={`flex gap-2 items-start ${needs ? "opacity-60" : ""}`}>
              <input
                type="checkbox"
                className="mt-0.5"
                checked={draft[r.key] && !needs}
                disabled={needs}
                onChange={(e) => setDraft((d) => ({ ...d, [r.key]: e.target.checked }))}
              />
              <span>
                <b className="font-medium">{r.title}</b>
                <span className="block text-black/65">{needs ? "Needs product analytics." : r.what}</span>
              </span>
            </label>
          );
        })}
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => onSave(draft)} className="rounded bg-black px-3 py-1.5 text-white">Save choices</button>
        {first ? (
          <button type="button" onClick={() => onSave(NONE)} className="rounded border px-3 py-1.5">Decline all</button>
        ) : onClose ? (
          <button type="button" onClick={onClose} className="rounded border px-3 py-1.5">Cancel</button>
        ) : null}
        <a href="/privacy#analytics" className="underline">Details</a>
      </div>
    </aside>
  );
}
