"use client";

/**
 * Email link (board X12: finish signing in, signing in, link expired; and the
 * X1 "Link sent" card for /magic/sent), behind UI_V4. Same exchange as today:
 * the token is read from the link (fragment, or the legacy query), scrubbed
 * from the address bar at once, kept only in memory, and spent only when the
 * person presses Continue (POST /api/auth/magic/exchange). Service failures are
 * never reported as a bad link.
 *
 * Landing: a part held on this device checks first (the phone check comes
 * before it when the account needs one); then the link's own return path; then
 * the server's path, with today's /verify default becoming Home.
 */
import * as React from "react";
import Link from "next/link";
import { authErrorMessage } from "@/lib/api-recovery";
import { browserPendingPartStore, peekPendingPart } from "@/lib/pending-part";
import { safeLocalPath } from "@/lib/safe-return-path";
import { AuthCard } from "./auth-card";
import { V4_HELD_PART, V4_HOME, v4Landing } from "./landing";
import { twoStepHref } from "@/components/two-step/href";
import "./moments.css";

export function V4MagicVerify() {
  const [token, setToken] = React.useState<string | null>(null);
  const [next, setNext] = React.useState<string | null>(null);
  const [ready, setReady] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [bad, setBad] = React.useState<string | null>(null);
  const [held, setHeld] = React.useState<{ name: string; email: string } | null>(null);

  React.useEffect(() => {
    const fragmentParams = new URLSearchParams(window.location.hash.slice(1));
    const fragment = fragmentParams.get("token");
    const requestedNext = fragmentParams.get("next");
    if (requestedNext) setNext((captured) => captured ?? v4Landing(safeLocalPath(requestedNext, V4_HOME)));
    const query = new URLSearchParams(window.location.search).get("token");
    const candidate = fragment || query;
    // Remove both fragment and legacy query tokens immediately. The token stays
    // only in component memory while the person confirms the exchange.
    window.history.replaceState(null, "", "/magic/verify");
    // Strict Mode may replay this effect after the URL has already been scrubbed.
    setToken((captured) => captured ?? candidate);
    setReady(true);
    let live = true;
    void peekPendingPart(browserPendingPartStore()).then((p) => live && setHeld(p));
    return () => {
      live = false;
    };
  }, []);

  async function exchange(e: React.FormEvent) {
    e.preventDefault();
    if (!token || busy) return;
    setError(null);
    setBusy(true);
    try {
      const res = await fetch("/api/auth/magic/exchange", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ token }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const message = authErrorMessage(res.status, data, "Magic link invalid or expired.");
        // A refused link is spent; a failing service is not the link's fault.
        if (res.status >= 400 && res.status < 500 && res.status !== 429) {
          setToken(null);
          setBad(message);
        } else setError(message);
        return;
      }
      // A part held from sign-in checks itself first; then the page they came from.
      const heldPart = await peekPendingPart(browserPendingPartStore());
      const serverPath = typeof data?.redirect === "string" ? safeLocalPath(data.redirect, V4_HOME) : V4_HOME;
      const redirect = heldPart ? V4_HELD_PART : next ?? v4Landing(data?.two_step ? V4_HOME : serverPath);
      window.history.replaceState(null, "", "/magic/verify");
      // Two-step sign-in: the link was right; the code comes next.
      window.location.href = data?.two_step ? twoStepHref(redirect) : redirect;
    } catch {
      setError("Could not establish a secure session. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (ready && (!token || bad))
    return (
      <AuthCard
        label="Link expired or used"
        icon={{ tone: "bad", mark: "!" }}
        title={token || bad ? "Link expired or used" : "Link not valid"}
        meta={
          bad
            ? [...(/invalid or expired/i.test(bad) ? [] : [bad]), "Email links work once, for 15 min"]
            : ["This sign-in link is missing or malformed", "Email links work once, for 15 min"]
        }
        actions={
          <Link className="btn ink" href="/login">
            Request a new link
          </Link>
        }
      />
    );

  return (
    <AuthCard
      label="Finish signing in"
      title="Finish signing in"
      meta={["Single-use link", "Expires 15 min after it was sent"]}
      error={error}
      busy={busy || !ready}
      links={<Link href="/login">Request a new link</Link>}
    >
      {held ? (
        <div className="form">
          <span className="held">
            <i aria-hidden="true" />
            {held.name} checks after you continue
          </span>
        </div>
      ) : null}
      <form onSubmit={exchange}>
        <div className="acts">
          <button className="btn ink" type="submit" disabled={!ready || !token || busy} aria-busy={busy}>
            {!ready ? "Checking link…" : busy ? "Signing in…" : "Continue"}
          </button>
        </div>
      </form>
    </AuthCard>
  );
}

const MAIL = (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <rect x="3.5" y="5.5" width="17" height="13" rx="2.5" stroke="currentColor" strokeWidth="1.7" />
    <path d="m4.5 7 7.5 6 7.5-6" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
  </svg>
);

/** /magic/sent: reached from older sign-in links; today's v4 sign-in shows this in place. */
export function V4MagicSent({ heldPart }: { heldPart: boolean }) {
  return (
    <AuthCard
      label="Link sent"
      icon={{ tone: "wait", mark: MAIL }}
      title="Link sent"
      meta={["Single use", "Expires in 15 min"]}
      info={[["Part", heldPart ? "Held on this device" : "None"]]}
      note={`If that address can sign in, the link is on its way. Open it on this device.${heldPart ? " Your part checks after sign-in." : ""} Not there? Check spam.`}
      actions={
        <Link className="btn" href="/login">
          Change email
        </Link>
      }
      links={<Link href="/login#magic-link">Resend</Link>}
    />
  );
}
