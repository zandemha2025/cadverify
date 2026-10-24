"use client";

/**
 * Two-step sign-in (after a correct password, email link or Google sign-in),
 * on the v4 account-state card. Either a code from the authenticator app (or
 * a recovery code), or, when an organization requires two-step and the
 * account hasn't set it up, the setup itself: QR code or key, first code, then
 * the ten recovery codes, shown once.
 */
import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { safeLocalPath } from "@/lib/safe-return-path";
import { ManualKey, QrCode, RecoveryCodes, SUPPORT_EMAIL, cleanCode } from "@/components/two-step/parts";
import { useTwoStepSignIn } from "@/components/two-step/use-two-step-sign-in";
import { R } from "../routes";
import { AuthCard, CardField } from "./auth-card";
import { V4_HOME, v4Landing } from "./landing";
import "./moments.css";

const LOCK = (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <rect x="5" y="10.5" width="14" height="10" rx="2.5" stroke="currentColor" strokeWidth="1.7" />
    <path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" stroke="currentColor" strokeWidth="1.7" />
  </svg>
);

const METHOD: Record<string, string> = { password: "Password checked", email_link: "Email link checked", google: "Google sign-in checked" };

export function V4TwoStep() {
  const params = useSearchParams();
  const next = v4Landing(safeLocalPath(params.get("next"), V4_HOME));
  const flow = useTwoStepSignIn({
    onDone: (used) => {
      window.location.href = used === "recovery" ? `${R.security}?recovery=used` : next;
    },
  });
  const [code, setCode] = React.useState("");
  const [recovery, setRecovery] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const { state, phase, busy, error } = flow;

  React.useEffect(() => {
    document.getElementById("ts-code")?.focus();
  }, [phase.kind, recovery]);

  const lost = (
    <>
      Lost your phone and your recovery codes? Email <a href={`mailto:${SUPPORT_EMAIL}?subject=ScaleCAD%20two-step%20sign-in`}>{SUPPORT_EMAIL}</a> from this address.
    </>
  );

  if (phase.kind === "loading")
    return <AuthCard label="Two-step sign-in" icon={{ tone: "wait" }} title="Two-step sign-in" meta={["Checking this sign-in"]} busy />;

  if (phase.kind === "expired")
    return (
      <AuthCard
        label="Sign-in expired"
        icon={{ tone: "bad", mark: "!" }}
        title="Sign in again"
        meta={[phase.message]}
        actions={
          <Link className="btn ink" href={`/login${next !== V4_HOME ? `?next=${encodeURIComponent(next)}` : ""}`}>
            Sign in
          </Link>
        }
      />
    );

  if (phase.kind === "codes")
    return (
      <AuthCard
        label="Recovery codes"
        icon={{ tone: "ok", mark: LOCK }}
        title="Save your recovery codes"
        meta={["Two-step sign-in is on", "Shown once"]}
        actions={
          <button className="btn ink" type="button" disabled={!saved} onClick={flow.finishSetup}>
            Continue
          </button>
        }
        note="Each code signs you in once if your phone isn't with you. You can make new ones in Account › Security."
      >
        <div className="form">
          <RecoveryCodes codes={phase.codes} account={state?.email ?? ""} />
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13.5 }}>
            <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
            I saved these codes
          </label>
        </div>
      </AuthCard>
    );

  if (phase.kind === "setup") {
    const enrol = phase.enrolment;
    const orgs = state?.required_by ?? [];
    return (
      <AuthCard
        label="Set up two-step sign-in"
        icon={{ tone: "wait", mark: LOCK }}
        title="Set up two-step sign-in"
        meta={[orgs.length ? `Required by ${orgs.join(", ")}` : "Required by your organization", state?.email ?? ""]}
        error={error}
        busy={busy || !enrol}
        links={<Link href="/login">Sign in as someone else</Link>}
        note={lost}
      >
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            if (cleanCode(code).length !== 6) {
              flow.setError("Enter the 6-digit code from your authenticator app.");
              return;
            }
            void flow.confirmSetup(cleanCode(code));
          }}
        >
          <span className="hintx">1. In an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, Authy), add an account by scanning this code.</span>
          {enrol ? (
            <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
              <QrCode rows={enrol.qr} size={164} label="QR code for your authenticator app" />
              <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0, flex: "1 1 160px" }}>
                <span className="hintx">Can&rsquo;t scan? Type this key:</span>
                <ManualKey value={enrol.manual_key} />
              </div>
            </div>
          ) : (
            <span className="hintx">Making your key…</span>
          )}
          <CardField
            id="ts-code"
            label="2. The 6-digit code the app shows"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9 \-]*"
            maxLength={7}
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <div className="acts" style={{ padding: "4px 0 0" }}>
            <button className="btn ink" type="submit" disabled={busy || !enrol} aria-busy={busy}>
              {busy ? "Checking…" : "Turn on and continue"}
            </button>
          </div>
        </form>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      label="Two-step sign-in"
      icon={{ tone: "wait", mark: LOCK }}
      title={recovery ? "Enter a recovery code" : "Enter your code"}
      meta={[state?.email ?? "", METHOD[state?.method ?? ""] ?? "First step checked"]}
      error={error}
      busy={busy}
      links={
        <>
          <button
            type="button"
            onClick={() => {
              setRecovery((r) => !r);
              setCode("");
              flow.setError(null);
            }}
          >
            {recovery ? "Use the app instead" : "Use a recovery code"}
          </button>
          <Link href="/login">Sign in again</Link>
        </>
      }
      note={lost}
    >
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (recovery) {
            if (code.replace(/[\s-]/g, "").length !== 10) {
              flow.setError("Recovery codes look like abcde-fghjk.");
              return;
            }
            void flow.verify({ recovery_code: code });
            return;
          }
          if (cleanCode(code).length !== 6) {
            flow.setError("Enter the 6-digit code from your authenticator app.");
            return;
          }
          void flow.verify({ code: cleanCode(code) });
        }}
      >
        <CardField
          id="ts-code"
          label={recovery ? "Recovery code" : "6-digit code from your authenticator app"}
          inputMode={recovery ? "text" : "numeric"}
          autoComplete={recovery ? "off" : "one-time-code"}
          autoCapitalize="off"
          spellCheck={false}
          maxLength={recovery ? 16 : 7}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          hint={recovery ? `${state?.recovery_codes_left ?? 0} unused. Each works once.` : "A new code every 30 seconds."}
        />
        <div className="acts" style={{ padding: "4px 0 0" }}>
          <button className="btn ink" type="submit" disabled={busy} aria-busy={busy}>
            {busy ? "Checking…" : "Continue"}
          </button>
        </div>
      </form>
    </AuthCard>
  );
}
