"use client";

/**
 * Sign in (board X1), behind UI_V4. Same calls and rules as today's login form:
 * POST /api/auth/login (password, when AUTH_MODE allows it), POST
 * /api/auth/magic/start (email link, only with a Turnstile site key and a
 * passed security check), the SSO path when one is configured, safe `next`
 * return paths, and the optional part held on this device (IndexedDB, keyed
 * to the email, picked up once after sign-in).
 */
import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { authErrorMessage } from "@/lib/api-recovery";
import { isSupportedCad } from "@/lib/cad-file";
import { browserPendingPartStore, holdPendingPart, PENDING_PART_MAX_BYTES } from "@/lib/pending-part";
import { safeLocalPath } from "@/lib/safe-return-path";
import { CAD_LIMIT } from "@/lib/upload-limit";
import { CAD_ACCEPT } from "../pending-file";
import { Chip, cx } from "../ui";
import { tierHint } from "./email-tier";
import { V4_HELD_PART, V4_HOME, v4Landing } from "./landing";
import { PartGlyph } from "./phone-gate";
import { SecurityCheck } from "./turnstile";
import "./moments.css";

type Step = "link" | "password" | "sent";

const MAIL = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <rect x="3.5" y="5.5" width="17" height="13" rx="2.5" stroke="currentColor" strokeWidth="1.7" />
    <path d="m4.5 7 7.5 6 7.5-6" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
  </svg>
);

function partProblem(file: File): string | null {
  if (!isSupportedCad(file.name)) return "Use a STEP, STL or IGES file.";
  if (!file.size) return "That file is empty.";
  if (file.size > PENDING_PART_MAX_BYTES) return `Parts ${CAD_LIMIT} can wait here. Add it after you sign in.`;
  return null;
}

export function V4SignIn({
  turnstileSiteKey,
  nonce,
  passwordEnabled,
  ssoLoginPath,
  freeChecks,
  passwordSignup,
}: {
  turnstileSiteKey?: string;
  nonce?: string;
  passwordEnabled: boolean;
  ssoLoginPath?: string;
  freeChecks: { work: number; personal: number };
  passwordSignup: boolean;
}) {
  const params = useSearchParams();
  const asked = params.get("next");
  const next = v4Landing(safeLocalPath(asked, V4_HOME));
  const explicitNext = asked && next !== V4_HOME ? next : null;
  const linkOn = Boolean(turnstileSiteKey);
  const canSignIn = linkOn || passwordEnabled;

  const [hydrated, setHydrated] = React.useState(false);
  const [step, setStep] = React.useState<Step>(linkOn ? "link" : "password");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [token, setToken] = React.useState<string | null>(null);
  const [resetSignal, setResetSignal] = React.useState(0);
  const [part, setPart] = React.useState<File | null>(null);
  const [partError, setPartError] = React.useState<string | null>(null);
  const [heldSent, setHeldSent] = React.useState(false);
  const [dragging, setDragging] = React.useState(false);
  const emailRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => setHydrated(true), []);

  function pick(file: File | undefined) {
    if (!file) return;
    const problem = partProblem(file);
    setPartError(problem);
    if (!problem) setPart(file);
  }

  const hint = tierHint(email, freeChecks);
  const tierShort = hint.tone === "warn" ? `${freeChecks.personal}, personal email` : hint.tone === "ok" ? `${freeChecks.work}, work email` : null;

  async function signInWithPassword() {
    setBusy(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(authErrorMessage(res.status, data, "Invalid email or password."));
        return;
      }
      // A part added here checks itself first, for this account only.
      const held = part ? await holdPendingPart(browserPendingPartStore(), part, email) : false;
      window.location.href = held ? V4_HELD_PART : next;
    } catch {
      setError("Could not reach the server. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function sendLink() {
    if (!token) {
      setError("Complete the security check first.");
      return;
    }
    setBusy(true);
    try {
      // Hold the part before sending, so the link can never arrive first.
      const held = part ? await holdPendingPart(browserPendingPartStore(), part, email) : false;
      const res = await fetch("/api/auth/magic/start", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, turnstileToken: token, ...(explicitNext ? { next: explicitNext } : {}) }),
      });
      const data = await res.json().catch(() => ({}));
      setResetSignal((n) => n + 1);
      if (!res.ok) {
        setError(authErrorMessage(res.status, data, "Could not send a sign-in link."));
        return;
      }
      setHeldSent(held);
      setStep("sent");
    } catch {
      setError("Could not send a sign-in link. Please try again.");
      setResetSignal((n) => n + 1);
    } finally {
      setBusy(false);
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setNotice(null);
    if (!/^[^@\s]+@[^@\s]+$/.test(email.trim())) {
      setError("Enter your email address.");
      emailRef.current?.focus();
      return;
    }
    if (step === "password" && !password) {
      setError("Enter your password.");
      return;
    }
    if (step === "password") void signInWithPassword();
    else void sendLink();
  }

  const signupHref = `/signup${explicitNext ? `?next=${encodeURIComponent(explicitNext)}` : ""}`;
  const meta =
    !canSignIn
      ? ["Through your organization’s identity provider"]
      : step === "password" && !linkOn
        ? ["Email and password"]
        : ["A new email creates an account", "No credit card"];

  return (
    <main
      id="main"
      className="world mo-x1"
      aria-label="Sign in"
      onDragOver={(e) => {
        if (!canSignIn || step === "sent") return;
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        if (!canSignIn || step === "sent") return;
        e.preventDefault();
        setDragging(false);
        pick(e.dataTransfer.files?.[0]);
      }}
    >
      <section className="stage" aria-label="Your part, waiting">
        {canSignIn && step !== "sent" ? (
          part ? (
            <div className="wait swap">
              <span className="held">
                <i aria-hidden="true" />
                Held on this device
              </span>
              <div className="pic" aria-hidden="true">
                <span className="shade" />
                <PartGlyph />
              </div>
              <b>{part.name}</b>
              <span>Checks after sign-in</span>
              {step === "password" ? (
                <button className="btn ghost sm" type="button" onClick={() => setPart(null)}>
                  Remove
                </button>
              ) : null}
            </div>
          ) : (
            <div className="wait swap">
              <label className={cx("drop1", dragging && "drag")}>
                <input
                  type="file"
                  accept={CAD_ACCEPT}
                  onChange={(e) => {
                    pick(e.target.files?.[0]);
                    e.target.value = "";
                  }}
                />
                <b>Add a part (optional)</b>
                <span>STEP, STL or IGES · held on this device · checks after sign-in</span>
              </label>
              {partError ? (
                <span className="err" role="alert">
                  {partError}
                </span>
              ) : null}
            </div>
          )
        ) : step === "sent" && heldSent && part ? (
          <div className="wait swap">
            <span className="held">
              <i aria-hidden="true" />
              Held on this device
            </span>
            <div className="pic" aria-hidden="true">
              <span className="shade" />
              <PartGlyph />
            </div>
            <b>{part.name}</b>
            <span>Checks after you open the link</span>
          </div>
        ) : null}
      </section>

      <aside className="sheet" aria-label="Sign in">
        {step !== "sent" ? (
          <div className="swap" style={{ display: "flex", flexDirection: "column" }}>
            <div className="top">
              <h1 className="ptitle">Sign in</h1>
              <p className="pmeta" style={{ marginTop: 6 }}>
                {meta.map((m) => (
                  <span key={m}>{m}</span>
                ))}
              </p>
            </div>
            <form className="form" onSubmit={submit} noValidate>
              {ssoLoginPath ? (
                <>
                  <a className="btn big" href={ssoLoginPath}>
                    Sign in with SSO
                  </a>
                  {canSignIn ? <div className="or">or</div> : null}
                </>
              ) : null}
              {canSignIn ? (
                <>
                  <label className="field">
                    Email
                    <input
                      ref={emailRef}
                      id="email"
                      name="email"
                      type="email"
                      autoComplete="email"
                      required
                      maxLength={320}
                      placeholder="you@company.com"
                      value={email}
                      aria-invalid={error === "Enter your email address." ? true : undefined}
                      onChange={(e) => {
                        setEmail(e.target.value);
                        if (error) setError(null);
                      }}
                    />
                  </label>
                  <p className="tier" aria-live="polite">
                    <Chip tone={hint.tone}>{hint.chip}</Chip>
                    <span>{hint.text}</span>
                  </p>
                  {step === "password" ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      <label className="field">
                        Password
                        <input
                          id="password"
                          name="password"
                          type="password"
                          autoComplete="current-password"
                          required
                          value={password}
                          onChange={(e) => {
                            setPassword(e.target.value);
                            if (error) setError(null);
                          }}
                        />
                      </label>
                      <Link href="/forgot-password" style={{ fontSize: 13, alignSelf: "flex-start" }}>
                        Reset password
                      </Link>
                    </div>
                  ) : (
                    <>
                      <SecurityCheck
                        siteKey={turnstileSiteKey ?? ""}
                        nonce={nonce}
                        resetSignal={resetSignal}
                        verified={Boolean(token)}
                        onToken={(t) => {
                          setToken(t);
                          if (t && error === "Complete the security check first.") setError(null);
                        }}
                      />
                      <div className="heldrow">
                        {part ? (
                          <>
                            <span>
                              <b>{part.name}</b> · held on this device
                            </span>
                            <button className="btn ghost sm" type="button" onClick={() => setPart(null)}>
                              Remove
                            </button>
                          </>
                        ) : (
                          <>
                            <span>No part held</span>
                            <label className="btn ghost sm filebtn">
                              Add part
                              <input
                                type="file"
                                accept={CAD_ACCEPT}
                                aria-label="Add part"
                                onChange={(e) => {
                                  pick(e.target.files?.[0]);
                                  e.target.value = "";
                                }}
                              />
                            </label>
                          </>
                        )}
                      </div>
                    </>
                  )}
                  {error ? (
                    <p className="err" role="alert">
                      {error}
                    </p>
                  ) : notice ? (
                    <p className="smeta" role="status" style={{ margin: 0 }}>
                      {notice}
                    </p>
                  ) : null}
                  <button className="btn ink big" type="submit" disabled={!hydrated || busy} aria-busy={busy}>
                    {busy ? (step === "password" ? "Signing in…" : "Sending…") : step === "password" ? "Sign in" : "Send link"}
                  </button>
                  {linkOn && passwordEnabled ? (
                    <>
                      <div className="or">or</div>
                      <button
                        className="btn big"
                        type="button"
                        onClick={() => {
                          setStep(step === "password" ? "link" : "password");
                          setError(null);
                        }}
                      >
                        {step === "password" ? "Use email link" : "Use password"}
                      </button>
                    </>
                  ) : null}
                  <span className="links">
                    {passwordSignup ? (
                      <Link href={signupHref}>Create an account with a password</Link>
                    ) : (
                      <Link href={signupHref}>Create an account</Link>
                    )}
                  </span>
                </>
              ) : (
                <p className="smeta" style={{ margin: 0 }}>
                  Access is managed by your organization administrator.
                </p>
              )}
            </form>
            <p className="fine">
              Work email: {freeChecks.work} free checks. Personal: {freeChecks.personal}. Parts are visible to your team only. <Link href="/terms">Terms</Link> · <Link href="/privacy">Privacy</Link>
            </p>
          </div>
        ) : (
          <div className="swap" style={{ display: "flex", flexDirection: "column" }} role="status">
            <div className="top">
              <span className="mail">{MAIL}</span>
              <h1 className="ptitle" style={{ marginTop: 14 }}>
                Link sent
              </h1>
              <p className="pmeta" style={{ marginTop: 6 }}>
                <span style={{ overflowWrap: "anywhere" }}>
                  To <b>{email}</b>
                </span>
                <span>Single use</span>
                <span>Expires in 15 min</span>
              </p>
              <p className="smeta">
                If that address can sign in, the link is on its way. Open it on this device.{heldSent ? " Your part checks after sign-in." : ""}
              </p>
            </div>
            <div className="sent">
              <div className="kv" style={{ padding: 0 }}>
                <span>Part</span>
                <b>{heldSent ? "Held on this device" : "None"}</b>
                {tierShort ? (
                  <>
                    <span>Free checks</span>
                    <b>{tierShort}</b>
                  </>
                ) : null}
              </div>
              <button
                className="btn big"
                type="button"
                onClick={() => {
                  setStep("link");
                  setError(null);
                }}
              >
                Change email
              </button>
              <p style={{ margin: 0, color: "var(--ink3)", fontSize: 13, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                Not there? Check spam.
                <button
                  className="btn ghost sm"
                  type="button"
                  style={{ height: 28, padding: "0 6px" }}
                  onClick={() => {
                    setStep("link");
                    setError(null);
                    setNotice("Complete the security check, then send the link again.");
                  }}
                >
                  Resend
                </button>
              </p>
            </div>
          </div>
        )}
      </aside>
    </main>
  );
}
