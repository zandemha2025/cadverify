"use client";

import * as React from "react";
import { AuthField, AuthFrame, AuthSubmit, AuthTextLink } from "@/components/auth/auth-frame";
import { TurnstileWidget } from "@/components/auth/turnstile-widget";
import { authErrorMessage } from "@/lib/api-recovery";

export function ForgotPasswordForm({ siteKey, nonce }: { siteKey: string; nonce?: string }) {
  const [email, setEmail] = React.useState("");
  const [token, setToken] = React.useState<string | null>(null);
  const [reset, setReset] = React.useState(0);
  const [loading, setLoading] = React.useState(false);
  const [sent, setSent] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!token) return;
    setError(null);
    setSent(false);
    setLoading(true);
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
      setLoading(false);
      setToken(null);
      setReset(value => value + 1);
    }
  }

  return <AuthFrame eyebrow="Account recovery" title="Forgot your password?" body="Enter your account email to request a password reset. The link expires in 15 minutes." footer={<AuthTextLink href="/login">Back to log in</AuthTextLink>}>
    {siteKey ? <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {sent && <p role="status" style={{ margin: 0, fontSize: 14, lineHeight: 1.7 }}>If an active password account matches that email, you’ll receive a reset link. Check your inbox and spam folder. If it doesn’t arrive, wait a minute and try again or <AuthTextLink href="mailto:nazeem@scalecad.ai">contact us</AuthTextLink>.</p>}
      {error && <p role="alert" style={{ margin: 0, color: "#b42318", fontSize: 14 }}>{error}</p>}
      <AuthField id="reset-email" label="Account email" type="email" autoComplete="email" maxLength={320} required value={email} onChange={event => setEmail(event.target.value)} />
      <TurnstileWidget siteKey={siteKey} nonce={nonce} resetSignal={reset} onToken={setToken} />
      <AuthSubmit loading={loading} disabled={!token}>Send reset link</AuthSubmit>
    </form> : <p role="alert" style={{ fontSize: 14, lineHeight: 1.7 }}>Email password recovery is unavailable here. For SSO accounts, use your organization’s identity provider. Otherwise, <AuthTextLink href="mailto:nazeem@scalecad.ai">contact us for help</AuthTextLink>.</p>}
  </AuthFrame>;
}
