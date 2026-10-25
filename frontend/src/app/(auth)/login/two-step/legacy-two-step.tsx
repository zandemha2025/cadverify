"use client";

/** Two-step sign-in on the pre-v4 auth frame (same flow as the v4 card). */
import * as React from "react";
import { useSearchParams } from "next/navigation";
import { AuthField, AuthFrame, AuthSubmit, AuthTextLink } from "@/components/auth/auth-frame";
import { ManualKey, QrCode, RecoveryCodes, SUPPORT_EMAIL, cleanCode } from "@/components/two-step/parts";
import { useTwoStepSignIn } from "@/components/two-step/use-two-step-sign-in";
import { safeLocalPath } from "@/lib/safe-return-path";

export function LegacyTwoStep() {
  const params = useSearchParams();
  const next = safeLocalPath(params.get("next"), "/verify");
  const flow = useTwoStepSignIn({
    onDone: (used) => {
      window.location.href = used === "recovery" ? "/settings/security?recovery=used" : next;
    },
  });
  const [code, setCode] = React.useState("");
  const [recovery, setRecovery] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const { state, phase, busy, error } = flow;
  const lost = (
    <span style={{ fontSize: 12 }}>
      Lost your phone and your recovery codes? Email <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>.
    </span>
  );

  if (phase.kind === "loading")
    return (
      <AuthFrame eyebrow="Two-step sign-in" title="Checking this sign-in" body="">
        {null}
      </AuthFrame>
    );
  if (phase.kind === "expired")
    return (
      <AuthFrame eyebrow="Two-step sign-in" title="Sign in again" body={phase.message}>
        <AuthTextLink href="/login">Sign in</AuthTextLink>
      </AuthFrame>
    );
  if (phase.kind === "codes")
    return (
      <AuthFrame eyebrow="Two-step sign-in is on" title="Save your recovery codes" body="Each code signs you in once if your phone isn't with you. Shown once.">
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <RecoveryCodes codes={phase.codes} account={state?.email ?? ""} />
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} /> I saved these codes
          </label>
          <AuthSubmit type="button" disabled={!saved} onClick={flow.finishSetup}>
            Continue
          </AuthSubmit>
        </div>
      </AuthFrame>
    );
  if (phase.kind === "setup") {
    const enrol = phase.enrolment;
    return (
      <AuthFrame
        eyebrow="Two-step sign-in"
        title="Set up two-step sign-in"
        body={`${state?.required_by.length ? state.required_by.join(", ") : "Your organization"} requires a code from an authenticator app. Scan the QR code, then enter the code it shows.`}
        footer={lost}
      >
        <form
          style={{ display: "flex", flexDirection: "column", gap: 14 }}
          onSubmit={(e) => {
            e.preventDefault();
            if (cleanCode(code).length !== 6) return flow.setError("Enter the 6-digit code from your authenticator app.");
            void flow.confirmSetup(cleanCode(code));
          }}
        >
          {enrol ? (
            <>
              <QrCode rows={enrol.qr} size={168} label="QR code for your authenticator app" />
              <ManualKey value={enrol.manual_key} />
            </>
          ) : null}
          <AuthField id="ts-code" label="6-digit code" inputMode="numeric" autoComplete="one-time-code" maxLength={7} value={code} error={error} onChange={(e) => setCode(e.target.value)} />
          <AuthSubmit loading={busy} disabled={!enrol}>
            Turn on and continue
          </AuthSubmit>
        </form>
      </AuthFrame>
    );
  }
  return (
    <AuthFrame eyebrow="Two-step sign-in" title={recovery ? "Enter a recovery code" : "Enter your code"} body={state?.email ?? ""} footer={lost}>
      <form
        style={{ display: "flex", flexDirection: "column", gap: 14 }}
        onSubmit={(e) => {
          e.preventDefault();
          if (recovery) return void flow.verify({ recovery_code: code });
          if (cleanCode(code).length !== 6) return flow.setError("Enter the 6-digit code from your authenticator app.");
          void flow.verify({ code: cleanCode(code) });
        }}
      >
        <AuthField
          id="ts-code"
          label={recovery ? "Recovery code" : "6-digit code from your authenticator app"}
          inputMode={recovery ? "text" : "numeric"}
          autoComplete={recovery ? "off" : "one-time-code"}
          maxLength={recovery ? 16 : 7}
          value={code}
          error={error}
          onChange={(e) => setCode(e.target.value)}
        />
        <AuthSubmit loading={busy}>Continue</AuthSubmit>
        <button
          type="button"
          onClick={() => {
            setRecovery((r) => !r);
            setCode("");
            flow.setError(null);
          }}
          style={{ all: "unset", cursor: "pointer", textAlign: "center", fontSize: 13, textDecoration: "underline" }}
        >
          {recovery ? "Use the app instead" : "Use a recovery code"}
        </button>
      </form>
    </AuthFrame>
  );
}
