"use client";

/**
 * Two-step sign-in in Account › Security: turn it on (QR code or key, then the
 * first code; the ten recovery codes are shown once), make new recovery codes,
 * and turn it off (a current code or a recovery code; refused while an
 * organization requires it). Every action goes through /api/auth/two-step/*,
 * which keeps any new session token server-side.
 */
import * as React from "react";
import { ManualKey, QrCode, RecoveryCodes, cleanCode, twoStepError } from "@/components/two-step/parts";
import { Chip, Panel } from "../ui";

export type TwoStepStatus = {
  enabled: boolean;
  enabled_at: string | null;
  recovery_codes_left: number;
  required_by: string[];
  locked_until: string | null;
};

type Enrolment = { manual_key: string; qr: string[]; account: string };

type Mode =
  | { kind: "idle" }
  | { kind: "enrol"; enrolment: Enrolment }
  | { kind: "codes"; codes: string[]; title: string }
  | { kind: "prove"; purpose: "disable" | "recovery-codes" };

async function call(action: string, method: "GET" | "POST", body?: unknown) {
  const res = await fetch(`/api/auth/two-step/${action}`, {
    method,
    headers: method === "POST" ? { "content-type": "application/json" } : undefined,
    body: method === "POST" ? JSON.stringify(body ?? {}) : undefined,
    cache: "no-store",
  });
  return { res, data: (await res.json().catch(() => ({}))) as Record<string, unknown> };
}

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function useTwoStepStatus() {
  const [status, setStatus] = React.useState<TwoStepStatus | null>(null);
  const [failed, setFailed] = React.useState(false);
  const load = React.useCallback(async () => {
    try {
      const { res, data } = await call("status", "GET");
      if (!res.ok) throw new Error();
      setStatus(data as unknown as TwoStepStatus);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);
  React.useEffect(() => {
    void load();
  }, [load]);
  return { status, setStatus, failed, reload: load };
}

export function TwoStepPanel({
  email,
  status,
  setStatus,
  failed,
  recoveryUsed,
}: {
  email: string | null;
  status: TwoStepStatus | null;
  setStatus: (s: TwoStepStatus) => void;
  failed: boolean;
  recoveryUsed: boolean;
}) {
  const [mode, setMode] = React.useState<Mode>({ kind: "idle" });
  const [code, setCode] = React.useState("");
  const [useRecovery, setUseRecovery] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [saved, setSaved] = React.useState(false);

  function reset(next: Mode = { kind: "idle" }) {
    setMode(next);
    setCode("");
    setUseRecovery(false);
    setErr(null);
    setSaved(false);
  }

  async function start() {
    setBusy(true);
    setErr(null);
    try {
      const { res, data } = await call("enrol", "POST");
      if (!res.ok) return setErr(twoStepError(res.status, data, "Couldn't start two-step setup."));
      reset({ kind: "enrol", enrolment: data as unknown as Enrolment });
    } catch {
      setErr("Couldn't reach the sign-in service. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    if (cleanCode(code).length !== 6) return setErr("Enter the 6-digit code from your authenticator app.");
    setBusy(true);
    setErr(null);
    try {
      const { res, data } = await call("enrol-confirm", "POST", { code: cleanCode(code) });
      if (!res.ok) return setErr(twoStepError(res.status, data, "That code didn't match."));
      setStatus(data.status as TwoStepStatus);
      reset({ kind: "codes", codes: (data.recovery_codes as string[]) ?? [], title: "Two-step sign-in is on. Save your recovery codes" });
    } catch {
      setErr("Couldn't reach the sign-in service. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function prove(e: React.FormEvent, purpose: "disable" | "recovery-codes") {
    e.preventDefault();
    const body = useRecovery ? { recovery_code: code } : { code: cleanCode(code) };
    if (!useRecovery && cleanCode(code).length !== 6) return setErr("Enter the 6-digit code from your authenticator app.");
    setBusy(true);
    setErr(null);
    try {
      const { res, data } = await call(purpose, "POST", body);
      if (!res.ok) return setErr(twoStepError(res.status, data, "That code didn't match."));
      if (purpose === "disable") {
        setStatus(data as unknown as TwoStepStatus);
        reset();
      } else {
        setStatus(data.status as TwoStepStatus);
        reset({ kind: "codes", codes: (data.recovery_codes as string[]) ?? [], title: "New recovery codes. The old ones no longer work" });
      }
    } catch {
      setErr("Couldn't reach the sign-in service. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const on = Boolean(status?.enabled);
  const required = status?.required_by ?? [];
  const codeField = (label: string) => (
    <label className="field">
      {useRecovery ? "Recovery code" : label}
      <input
        inputMode={useRecovery ? "text" : "numeric"}
        autoComplete={useRecovery ? "off" : "one-time-code"}
        maxLength={useRecovery ? 16 : 7}
        value={code}
        onChange={(e) => setCode(e.target.value)}
        aria-invalid={err ? true : undefined}
        autoFocus
      />
    </label>
  );

  return (
    <Panel title="Two-step sign-in" note="Authenticator app" actions={<Chip tone={on ? "ok" : "unk"}>{status ? (on ? "On" : "Off") : "…"}</Chip>}>
      {failed ? (
        <div className="a-row2">
          <span className="a-err">Couldn&rsquo;t read your two-step setting. Reload the page.</span>
        </div>
      ) : null}
      {recoveryUsed && on ? (
        <div className="a-row2" role="status">
          <span>
            <b>You signed in with a recovery code</b>
            <small>{status?.recovery_codes_left ?? 0} left. Make new ones if you&rsquo;re running low or lost your phone.</small>
          </span>
        </div>
      ) : null}

      {mode.kind === "codes" ? (
        <div className="a-pf" style={{ maxWidth: 520 }}>
          <b>{mode.title}</b>
          <span className="a-fh">Shown once. Each code signs you in once if your phone isn&rsquo;t with you.</span>
          <RecoveryCodes codes={mode.codes} account={email ?? ""} />
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} /> I saved these codes
          </label>
          <span>
            <button className="btn ink sm" type="button" disabled={!saved} onClick={() => reset()}>
              Done
            </button>
          </span>
        </div>
      ) : mode.kind === "enrol" ? (
        <form className="a-pf" style={{ maxWidth: 560 }} onSubmit={confirm} noValidate>
          <span>1. In an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, Authy), add an account by scanning this code.</span>
          <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
            <QrCode rows={mode.enrolment.qr} size={168} label="QR code for your authenticator app" />
            <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0, flex: "1 1 180px" }}>
              <span className="a-fh">Can&rsquo;t scan? Type this key:</span>
              <ManualKey value={mode.enrolment.manual_key} />
            </div>
          </div>
          {codeField("2. The 6-digit code the app shows")}
          {err ? (
            <span className="a-err" role="alert">
              {err}
            </span>
          ) : null}
          <span style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn ink sm" type="submit" disabled={busy} aria-busy={busy}>
              {busy ? "Checking…" : "Turn on"}
            </button>
            <button className="btn sm" type="button" onClick={() => reset()} disabled={busy}>
              Cancel
            </button>
            <span className="a-fh">Turning it on signs out your other browsers.</span>
          </span>
        </form>
      ) : mode.kind === "prove" ? (
        <form className="a-pf" onSubmit={(e) => prove(e, mode.purpose)} noValidate>
          <b>{mode.purpose === "disable" ? "Turn off two-step sign-in?" : "Make new recovery codes?"}</b>
          <span className="a-fh">
            {mode.purpose === "disable"
              ? "Sign-in then needs only your password or an email link."
              : "Your current recovery codes stop working."}
          </span>
          {codeField("Current 6-digit code")}
          {err ? (
            <span className="a-err" role="alert">
              {err}
            </span>
          ) : null}
          <span style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button className={mode.purpose === "disable" ? "btn sm a-danger" : "btn ink sm"} type="submit" disabled={busy} aria-busy={busy}>
              {busy ? "Checking…" : mode.purpose === "disable" ? "Turn off" : "Make new codes"}
            </button>
            <button className="btn sm" type="button" onClick={() => reset()} disabled={busy}>
              Cancel
            </button>
            <button
              className="btn sm"
              type="button"
              onClick={() => {
                setUseRecovery((r) => !r);
                setCode("");
                setErr(null);
              }}
            >
              {useRecovery ? "Use the app instead" : "Use a recovery code"}
            </button>
          </span>
        </form>
      ) : on ? (
        <>
          <div className="a-row2">
            <span>
              <b>Code from your authenticator app</b>
              <small>
                Asked after a password, email-link or Google sign-in{status?.enabled_at ? `. On since ${when(status.enabled_at)}` : ""}.
              </small>
            </span>
            <Chip tone="ok">On</Chip>
          </div>
          <div className="a-row2">
            <span>
              <b>Recovery codes</b>
              <small>{status?.recovery_codes_left ?? 0} of 10 unused.</small>
            </span>
            <button className="btn sm" type="button" onClick={() => reset({ kind: "prove", purpose: "recovery-codes" })}>
              New codes
            </button>
          </div>
          <div className="a-row2">
            <span>
              <b>Turn off</b>
              <small>
                {required.length
                  ? `${required.join(", ")} requires two-step sign-in, so it stays on. An admin can change that in Members.`
                  : "Needs a current code or a recovery code."}
              </small>
            </span>
            <button className="btn sm" type="button" disabled={required.length > 0} onClick={() => reset({ kind: "prove", purpose: "disable" })}>
              Turn off
            </button>
          </div>
        </>
      ) : (
        <div className="a-row2">
          <span>
            <b>Ask for a code at sign-in</b>
            <small>
              A 6-digit code from an authenticator app on your phone, after your password or email link. Single sign-on uses your
              identity provider&rsquo;s own checks.
            </small>
            {err ? (
              <span className="a-err" role="alert">
                {err}
              </span>
            ) : null}
          </span>
          <button className="btn ink sm" type="button" onClick={start} disabled={busy || !status} aria-busy={busy}>
            {busy ? "Starting…" : "Turn on"}
          </button>
        </div>
      )}
    </Panel>
  );
}
