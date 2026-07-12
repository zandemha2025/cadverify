"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { AuthField, AuthFrame, AuthSubmit, AuthTextLink } from "@/components/auth/auth-frame";
import { TurnstileWidget } from "@/components/auth/turnstile-widget";

const POST_LOGIN_HOME = "/verify";

function safeLocalPath(raw: string | null, fallback = POST_LOGIN_HOME): string {
  if (!raw) return fallback;
  try {
    const base = new URL("https://cadverify.invalid");
    const parsed = new URL(raw, base);
    if (parsed.origin !== base.origin || !raw.startsWith("/")) return fallback;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }
}

function errorMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object") {
    const d = data as { detail?: { message?: string }; message?: string };
    return d.detail?.message ?? d.message ?? fallback;
  }
  return fallback;
}

export function LoginForm({
  turnstileSiteKey,
  nonce,
  passwordEnabled,
  ssoLoginPath,
}: {
  turnstileSiteKey?: string;
  nonce?: string;
  passwordEnabled: boolean;
  ssoLoginPath?: string;
}) {
  const params = useSearchParams();
  const next = safeLocalPath(params.get("next"));
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [magicEmail, setMagicEmail] = React.useState("");
  const [magicError, setMagicError] = React.useState<string | null>(null);
  const [magicLoading, setMagicLoading] = React.useState(false);
  const [turnstileToken, setTurnstileToken] = React.useState<string | null>(null);
  const [turnstileReset, setTurnstileReset] = React.useState(0);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(errorMessage(data, "Invalid email or password."));
        return;
      }
      window.location.href = next;
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  async function onMagicSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!turnstileToken) {
      setMagicError("Complete the security check first.");
      return;
    }
    setMagicError(null);
    setMagicLoading(true);
    try {
      const res = await fetch("/api/auth/magic/start", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: magicEmail, turnstileToken }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setMagicError(errorMessage(data, "Could not send a sign-in link."));
        setTurnstileReset((value) => value + 1);
        return;
      }
      window.location.href = "/magic/sent";
    } catch {
      setMagicError("Could not send a sign-in link. Please try again.");
      setTurnstileReset((value) => value + 1);
    } finally {
      setMagicLoading(false);
    }
  }

  return (
    <AuthFrame
      eyebrow="Secure workspace"
      title="Log in to CadVerify"
      body={
        ssoLoginPath && !passwordEnabled
          ? "Continue through your organization's approved identity provider."
          : "Enter the workspace where part, machine, material, and decision records stay auditable."
      }
      footer={
        passwordEnabled || turnstileSiteKey ? (
          <>New here? <AuthTextLink href="/signup">Create an account</AuthTextLink></>
        ) : (
          <span className="st-mono" style={{ fontSize: 11, color: "rgba(245,245,247,0.4)" }}>
            Access is managed by your organization administrator.
          </span>
        )
      }
    >
      {ssoLoginPath && (
        <a
          href={ssoLoginPath}
          style={{ display: "block", width: "100%", borderRadius: 999, background: "#f5f5f7", color: "#050506", padding: "13px 18px", textAlign: "center", textDecoration: "none", fontSize: 14, fontWeight: 500 }}
        >
          Continue with enterprise SSO
        </a>
      )}

      {ssoLoginPath && passwordEnabled && (
        <div style={{ display: "flex", alignItems: "center", gap: 12, margin: "24px 0", color: "rgba(245,245,247,0.36)", fontSize: 11 }}>
          <span style={{ height: 1, flex: 1, background: "rgba(245,245,247,0.12)" }} />
          OR USE PASSWORD
          <span style={{ height: 1, flex: 1, background: "rgba(245,245,247,0.12)" }} />
        </div>
      )}

      {passwordEnabled && <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <AuthField
          id="email"
          name="email"
          label="Email"
          type="email"
          autoComplete="email"
          required
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <AuthField
          id="password"
          name="password"
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          placeholder="Your password"
          value={password}
          error={error}
          onChange={(e) => setPassword(e.target.value)}
        />
        <AuthSubmit loading={loading}>Log in</AuthSubmit>
      </form>}

      {turnstileSiteKey && (
        <>
          <div id="magic-link" style={{ display: "flex", alignItems: "center", gap: 12, margin: passwordEnabled || ssoLoginPath ? "24px 0" : "0 0 24px", color: "rgba(245,245,247,0.36)", fontSize: 11 }}>
            <span style={{ height: 1, flex: 1, background: "rgba(245,245,247,0.12)" }} />
            OR USE A ONE-TIME LINK
            <span style={{ height: 1, flex: 1, background: "rgba(245,245,247,0.12)" }} />
          </div>
          <form onSubmit={onMagicSubmit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <AuthField
              id="magic-email"
              name="magic-email"
              label="Email for sign-in link"
              type="email"
              autoComplete="email"
              required
              placeholder="you@company.com"
              value={magicEmail}
              error={magicError}
              onChange={(e) => setMagicEmail(e.target.value)}
            />
            <TurnstileWidget
              siteKey={turnstileSiteKey}
              nonce={nonce}
              resetSignal={turnstileReset}
              onToken={setTurnstileToken}
            />
            <AuthSubmit loading={magicLoading} disabled={!turnstileToken}>
              Email me a sign-in link
            </AuthSubmit>
          </form>
        </>
      )}
    </AuthFrame>
  );
}
