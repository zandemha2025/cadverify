"use client";

import * as React from "react";
import { AuthFrame, AuthSubmit, AuthTextLink } from "@/components/auth/auth-frame";

function errorMessage(data: unknown): string {
  if (data && typeof data === "object") {
    const d = data as { detail?: { message?: string }; message?: string };
    return d.detail?.message ?? d.message ?? "Magic link invalid or expired.";
  }
  return "Magic link invalid or expired.";
}

function safeLocalPath(raw: unknown): string {
  if (typeof raw !== "string") return "/verify";
  try {
    const base = new URL("https://cadverify.invalid");
    const parsed = new URL(raw, base);
    if (parsed.origin !== base.origin || !raw.startsWith("/")) return "/verify";
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return "/verify";
  }
}

export function MagicVerifyClient() {
  const [token, setToken] = React.useState<string | null>(null);
  const [ready, setReady] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const fragment = new URLSearchParams(window.location.hash.slice(1)).get("token");
    const query = new URLSearchParams(window.location.search).get("token");
    const candidate = fragment || query;
    // Remove both fragment and legacy query tokens immediately. The token stays
    // only in component memory while the person confirms the exchange.
    window.history.replaceState(null, "", "/magic/verify");
    setToken(candidate);
    setReady(true);
  }, []);

  async function exchange(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/magic/exchange", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ token }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(errorMessage(data));
        return;
      }
      const redirect = safeLocalPath(data?.redirect);
      window.history.replaceState(null, "", "/magic/verify");
      window.location.href = redirect;
    } catch {
      setError("Could not establish a secure session. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthFrame
      eyebrow="Magic link"
      title="Finish signing in"
      body="Continue to consume this single-use link and open your secure workspace."
      footer={<AuthTextLink href="/login">Request a new link</AuthTextLink>}
    >
      {!ready ? (
        <p style={{ color: "rgba(245,245,247,0.58)", fontSize: 14 }}>Checking link…</p>
      ) : token ? (
        <form onSubmit={exchange} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {error && (
            <p role="alert" style={{ margin: 0, color: "#f08f86", fontSize: 13, lineHeight: 1.5 }}>
              {error}
            </p>
          )}
          <AuthSubmit loading={loading}>Continue to CadVerify</AuthSubmit>
        </form>
      ) : (
        <p role="alert" style={{ margin: 0, color: "#f08f86", fontSize: 13 }}>
          This sign-in link is missing or malformed.
        </p>
      )}
    </AuthFrame>
  );
}
