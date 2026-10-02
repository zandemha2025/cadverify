"use client";

import * as React from "react";
import { ArrowUpRight } from "lucide-react";
import { TurnstileWidget } from "@/components/auth/turnstile-widget";
import { PILOT_WORKFLOWS } from "@/lib/site/navigation";

function errorMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object") {
    const value = data as { detail?: { message?: string }; message?: string };
    return value.detail?.message ?? value.message ?? fallback;
  }
  return fallback;
}

export function PilotForm({ initialWorkflow }: { initialWorkflow?: string }) {
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
    const question = String(form.get("what") || "").trim();
    const what = `${form.get("workflow")}: ${question}`;
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
    <form className="cv-pilot-form" onSubmit={onSubmit} aria-label="Plan a pilot">
      <h3>Tell us what you need to decide.</h3>
      <p>Describe your workflow and question. We’ll record your request and give you a confirmation receipt.</p>
      {receipt ? <div role="status" className="cv-form-note">
        <p>Request received and recorded.</p>
        <p>Keep this receipt if you contact us about your request.</p>
        <p>CV-{receipt}</p>
      </div> : <>
        <div className="cv-form-fields">
          <label>Work email<input name="email" type="email" autoComplete="email" required maxLength={254} placeholder="you@company.com" /></label>
          <label>Company<input name="company" autoComplete="organization" required maxLength={120} placeholder="Your company" /></label>
          <label>What are you working on?<select name="workflow" defaultValue={PILOT_WORKFLOWS.includes(initialWorkflow ?? "") ? initialWorkflow : PILOT_WORKFLOWS[0]}>{PILOT_WORKFLOWS.map(workflow => <option key={workflow}>{workflow}</option>)}</select></label>
          <label>Your question<textarea name="what" required maxLength={1900} placeholder="Tell us about the parts, the decision, and any requirements we should understand." /></label>
          <label aria-hidden="true" style={{ position: "absolute", left: "-10000px", width: 1, height: 1, overflow: "hidden" }}>
            Website<input name="website" tabIndex={-1} autoComplete="off" />
          </label>
        </div>
        {siteKey && <TurnstileWidget siteKey={siteKey} nonce={nonce} resetSignal={turnstileReset} onToken={setTurnstileToken} />}
        {error && <p role="alert" className="cv-form-note">{error}</p>}
        <button className="cv-button" type="submit" disabled={submitting || !securityReady || Boolean(siteKey && !turnstileToken)}>
          {submitting ? "Sending…" : "Send request"} <ArrowUpRight size={17} aria-hidden="true" />
        </button>
      </>}
      <p className="cv-form-note">Please don’t attach sensitive CAD before agreeing on data handling. See our <a href="/privacy">privacy notice</a>.</p>
      <a className="cv-text-link" href="mailto:nazeemahmed2023@gmail.com">Email nazeemahmed2023@gmail.com</a>
    </form>
  );
}
