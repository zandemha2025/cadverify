"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { ArrowRight, Check, Mail } from "lucide-react";
import { TurnstileWidget } from "@/components/auth/turnstile-widget";
import { authErrorMessage } from "@/lib/api-recovery";
import { emailTier } from "@/components/v4/moments/email-tier";
import { browserPendingPartStore, holdPendingPart } from "@/lib/pending-part";
import { siteSignupMethod } from "@/lib/public-signup";
import { setPendingFile } from "@/components/v4/pending-file";
import { safeLocalPath } from "@/lib/safe-return-path";
import { SignupDataNote } from "./signup-data-note";
import { SiteCta, useSiteSession } from "./site-shell";

export function SignupEmailForm({ part }: { part?: File }) {
  const { user, siteKey, passwordSignup, nonce, ssoLoginPath, freeChecks } = useSiteSession();
  const id = useId();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [reset, setReset] = useState(0);
  const tier = emailTier(email);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!tier || busy) return;
    if (!token) { setError("Complete the security check first."); return; }
    setBusy(true); setError(null);
    try {
      if (part && !await holdPendingPart(browserPendingPartStore(), part, email)) throw new Error("Could not keep this file in your browser. Sign in and upload it in ScaleCAD.");
      const next = new URLSearchParams(window.location.search).get("next");
      const res = await fetch("/api/auth/magic/start", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email: email.trim(), turnstileToken: token, ...(next ? { next: safeLocalPath(next) } : {}) }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(authErrorMessage(res.status, data, "Could not send a sign-in link."));
      setSent(true);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not send a sign-in link. Please try again."); setToken(null); setReset(value => value + 1); }
    finally { setBusy(false); }
  }
  if (user) return <div className="cv-signup-card"><SiteCta /><Link href="/history">View your saved checks</Link></div>;
  if (siteSignupMethod(siteKey, passwordSignup) !== "magic") return <div className="cv-signup-card">
    {passwordSignup ? <>
      <p>Create your account with an email and password. {freeChecks.work} free checks with a work email, {freeChecks.personal} with a personal email.</p>
      <Link className="cv-button" href="/signup" onNavigate={() => { if (part) setPendingFile(part); }}>Try ScaleCAD free<ArrowRight size={16} aria-hidden="true" /></Link>
      <p className="cv-signup-terms">No credit card. <SignupDataNote /></p>
    </> : <p>Contact your organization administrator to create an account.</p>}
    <div className="cv-signup-links"><span>Have an account? <Link href="/login">Log in</Link></span>{ssoLoginPath && <a href={ssoLoginPath}>Sign in with your company account</a>}</div>
  </div>;
  return <div className="cv-signup-card">
    {sent ? <div role="status" className="cv-signup-sent"><Mail size={44} aria-hidden="true" /><h2>Check your inbox.</h2><p>We sent a sign-in link to <strong>{email.trim()}</strong>. Click it to open ScaleCAD with {tier === "personal" ? freeChecks.personal : freeChecks.work} free checks. Not there? Check your spam folder or try another address.</p><button className="cv-button cv-button-secondary" type="button" onClick={async () => { if (part) await browserPendingPartStore().clear().catch(() => {}); setSent(false); setEmail(""); setToken(null); }}>Use a different email</button></div> : <>
      <form onSubmit={submit}>
        <label htmlFor={id}>Work email</label>
        <input id={id} name="email" type="email" autoComplete="email" required maxLength={320} placeholder="you@company.com" value={email} onChange={event => setEmail(event.target.value)} aria-describedby={`${id}-tier`} />
        <p id={`${id}-tier`} className="cv-email-tier" data-tier={tier || "empty"} aria-live="polite">{tier === "personal" ? <><strong>Personal email: {freeChecks.personal} free checks.</strong> Use your work email to start with {freeChecks.work}.</> : tier === "work" ? <><Check size={16} aria-hidden="true" /><strong>Work email: {freeChecks.work} free checks.</strong></> : `Work emails get ${freeChecks.work} free checks. Personal emails get ${freeChecks.personal}.`}</p>
        {siteKey ? <TurnstileWidget siteKey={siteKey} nonce={nonce} resetSignal={reset} onToken={setToken} /> : <p>Email sign-up is unavailable in this environment. <Link href="/login">Log in</Link> or <Link href="/contact">contact us</Link>.</p>}
        {error && <p role="alert">{error}</p>}
        <button className="cv-button" type="submit" disabled={!siteKey || !token || busy}>{busy ? "Sending…" : "Try ScaleCAD free"}<ArrowRight size={16} aria-hidden="true" /></button>
        <p className="cv-signup-terms">No password. No credit card. <SignupDataNote /></p>
      </form>
      <div className="cv-signup-links"><span>Have an account? <Link href="/login">Log in</Link></span>{ssoLoginPath && <a href={ssoLoginPath}>Sign in with your company account</a>}</div>
    </>}
  </div>;
}
