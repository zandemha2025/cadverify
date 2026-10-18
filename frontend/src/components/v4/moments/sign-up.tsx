"use client";

/**
 * Create account (board X12: signup, managed, email-link only), behind UI_V4.
 * Same rules as today's signup: the password form only when public password
 * signup is on (POST /api/auth/signup, same fields and limits, same analytics
 * events); otherwise accounts start from the email link or come from the
 * identity provider. A new account lands on Home with Get started open.
 */
import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { authErrorMessage } from "@/lib/api-recovery";
import { identifyAccount, signupMetadata, track } from "@/lib/analytics";
import { safeLocalPath } from "@/lib/safe-return-path";
import { Chip } from "../ui";
import { AuthCard, CardField } from "./auth-card";
import { tierHint } from "./email-tier";
import { V4_HOME, V4_SIGNUP_HOME, v4Landing } from "./landing";
import "./moments.css";

export function V4SignUp({
  freeChecks,
  ssoLoginPath,
  phoneNeeded,
}: {
  freeChecks: { work: number; personal: number };
  ssoLoginPath?: string;
  phoneNeeded: boolean;
}) {
  const asked = useSearchParams().get("next");
  const requested = safeLocalPath(asked, V4_SIGNUP_HOME);
  const next = v4Landing(requested) === V4_HOME ? V4_SIGNUP_HOME : requested;
  const explicitNext = asked && next !== V4_SIGNUP_HOME && next !== V4_HOME ? next : null;
  const [hydrated, setHydrated] = React.useState(false);
  const [name, setName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [phone, setPhone] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => setHydrated(true), []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      const res = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password, name, phone, ...signupMetadata() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(authErrorMessage(res.status, data, "Could not create your account."));
        return;
      }
      identifyAccount(data.user.id);
      track("signup_completed", { auth_provider: "password" });
      window.location.href = next;
    } catch {
      setError("Could not connect. Please try again in a moment.");
    } finally {
      setBusy(false);
    }
  }

  const hint = tierHint(email, freeChecks);
  return (
    <AuthCard
      label="Create account"
      title="Create account"
      meta={[`${freeChecks.work} free checks with a work email`, `${freeChecks.personal} with a personal one`, "No credit card"]}
      error={error}
      busy={busy}
      actions={
        <button className="btn ink" type="submit" form="v4-signup" disabled={!hydrated || busy} aria-busy={busy}>
          {busy ? "Creating account…" : "Create account"}
        </button>
      }
      links={
        <>
          {ssoLoginPath ? <a href={ssoLoginPath}>Sign in with SSO</a> : null}
          <Link href={`/login${explicitNext ? `?next=${encodeURIComponent(explicitNext)}` : ""}`}>Have an account? Sign in</Link>
        </>
      }
    >
      <form id="v4-signup" className="form" onSubmit={submit}>
        <CardField id="name" name="name" label="Full name" type="text" autoComplete="name" required maxLength={160} placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} />
        <CardField id="email" name="email" label="Email" type="email" autoComplete="email" required maxLength={320} placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        <p className="chipline" aria-live="polite">
          <Chip tone={hint.tone}>{hint.chip}</Chip>
          {hint.text}
        </p>
        <CardField
          id="phone"
          name="phone"
          label="Phone (optional)"
          type="tel"
          autoComplete="tel"
          maxLength={32}
          placeholder="+1 555 123 4567"
          value={phone}
          hint={phoneNeeded ? "Needed before your first free check" : undefined}
          onChange={(e) => setPhone(e.target.value)}
        />
        {/* HTML counts UTF-16 units; allow two per server-validated code point. */}
        <CardField
          id="password"
          name="password"
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          maxLength={256}
          value={password}
          hint="8–128 characters, with a letter and a number"
          onChange={(e) => setPassword(e.target.value)}
        />
      </form>
    </AuthCard>
  );
}

/** Accounts here come from the organization's identity provider. */
export function V4ManagedAccess({ ssoLoginPath }: { ssoLoginPath?: string }) {
  return (
    <AuthCard
      label="Managed access"
      title="Managed access"
      meta={["Accounts come from your identity provider"]}
      info={[["Need access", "Ask your organization admin"]]}
      actions={
        ssoLoginPath ? (
          <a className="btn ink" href={ssoLoginPath}>
            Sign in with SSO
          </a>
        ) : null
      }
      links={<Link href="/login">Back to sign in</Link>}
    />
  );
}

/** Production accounts start from a single-use email link. */
export function V4EmailLinkSignUp() {
  return (
    <AuthCard
      label="Create account"
      title="Create account"
      meta={["Starts with a single-use email link", "Add a password later in Security"]}
      actions={
        <Link className="btn ink" href="/login#magic-link">
          Continue with email
        </Link>
      }
      links={<Link href="/login">Have an account? Sign in</Link>}
    />
  );
}
