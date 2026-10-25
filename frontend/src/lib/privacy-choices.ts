/**
 * Three separate privacy choices, each off until the person turns it on:
 *
 * - analytics: PostHog product analytics (page and button activity, text masked);
 * - recordings: PostHog session recordings of public pages (text and inputs masked);
 *   they need analytics, since PostHog records them;
 * - visitors: RB2B business visitor identification on public pages, for sales.
 *
 * Kept in this browser (localStorage). Browsers that send Do Not Track get none
 * of them, whatever is stored. Before these were separate (v2), one Allow/Decline
 * covered all three; a stored "yes" or "no" carries over as all on or all off,
 * since that is what the person chose.
 *
 * Pure apart from storage access (runs under node --test with a fake store).
 */

export type PrivacyChoices = { analytics: boolean; recordings: boolean; visitors: boolean };

export const CHOICES_KEY = "scalecad_privacy_choices_v3";
/** The bundled v2 choice ("yes" | "no"), read once to carry it over. */
export const LEGACY_KEY = "scalecad_analytics_consent_v2";
/** Fired on window after the choices change (same tab). */
export const CHOICES_EVENT = "scalecad:privacy-choices";

export const NONE: PrivacyChoices = { analytics: false, recordings: false, visitors: false };

type KV = Pick<Storage, "getItem" | "setItem">;

function store(): KV | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The stored choices, or null when the person hasn't chosen yet. */
export function readChoices(kv: KV | null = store()): PrivacyChoices | null {
  try {
    const raw = kv?.getItem(CHOICES_KEY);
    if (raw) {
      const v = JSON.parse(raw) as Partial<PrivacyChoices>;
      const analytics = v.analytics === true;
      return { analytics, recordings: analytics && v.recordings === true, visitors: v.visitors === true };
    }
    const legacy = kv?.getItem(LEGACY_KEY);
    if (legacy === "yes") return { analytics: true, recordings: true, visitors: true };
    if (legacy === "no") return { ...NONE };
  } catch {
    // Unreadable storage counts as no choice made: nothing loads.
  }
  return null;
}

export function saveChoices(next: PrivacyChoices, kv: KV | null = store()): PrivacyChoices {
  const clean = { analytics: next.analytics, recordings: next.analytics && next.recordings, visitors: next.visitors };
  try {
    kv?.setItem(CHOICES_KEY, JSON.stringify({ ...clean, at: new Date().toISOString() }));
    // Keep the old key in step for any tab still running the earlier page.
    kv?.setItem(LEGACY_KEY, clean.analytics && clean.recordings && clean.visitors ? "yes" : "no");
  } catch {
    // Private modes: the choice holds for this page only.
  }
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(CHOICES_EVENT, { detail: clean }));
  return clean;
}

function doNotTrack(): boolean {
  try {
    return typeof navigator !== "undefined" && navigator.doNotTrack === "1";
  } catch {
    return false;
  }
}

/** What may run now: the stored choices, all off under Do Not Track or before any choice. */
export function effectiveChoices(choices: PrivacyChoices | null = readChoices(), dnt = doNotTrack()): PrivacyChoices {
  if (!choices || dnt) return { ...NONE };
  return { analytics: choices.analytics, recordings: choices.analytics && choices.recordings, visitors: choices.visitors };
}

/** Which vendor must stop now that a choice was withdrawn (RB2B has no stop call: a reload). */
export function withdrawn(before: PrivacyChoices, after: PrivacyChoices): { stopAnalytics: boolean; stopRecordings: boolean; reload: boolean } {
  return {
    stopAnalytics: before.analytics && !after.analytics,
    stopRecordings: before.recordings && !after.recordings,
    reload: before.visitors && !after.visitors,
  };
}

/** One line for menus: "Analytics on · Recordings off · Visitor ID off". */
export function choicesSummary(c: PrivacyChoices | null): string {
  if (!c) return "Not chosen: all off";
  const w = (on: boolean) => (on ? "on" : "off");
  return `Analytics ${w(c.analytics)} · Recordings ${w(c.recordings)} · Visitor ID ${w(c.visitors)}`;
}

/** Pages where nothing loads and nothing is asked: supplier share pages (/s/...). */
export function trackingFreePath(path: string | null | undefined): boolean {
  return !!path && (path === "/s" || path.startsWith("/s/"));
}
