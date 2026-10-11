"use client";

import * as React from "react";
import { AuthField, AuthFrame, AuthSubmit, AuthTextLink } from "@/components/auth/auth-frame";
import { authErrorMessage } from "@/lib/api-recovery";

export function ResetPasswordForm() {
  const [token, setToken] = React.useState<string | null>(null);
  const [ready, setReady] = React.useState(false);
  const [password, setPassword] = React.useState("");
  const [confirmation, setConfirmation] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [done, setDone] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    function captureLink() {
      const candidate = new URLSearchParams(window.location.hash.slice(1)).get("token");
      window.history.replaceState(null, "", "/reset-password");
      if (candidate) {
        setToken(/^[A-Za-z0-9_-]{43}$/.test(candidate) ? candidate : null);
        setDone(false);
        setError(null);
        setPassword("");
        setConfirmation("");
      }
      setReady(true);
    }
    captureLink();
    window.addEventListener("hashchange", captureLink);
    return () => window.removeEventListener("hashchange", captureLink);
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!token) return;
    if (password !== confirmation) {
      setError("The passwords do not match.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const response = await fetch("/api/auth/password/reset/complete", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setError(authErrorMessage(response.status, data, "This reset link is invalid or expired. Request a new link."));
        return;
      }
      setToken(null);
      setPassword("");
      setConfirmation("");
      setDone(true);
    } catch {
      setError("Could not reach the service. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return <AuthFrame eyebrow="Account recovery" title={done ? "Password reset" : "Choose a new password"} body={done ? "Your password has changed and previous sessions have been signed out. Log in with your new password." : "Use 8–128 characters, including at least one letter and one number."} footer={<AuthTextLink href={done ? "/login" : "/forgot-password"}>{done ? "Log in" : "Request a new reset link"}</AuthTextLink>}>
    {done ? <p role="status" style={{ fontSize: 14 }}>Your new password is ready to use.</p> : !ready ? <p>Checking link…</p> : token ? <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {error && <p role="alert" style={{ margin: 0, color: "#b42318", fontSize: 14 }}>{error}</p>}
      <AuthField id="new-password" label="New password" type="password" autoComplete="new-password" minLength={8} maxLength={128} required value={password} onChange={event => setPassword(event.target.value)} />
      <AuthField id="confirm-password" label="Confirm new password" type="password" autoComplete="new-password" minLength={8} maxLength={128} required value={confirmation} onChange={event => setConfirmation(event.target.value)} />
      <AuthSubmit loading={loading}>Reset password</AuthSubmit>
    </form> : <p role="alert" style={{ fontSize: 14 }}>This reset link is missing or malformed. Request a new link to continue.</p>}
  </AuthFrame>;
}
