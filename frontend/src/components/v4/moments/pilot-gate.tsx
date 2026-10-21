"use client";

/**
 * Pilot gate (board X5): what a pilot-plan tool does, shown locked, with the
 * pilot plan and how to get it. Render it in place of the tool's screen when
 * the account isn't on the pilot plan. The server still enforces access (403
 * `paid_access_required`); this only says so up front.
 *
 * Props:
 * - `title`     the tool's name, used as the page title ("Fit in assembly").
 * - `slot`      label inside the locked preview box ("Part + assembly").
 * - `features`  three panels: `{ title, text, tone? }` (tone is a CSS colour for the swatch).
 * - `inputs`    facts under the panels (["Inputs: part + assembly", "STEP, STL, OBJ, 3MF"]).
 * - `tabs`, `tabsLabel`  the section's sibling tabs (TABS.make, "Make and fit"), optional.
 * - `illustration` optional node drawn in the locked box (defaults to a neutral sheet stack).
 * - `includes`  optional list for "Includes" (defaults to the pilot plan's tools).
 *
 * Helpers: `usePilotAccess()` reads the plan once ("loading" | "pilot" | "gated" | "unknown")
 * and returns `[access, gate]` where `gate()` flips to "gated" after a 403;
 * `isPaidAccessError(err)` spots that 403 in any error shape.
 */
import * as React from "react";
import Link from "next/link";
import { Content, PageHead, Sheet, World } from "../ui";
import "./moments.css";

export type PilotFeature = { title: string; text: string; tone?: string };

export const PILOT_PLAN_FACTS = "$7,500 · 4–6 weeks · up to 500 parts · one factory";

export const PILOT_INCLUDES = [
  "Fit in assembly",
  "Batch runs",
  "Assemblies",
  "File repair",
  "Design Studio",
  "Recalibration from real costs",
];

/** Where the pilot is requested and planned (public site pages). */
export const PILOT_HREF = { request: "/pilot#pilot", plan: "/pricing" } as const;

const LOCK = (
  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">
    <rect x="3" y="7" width="10" height="7" rx="1.6" stroke="currentColor" strokeWidth="1.5" />
    <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);

const STACK = (
  <svg width="150" height="120" viewBox="0 0 150 120" fill="none" aria-hidden="true">
    <rect x="34" y="14" width="82" height="96" rx="10" fill="#fff" stroke="rgba(20,24,31,.16)" strokeWidth="2" />
    <rect x="24" y="24" width="82" height="86" rx="10" fill="#fff" stroke="rgba(20,24,31,.2)" strokeWidth="2" />
    <rect x="14" y="34" width="82" height="76" rx="10" fill="#fff" stroke="rgba(20,24,31,.28)" strokeWidth="2" />
    <path d="M34 62h42M34 74h30M34 86h36" stroke="rgba(20,24,31,.2)" strokeWidth="4" strokeLinecap="round" />
  </svg>
);

const TONES = ["#FBE7E4", "#E8EEFB", "#ECEEF1"];

export function PilotGate({
  title,
  slot,
  features,
  inputs,
  tabs,
  tabsLabel,
  illustration,
  includes = PILOT_INCLUDES,
}: {
  title: string;
  slot: string;
  features: PilotFeature[];
  inputs: string[];
  tabs?: { label: string; href: string; count?: number }[];
  tabsLabel?: string;
  illustration?: React.ReactNode;
  includes?: string[];
}) {
  return (
    <div className="mo-x5" style={{ display: "contents" }}>
      <World label={title}>
        <PageHead title={title} meta={[<b key="p">Pilot plan</b>, "Your plan: single-part checks"]} tabs={tabs} tabsLabel={tabsLabel} />
        <Content>
          <div className="slot" role="img" aria-label={`${title}: locked on your plan`}>
            <span className="lab">{slot}</span>
            <span className="lock">
              {LOCK}Pilot
            </span>
            {illustration ?? STACK}
          </div>
          <div className="three">
            {features.map((f, i) => (
              <div key={f.title} className="panel">
                <i style={{ background: f.tone ?? TONES[i % TONES.length] }} aria-hidden="true" />
                <b>{f.title}</b>
                <span>{f.text}</span>
              </div>
            ))}
          </div>
          {inputs.length ? (
            <p className="pmeta">
              {inputs.map((x) => (
                <span key={x}>{x}</span>
              ))}
            </p>
          ) : null}
        </Content>
        <Sheet label="Get access">
          <div className="top">
            <h2 className="stitle">Pilot plan</h2>
            <p className="smeta">{PILOT_PLAN_FACTS}</p>
          </div>
          <div className="gh">
            <span>Includes</span>
            <span />
          </div>
          <div className="inc">
            {includes.map((x) => (
              <span key={x}>{x}</span>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, padding: 12, flexWrap: "wrap" }}>
            <Link className="btn ink" href={PILOT_HREF.request}>
              Request access
            </Link>
            <Link className="btn" href={PILOT_HREF.plan}>
              Plan pilot
            </Link>
          </div>
          <p style={{ margin: "0 12px 16px", color: "var(--ink3)", fontSize: 12.5 }}>Pro adds checks only. Pilot tools aren&apos;t included.</p>
        </Sheet>
      </World>
    </div>
  );
}

export type PilotAccess = "loading" | "pilot" | "gated" | "unknown";

/**
 * Whether this account has the pilot plan. The server enforces it; this only
 * decides whether to show the gate up front. An unreadable plan is "unknown":
 * render the tool and let the server answer for itself.
 */
export function usePilotAccess(): [PilotAccess, () => void] {
  const [access, setAccess] = React.useState<PilotAccess>("loading");
  React.useEffect(() => {
    let live = true;
    fetch("/api/auth/me/usage", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((u: { plan?: unknown } | null) => {
        if (!live) return;
        if (!u || typeof u.plan !== "string") setAccess("unknown");
        else setAccess(u.plan === "pilot" ? "pilot" : "gated");
      })
      .catch(() => live && setAccess("unknown"));
    return () => {
      live = false;
    };
  }, []);
  const gate = React.useCallback(() => setAccess("gated"), []);
  return [access, gate];
}

/** True for the server's pilot-plan refusal, whatever shape the error took on the way here. */
export function isPaidAccessError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const e = err as { code?: unknown; message?: unknown; detail?: { code?: unknown } };
  if (e.code === "paid_access_required" || e.detail?.code === "paid_access_required") return true;
  return typeof e.message === "string" && /paid_access_required|part of a pilot or Enterprise plan/i.test(e.message);
}
