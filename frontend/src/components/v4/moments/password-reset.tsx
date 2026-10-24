"use client";

/**
 * Password recovery (board X12: reset request, sent, not available, checking
 * link, new password, mismatch, changed, link expired), behind UI_V4. Same
 * calls and rules as today: POST /api/auth/password/reset/start with a
 * Turnstile token (only when password sign-in and a site key are on; the reply
 * never says whether the account exists), and POST .../complete with the token
 * from the link's fragment, which is scrubbed from the address bar at once.
 */
import * as React from "react";
import Link from "next/link";
import { authErrorMessage } from "@/lib/api-recovery";
import { AuthCard, CardField } from "./auth-card";
import { SUPPORT_MAILTO } from "./landing";
import { SecurityCheck } from "./turnstile";
import "./moments.css";

export function V4ForgotPassword({ siteKey, nonce }: { siteKey: string; nonce?: string }) {
  const [email, setEmail] = React.useState("");
  const [token, setToken] = React.useState<string | null>(null);
  const [reset, setReset] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [sent, setSent] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);

  if (!siteKey)
    return (
      <AuthCard
        label="Reset password"
        title="Reset password"
        meta={["Not available on this workspace", "SSO accounts reset through your identity provider"]}
        actions={
          <a className="btn" href={SUPPORT_MAILTO}>
            Email support
          </a>
        }
        links={<Link href="/login">Back to sign in</Link>}
      />
    );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!token || busy) return;
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const response = await fetch("/api/auth/password/reset/start", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, turnstileToken: token }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(authErrorMessage(response.status, data, "Could not request a reset link. Please try again."));
        return;
      }
      setSent(true);
    } catch {
      setError("Could not reach the service. Please try again.");
    } finally {
      setBusy(false);
      setToken(null);
      setReset((value) => value + 1);
    }
  }

  if (sent)
    return (
      <AuthCard
        label="Check your email"
        icon={{ tone: "ok", mark: "✓" }}
        title="Check your email"
        meta={[`Sent if a password account uses ${email}`, "Expires in 15 min"]}
        note="Not there? Check spam, wait a minute, then resend."
        actions={
          <button
            className="btn"
            type="button"
            onClick={() => {
              setSent(false);
              setNotice("Complete the security check to send the link again.");
            }}
          >
            Resend
          </button>
        }
        links={
          <>
            <a href={SUPPORT_MAILTO}>Email support</a>
            <Link href="/login">Back to sign in</Link>
          </>
        }
      />
    );

  return (
    <AuthCard
      label="Reset password"
      title="Reset password"
      meta={["Link expires in 15 min"]}
      error={error}
      notice={notice}
      busy={busy}
      actions={
        <button className="btn ink" type="submit" form="v4-forgot" disabled={!token || busy} aria-busy={busy}>
          {busy ? "Sending…" : "Send reset link"}
        </button>
      }
      links={<Link href="/login">Back to sign in</Link>}
    >
      <form id="v4-forgot" className="form" onSubmit={submit}>
        <CardField id="reset-email" name="email" label="Account email" type="email" autoComplete="email" maxLength={320} required placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        <SecurityCheck siteKey={siteKey} nonce={nonce} resetSignal={reset} onToken={setToken} verified={Boolean(token)} />
      </form>
    </AuthCard>
  );
}

type ResetState = "check" | "form" | "done" | "bad" | "missing";

export function V4ResetPassword() {
  const [token, setToken] = React.useState<string | null>(null);
  const [state, setState] = React.useState<ResetState>("check");
  const [password, setPassword] = React.useState("");
  const [confirmation, setConfirmation] = React.useState("");
  const [mismatch, setMismatch] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    function captureLink() {
      const candidate = new URLSearchParams(window.location.hash.slice(1)).get("token");
      window.history.replaceState(null, "", "/reset-password");
      if (candidate) {
        const ok = /^[A-Za-z0-9_-]{43}$/.test(candidate);
        setToken(ok ? candidate : null);
        setState(ok ? "form" : "missing");
        setError(null);
        setMismatch(false);
        setPassword("");
        setConfirmation("");
      } else {
        setState((s) => (s === "check" ? "missing" : s));
      }
    }
    captureLink();
    window.addEventListener("hashchange", captureLink);
    return () => window.removeEventListener("hashchange", captureLink);
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!token || busy) return;
    if (password !== confirmation) {
      setMismatch(true);
      setError("Passwords don’t match.");
      return;
    }
    setMismatch(false);
    setError(null);
    setBusy(true);
    try {
      const response = await fetch("/api/auth/password/reset/complete", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        // 400: the link is spent or expired (the server consumed it).
        if (response.status === 400) {
          setToken(null);
          setState("bad");
          return;
        }
        setError(authErrorMessage(response.status, data, "This reset link is invalid or expired. Request a new link."));
        return;
      }
      setToken(null);
      setPassword("");
      setConfirmation("");
      setState("done");
    } catch {
      setError("Could not reach the service. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (state === "check")
    return (
      <AuthCard
        label="New password"
        icon={{ tone: "wait" }}
        title="New password"
        meta={["Checking link…"]}
        busy
        actions={
          <button className="btn ink" type="button" disabled>
            Save password
          </button>
        }
      />
    );
  if (state === "done")
    return (
      <AuthCard
        label="Password changed"
        icon={{ tone: "ok", mark: "✓" }}
        title="Password changed"
        meta={["Other sessions signed out", "Sign in with your new password"]}
        actions={
          <Link className="btn ink" href="/login">
            Sign in
          </Link>
        }
      />
    );
  if (state === "bad" || state === "missing")
    return (
      <AuthCard
        label="Link expired"
        icon={{ tone: "bad", mark: "!" }}
        title={state === "bad" ? "Link expired" : "Link not valid"}
        meta={state === "bad" ? ["Reset links work once, for 15 min"] : ["This reset link is missing or malformed", "Reset links work once, for 15 min"]}
        actions={
          <Link className="btn ink" href="/forgot-password">
            Request a new link
          </Link>
        }
        links={<Link href="/login">Back to sign in</Link>}
      />
    );
  return (
    <AuthCard
      label="New password"
      title="New password"
      meta={["Signs out your other sessions"]}
      error={error}
      busy={busy}
      actions={
        <button className="btn ink" type="submit" form="v4-reset" disabled={busy} aria-busy={busy}>
          {busy ? "Saving…" : "Save password"}
        </button>
      }
    >
      <form id="v4-reset" className="form" onSubmit={submit}>
        <CardField
          id="new-password"
          label="New password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          maxLength={128}
          required
          value={password}
          hint="8–128 characters, with a letter and a number"
          onChange={(e) => setPassword(e.target.value)}
        />
        <CardField
          id="confirm-password"
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          maxLength={128}
          required
          value={confirmation}
          aria-invalid={mismatch || undefined}
          onChange={(e) => {
            setConfirmation(e.target.value);
            if (mismatch) setMismatch(false);
          }}
        />
      </form>
    </AuthCard>
  );
}
