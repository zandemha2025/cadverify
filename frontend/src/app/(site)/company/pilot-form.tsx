"use client";

/**
 * The pilot request form on /company#pilot. Page-local (NOT foundation).
 *
 * Ported faithfully from handoff_cadverify_2026-07-04/site/Company.dc.html: work
 * email, company, "what do you make?", deployment preference, and the Send
 * pill. Submission is server-side and returns a durable receipt; direct email
 * remains a visible fallback, never the primary transport.
 */

import * as React from "react";
import { TurnstileWidget } from "@/components/auth/turnstile-widget";
import styles from "./company.module.css";

function errorMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object") {
    const value = data as { detail?: { message?: string }; message?: string };
    return value.detail?.message ?? value.message ?? fallback;
  }
  return fallback;
}

export function PilotForm() {
  const [siteKey, setSiteKey] = React.useState<string | null>(null);
  const [securityReady, setSecurityReady] = React.useState(false);
  const [turnstileToken, setTurnstileToken] = React.useState<string | null>(null);
  const [turnstileReset, setTurnstileReset] = React.useState(0);
  const [nonce, setNonce] = React.useState<string | undefined>();
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [receipt, setReceipt] = React.useState<string | null>(null);
  const requestId = React.useRef<string | null>(null);

  React.useEffect(() => {
    setNonce(document.querySelector<HTMLScriptElement>("script[nonce]")?.nonce || undefined);
    const controller = new AbortController();
    fetch("/api/pilot/request", { cache: "no-store", signal: controller.signal })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(errorMessage(data, "Security check unavailable."));
        const key = typeof data.turnstileSiteKey === "string" ? data.turnstileSiteKey : null;
        setSiteKey(key);
        setSecurityReady(true);
      })
      .catch((cause) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof Error ? cause.message : "Security check unavailable.");
      });
    return () => controller.abort();
  }, []);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!securityReady) {
      setError("Online intake is still loading. Please try again in a moment.");
      return;
    }
    if (siteKey && !turnstileToken) {
      setError("Complete the security check first.");
      return;
    }
    const formElement = e.currentTarget;
    const form = new FormData(formElement);
    const email = String(form.get("email") || "").trim();
    const company = String(form.get("company") || "").trim();
    const what = String(form.get("what") || "").trim();
    const deployment = String(form.get("deployment") || "undecided");
    const website = String(form.get("website") || "");
    requestId.current ||= crypto.randomUUID();
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/api/pilot/request", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          requestId: requestId.current,
          email,
          company,
          what,
          deployment,
          turnstileToken,
          website,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || typeof data.receipt !== "string") {
        setError(errorMessage(data, "Could not send the request. Please try again."));
        if (siteKey) setTurnstileReset((value) => value + 1);
        return;
      }
      setReceipt(data.receipt);
      formElement.reset();
      requestId.current = null;
    } catch {
      setError("Could not reach online intake. Please try again or email us directly.");
      if (siteKey) setTurnstileReset((value) => value + 1);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      className={styles.formCard}
      onSubmit={onSubmit}
      aria-label="Request a pilot"
    >
      <p style={{ margin: 0, fontSize: 19, fontWeight: 400 }}>Request a pilot</p>
      <p style={{ margin: "8px 0 0", fontSize: 13.5, fontWeight: 300, color: "rgba(245,245,247,0.5)" }}>
        We reply within two business days. Security teams welcome from day one.
      </p>
      {receipt ? (
        <div role="status" style={{ marginTop: 24, border: "1px solid rgba(85,184,128,0.42)", borderRadius: 12, padding: "18px 20px", background: "rgba(85,184,128,0.07)" }}>
          <p style={{ margin: 0, color: "#71cf99", fontSize: 15, fontWeight: 500 }}>Request received and recorded.</p>
          <p style={{ margin: "8px 0 0", color: "rgba(245,245,247,0.65)", fontSize: 13, lineHeight: 1.55 }}>
            We&apos;ll reply within two business days. Keep this receipt if you contact us about the request.
          </p>
          <p className="st-mono" style={{ margin: "10px 0 0", color: "rgba(245,245,247,0.84)", fontSize: 11, overflowWrap: "anywhere" }}>
            CV-{receipt}
          </p>
        </div>
      ) : <>
      <div className={styles.formGrid}>
        <label className={styles.fieldLabel}>
          <span>Work email</span>
          <input
            className={styles.pilotInput}
            name="email"
            type="email"
            placeholder="you@company.com"
            autoComplete="email"
            required
          />
        </label>
        <label className={styles.fieldLabel}>
          <span>Company</span>
          <input
            className={styles.pilotInput}
            name="company"
            placeholder="Company name"
            autoComplete="organization"
            required
          />
        </label>
        <label className={`${styles.fieldLabel} ${styles.formGridWide}`}>
          <span>What do you make?</span>
          <textarea
            className={styles.pilotInput}
            name="what"
            placeholder="Parts, programs, materials, or supplier flow"
            rows={3}
            maxLength={2000}
            required
            style={{ resize: "vertical", minHeight: 92 }}
          />
        </label>
        <label className={`${styles.fieldLabel} ${styles.formGridWide}`}>
          <span>Deployment preference</span>
          <select className={styles.pilotInput} name="deployment" defaultValue="undecided">
            <option value="undecided">Not sure yet</option>
            <option value="cloud">Commercial cloud SaaS</option>
            <option value="vpc">Private VPC / customer cloud</option>
            <option value="air-gapped">Air-gapped / regulated environment</option>
          </select>
        </label>
        <label aria-hidden="true" style={{ position: "absolute", left: "-10000px", width: 1, height: 1, overflow: "hidden" }}>
          Website
          <input name="website" tabIndex={-1} autoComplete="off" />
        </label>
      </div>
      {siteKey && (
        <div style={{ marginTop: 16 }}>
          <TurnstileWidget
            siteKey={siteKey}
            nonce={nonce}
            resetSignal={turnstileReset}
            onToken={setTurnstileToken}
          />
        </div>
      )}
      {error && <p role="alert" style={{ margin: "14px 0 0", color: "#ff9b94", fontSize: 12.5, lineHeight: 1.5 }}>{error}</p>}
      <div className={styles.formFoot}>
        <span
          className="st-mono"
          style={{ fontSize: 11, color: "rgba(245,245,247,0.35)" }}
        >
          cloud · VPC · air-gapped — your call
        </span>
        <button
          type="submit"
          className={styles.sendBtn}
          disabled={submitting || !securityReady || Boolean(siteKey && !turnstileToken)}
          style={{ opacity: submitting || !securityReady || Boolean(siteKey && !turnstileToken) ? 0.55 : 1, cursor: submitting ? "wait" : "pointer" }}
        >
          {submitting ? "Sending…" : "Send request"}
        </button>
      </div>
      </>}
      <p className={styles.mailFallback}>
        Online requests are recorded server-side. Direct fallback: <a href="mailto:pilots@cadverify.com">pilots@cadverify.com</a>. See our <a href="/privacy">privacy notice</a>.
      </p>
    </form>
  );
}
