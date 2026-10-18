"use client";

/**
 * Phone check (board X2): one text, one code, then the free checks start. Same
 * calls as today's gate: POST /account/phone/start { phone } and
 * POST /account/phone/check { phone, code }. The server owns every rule (one
 * number per account, 5 codes an hour, code expiry); this shows its answers.
 *
 * `<PhoneGate>` is the sheet (an `<aside class="sheet">`):
 * - `onVerified()`   called once the number is verified (usage is refreshed for you).
 * - `onContinue()`   optional; the done step shows a button that calls it.
 * - `continueLabel`  that button's text (default "Open part").
 *
 * `<PhoneGateView>` is the whole screen: the waiting part on the stage plus the sheet.
 * Same props, plus `fileName` (the part that checks after verification, if any).
 */
import * as React from "react";
import { apiProblemDetail } from "@/lib/api-recovery";
import { cx } from "../ui";
import { useUsage } from "./out-of-checks";
import "./moments.css";

const RESEND_S = 30;
const BOXES = 6;

async function post(path: string, body: unknown): Promise<{ ok: boolean; status: number; data: unknown }> {
  const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  return { ok: res.ok, status: res.status, data: await res.json().catch(() => null) };
}

function mmss(s: number): string {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function PhoneGate({
  onVerified,
  onContinue,
  continueLabel = "Open part",
}: {
  onVerified: () => void;
  onContinue?: () => void;
  continueLabel?: string;
}) {
  const usage = useUsage();
  const [step, setStep] = React.useState<"phone" | "code" | "done">("phone");
  const [phone, setPhone] = React.useState("");
  const [code, setCode] = React.useState("");
  const [working, setWorking] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [badCode, setBadCode] = React.useState(false);
  const [left, setLeft] = React.useState(0);
  const tried = React.useRef("");
  const codeRef = React.useRef<HTMLInputElement>(null);
  const phoneRef = React.useRef<HTMLInputElement>(null);
  const doneRef = React.useRef<HTMLHeadingElement>(null);

  React.useEffect(() => {
    if (step !== "code" || left <= 0) return;
    const t = window.setTimeout(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => window.clearTimeout(t);
  }, [step, left]);

  const verified = React.useCallback(() => {
    setStep("done");
    setError(null);
    window.dispatchEvent(new Event("proofshape:usage-changed"));
    onVerified();
  }, [onVerified]);

  // Move focus with the step, but never on first render (the host decides that).
  const shown = React.useRef(step);
  React.useEffect(() => {
    if (shown.current === step) return;
    shown.current = step;
    if (step === "code") codeRef.current?.focus();
    if (step === "phone") phoneRef.current?.focus();
    if (step === "done") doneRef.current?.focus();
  }, [step]);

  async function send() {
    if (working) return;
    setError(null);
    setBadCode(false);
    setWorking(true);
    try {
      const res = await post("/api/proxy/account/phone/start", { phone });
      const status = (res.data as { status?: unknown } | null)?.status;
      if (res.ok && status === "verified") verified();
      else if (res.ok) {
        setStep("code");
        setCode("");
        tried.current = "";
        setLeft(RESEND_S);
      } else setError(apiProblemDetail(res.data) ?? "We couldn't send a text. Try again.");
    } catch {
      setError("We couldn't send a text. Check your connection and try again.");
    } finally {
      setWorking(false);
    }
  }

  async function check(value = code) {
    if (working || value.length < 4) return;
    tried.current = value;
    setError(null);
    setBadCode(false);
    setWorking(true);
    try {
      const res = await post("/api/proxy/account/phone/check", { phone, code: value });
      if (res.ok) verified();
      else {
        setError(apiProblemDetail(res.data) ?? "That code didn't work. Check it and try again.");
        setBadCode(true);
      }
    } catch {
      setError("We couldn't check the code. Check your connection and try again.");
    } finally {
      setWorking(false);
    }
  }

  const lead =
    step === "phone"
      ? ["Verify your phone", "Required for free checks · one text with a code"]
      : step === "code"
        ? ["Enter code", `Sent to ${phone}`]
        : ["Phone verified", usage?.cap ? `${usage.cap} free checks · ${usage.tier === "personal" ? "personal" : "work"} email` : "Free checks unlocked"];
  const boxes = Math.max(BOXES, Math.min(10, code.length));
  const canConfirm = code.length >= 4 && !working;

  return (
    <aside className="sheet" aria-label="Verify your phone">
      <div className="top" style={{ borderBottom: 0, paddingBottom: 8 }}>
        <h1 className="ptitle" ref={doneRef} tabIndex={-1} style={{ outline: "none" }}>
          {lead[0]}
        </h1>
        <p className="pmeta" style={{ marginTop: 6 }}>
          <span style={{ overflowWrap: "anywhere" }}>{lead[1]}</span>
        </p>
      </div>
      <div className="prog" aria-hidden="true">
        <i className="on" />
        <i className={cx(step !== "phone" && "on")} />
        <i className={cx(step === "done" && "on")} />
      </div>

      {step === "phone" ? (
        <form
          className="form swap"
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
        >
          <label className="field">
            Mobile number
            <input
              ref={phoneRef}
              type="tel"
              autoComplete="tel"
              inputMode="tel"
              required
              maxLength={32}
              placeholder="+1 555 123 4567"
              value={phone}
              aria-invalid={error ? true : undefined}
              aria-describedby="mo-phone-help"
              onChange={(e) => setPhone(e.target.value)}
            />
          </label>
          <span className="hintx" id="mo-phone-help">
            Include the country code, e.g. +1 555 123 4567
          </span>
          {error ? (
            <p className="err" role="alert">
              {error}
            </p>
          ) : null}
          <button className="btn ink big" type="submit" disabled={working || !phone.trim()}>
            {working ? "Sending…" : "Send code"}
          </button>
        </form>
      ) : null}

      {step === "code" ? (
        <form
          className="form swap"
          onSubmit={(e) => {
            e.preventDefault();
            void check();
          }}
        >
          <div className={cx("boxes", badCode && "bad")} style={{ gridTemplateColumns: `repeat(${boxes}, minmax(0,1fr))` }}>
            {Array.from({ length: boxes }, (_, i) => (
              <span key={i} className={cx(!badCode && i === Math.min(code.length, boxes - 1) && "on")} aria-hidden="true">
                {code[i] ?? ""}
              </span>
            ))}
            <input
              ref={codeRef}
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{4,10}"
              maxLength={10}
              value={code}
              aria-label="Code from the text"
              aria-invalid={badCode ? true : undefined}
              aria-describedby={error ? "mo-code-err" : undefined}
              onChange={(e) => {
                const v = e.target.value.replace(/\D/g, "").slice(0, 10);
                setCode(v);
                setBadCode(false);
                if (v.length === BOXES && tried.current !== v) void check(v);
              }}
            />
          </div>
          {error ? (
            <p className="err" role="alert" id="mo-code-err">
              {error}
            </p>
          ) : null}
          <button className="btn ink big" type="submit" aria-disabled={!canConfirm}>
            {working ? "Checking…" : "Confirm"}
          </button>
          <div className="row">
            <button
              className="btn ghost sm"
              type="button"
              aria-disabled={left > 0 || working}
              onClick={() => {
                if (left <= 0 && !working) void send();
              }}
            >
              {left > 0 ? `Resend in ${mmss(left)}` : "Resend"}
            </button>
            <button
              className="btn ghost sm"
              type="button"
              onClick={() => {
                setStep("phone");
                setCode("");
                setError(null);
                setBadCode(false);
              }}
            >
              Change number
            </button>
          </div>
          <span className="hintx">Up to 5 codes an hour</span>
        </form>
      ) : null}

      {step === "done" ? (
        <div className="form swap" role="status">
          <span className="done" aria-hidden="true">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
              <path d="m5 12.5 4.5 4.5L19 7.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <div className="kv" style={{ padding: 0 }}>
            <span>Phone</span>
            <b className="num">{phone || "Verified"}</b>
            <span>Free checks</span>
            <b>{usage?.cap ? `${usage.cap}, ${usage.tier === "personal" ? "personal" : "work"} email` : "Unlocked"}</b>
          </div>
          {onContinue ? (
            <button className="btn ink big" type="button" onClick={onContinue}>
              {continueLabel}
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="why">
        <b>One number per account</b>
        <span>Free checks are per person, so a number can be linked to one ScaleCAD account.</span>
      </div>
    </aside>
  );
}

/** The whole X2 screen: the part waiting on the stage, the phone sheet on the right. */
export function PhoneGateView({
  fileName,
  onVerified,
  onContinue,
  continueLabel,
}: {
  fileName?: string | null;
  onVerified: () => void;
  onContinue?: () => void;
  continueLabel?: string;
}) {
  const [done, setDone] = React.useState(false);
  return (
    <main className="world mo-x2" aria-label="Verify your phone">
      <section className="stage" aria-label="Your part, waiting">
        {fileName ? (
          <div className="wait swap">
            <div className={cx("pic", !done && "dim")} aria-hidden="true">
              <span className="shade" />
              <PartGlyph />
            </div>
            <b>{fileName}</b>
            <span>{done ? "Ready to check" : "Checks after verification"}</span>
          </div>
        ) : (
          <div className="wait swap">
            <div className="pic dim" aria-hidden="true">
              <span className="shade" />
              <PartGlyph />
            </div>
            <b>No part waiting</b>
            <span>Check a part once your number is verified</span>
          </div>
        )}
      </section>
      <PhoneGate
        onVerified={() => {
          setDone(true);
          onVerified();
        }}
        onContinue={onContinue}
        continueLabel={continueLabel}
      />
    </main>
  );
}

/** A neutral block drawn for a part that hasn't been read yet (no geometry is claimed). */
export function PartGlyph({ size = 180 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" fill="none" aria-hidden="true">
      <path d="M60 14 102 38v44L60 106 18 82V38L60 14Z" fill="#fff" stroke="rgba(20,24,31,.28)" strokeWidth="2" strokeLinejoin="round" />
      <path d="M18 38 60 62l42-24M60 62v44" stroke="rgba(20,24,31,.22)" strokeWidth="2" strokeLinejoin="round" />
      <ellipse cx="60" cy="38" rx="12" ry="7" stroke="rgba(20,24,31,.22)" strokeWidth="2" />
    </svg>
  );
}
