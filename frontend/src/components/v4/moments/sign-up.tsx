"use client";

/**
 * Create account (board X12: signup, managed, email-link only), behind UI_V4.
 * Same rules as today's signup: the password form only when public password
 * signup is on (POST /api/auth/signup, same fields and limits, same analytics
 * events); otherwise accounts start from the email link or come from the
 * identity provider. A new account lands on Home with Get started open.
 *
 * When free checks need a verified phone, the number typed here is the one
 * used: creating the account sends the code to it at once, and the phone check
 * opens on "Enter code". A part added on the sign-in screen (or here) waits on
 * this device and checks after the phone check, so nothing picked is lost.
 */
import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { apiProblemDetail, authErrorMessage } from "@/lib/api-recovery";
import { identifyAccount, signupMetadata, track } from "@/lib/analytics";
import { isSupportedCad } from "@/lib/cad-file";
import { browserPendingPartStore, holdPendingPart, PENDING_PART_MAX_BYTES } from "@/lib/pending-part";
import { safeLocalPath } from "@/lib/safe-return-path";
import { FORM_MAX_MB } from "@/lib/upload-limit";
import { CAD_ACCEPT, takePendingFile } from "../pending-file";
import { Chip } from "../ui";
import { AuthCard, CardField } from "./auth-card";
import { adoptTyped } from "./early-typing";
import { tierHint } from "./email-tier";
import { V4_HOME, V4_SIGNUP_HOME, afterSignup, v4Landing } from "./landing";
import { PHONE_WHY } from "./phone-gate";
import { rememberSignupPhone, sessionStore } from "./signup-phone";
import "./moments.css";

function partProblem(file: File): string | null {
  if (!isSupportedCad(file.name)) return "Use a STEP, STL or IGES file.";
  if (!file.size) return "That file is empty.";
  if (file.size > PENDING_PART_MAX_BYTES) return `Parts up to ${FORM_MAX_MB} MB can wait here. Add it after you sign up.`;
  return null;
}

/** Send the code to the number typed at sign-up; what happened goes to the phone check. */
async function sendSignupCode(phone: string): Promise<"sent" | "failed"> {
  try {
    const res = await fetch("/api/proxy/account/phone/start", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ phone }),
    });
    const data = await res.json().catch(() => null);
    if (res.ok) {
      rememberSignupPhone(sessionStore(), { phone, sentAt: Date.now(), error: null });
      return "sent";
    }
    rememberSignupPhone(sessionStore(), { phone, sentAt: null, error: apiProblemDetail(data) ?? "We couldn't send a text. Try again." });
  } catch {
    rememberSignupPhone(sessionStore(), { phone, sentAt: null, error: "We couldn't send a text. Check your connection and try again." });
  }
  return "failed";
}

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
  const [part, setPart] = React.useState<File | null>(null);
  const [partError, setPartError] = React.useState<string | null>(null);
  const handed = React.useRef(false);
  const formRef = React.useRef<HTMLFormElement>(null);

  React.useEffect(() => {
    // Anything typed while the page was still loading stays.
    adoptTyped(formRef.current, { name: setName, email: setEmail, phone: setPhone, password: setPassword });
    setHydrated(true);
    // A part added on the sign-in screen comes along (once, even under Strict Mode).
    if (handed.current) return;
    handed.current = true;
    const file = takePendingFile();
    if (file && !partProblem(file)) setPart(file);
  }, []);

  function pick(file: File | undefined) {
    if (!file) return;
    const problem = partProblem(file);
    setPartError(problem);
    if (!problem) setPart(file);
  }

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
      // The part waits for this account only; the code goes to the number typed above.
      const held = part ? await holdPendingPart(browserPendingPartStore(), part, email) : false;
      const sent = phoneNeeded && phone.trim() ? await sendSignupCode(phone.trim()) : null;
      window.location.href = afterSignup({ next, phone: sent, held });
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
      <form id="v4-signup" ref={formRef} className="form" onSubmit={submit}>
        <CardField id="name" name="name" label="Full name" type="text" autoComplete="name" required maxLength={160} placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} />
        <CardField id="email" name="email" label="Email" type="email" autoComplete="email" required maxLength={320} placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} />
        <p className="chipline" aria-live="polite">
          <Chip tone={hint.tone}>{hint.chip}</Chip>
          {hint.text}
        </p>
        <CardField
          id="phone"
          name="phone"
          label={phoneNeeded ? "Mobile number" : "Phone (optional)"}
          type="tel"
          autoComplete="tel"
          inputMode="tel"
          maxLength={32}
          placeholder="+1 555 123 4567"
          value={phone}
          hint={phoneNeeded ? PHONE_WHY : undefined}
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
        <div className="heldrow" aria-live="polite">
          {part ? (
            <>
              <span>
                <b>{part.name}</b> · held on this device · checks after sign-up
              </span>
              <button className="btn ghost sm" type="button" onClick={() => setPart(null)}>
                Remove
              </button>
            </>
          ) : (
            <>
              <span>Add a part to check first (optional)</span>
              <label className="btn ghost sm filebtn">
                Add part
                <input
                  type="file"
                  accept={CAD_ACCEPT}
                  aria-label="Add a part to check after sign-up"
                  onChange={(e) => {
                    pick(e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
              </label>
            </>
          )}
        </div>
        {partError ? (
          <span className="hintx bad" role="alert">
            {partError}
          </span>
        ) : null}
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
