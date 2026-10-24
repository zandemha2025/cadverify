"use client";

import { useState, type CSSProperties, type FormEvent } from "react";
import { apiProblemDetail } from "@/lib/api-recovery";
import { C, MONO } from "@/lib/verify/tokens";

async function post(path: string, body: unknown): Promise<{ ok: boolean; status: number; data: unknown }> {
  const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  return { ok: res.ok, status: res.status, data: await res.json().catch(() => null) };
}

const field: CSSProperties = {
  minHeight: 40, minWidth: 0, flex: "1 1 200px", border: `1px solid ${C.hair}`, borderRadius: 8,
  padding: "8px 12px", fontFamily: "inherit", fontSize: 14, color: C.ink, background: "#fff",
};
const primary: CSSProperties = {
  minHeight: 40, border: "none", borderRadius: 999, background: C.ink, color: "#fff",
  padding: "8px 16px", fontFamily: "inherit", fontSize: 13, fontWeight: 600, cursor: "pointer",
};
const quiet: CSSProperties = {
  border: 0, background: "none", padding: 0, color: C.ink, textDecoration: "underline",
  fontFamily: "inherit", fontSize: 12.5, cursor: "pointer",
};

/** One text, one code: the free allowance unlocks once the number is verified. */
export function PhoneGate({ onVerified }: { onVerified: () => void }) {
  const [step, setStep] = useState<"phone" | "code">("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(e?: FormEvent) {
    e?.preventDefault();
    setError(null);
    setWorking(true);
    try {
      const res = await post("/api/proxy/account/phone/start", { phone });
      const status = (res.data as { status?: unknown } | null)?.status;
      if (res.ok && status === "verified") onVerified();
      else if (res.ok) setStep("code");
      else setError(apiProblemDetail(res.data) ?? "We couldn't send a text. Try again.");
    } catch {
      setError("We couldn't send a text. Check your connection and try again.");
    } finally {
      setWorking(false);
    }
  }

  async function check(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setWorking(true);
    try {
      const res = await post("/api/proxy/account/phone/check", { phone, code });
      if (res.ok) onVerified();
      else setError(apiProblemDetail(res.data) ?? "That code didn't work. Try again.");
    } catch {
      setError("We couldn't check the code. Check your connection and try again.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <section
      role="region"
      aria-labelledby="phone-gate-title"
      data-testid="phone-gate"
      style={{ flexShrink: 0, borderBottom: `1px solid ${C.hair}`, background: "#f7f9fc", padding: "14px 20px", color: C.ink }}
    >
      <p id="phone-gate-title" style={{ margin: 0, fontSize: 14, fontWeight: 650 }}>One quick step before your free checks.</p>
      <p style={{ margin: "3px 0 10px", fontSize: 12.5, lineHeight: 1.5, color: C.ink55 }}>
        {step === "phone"
          ? "We text you a code once. It keeps free checks for real people."
          : <>Enter the code we sent to <span style={{ fontFamily: MONO }}>{phone}</span>.</>}
      </p>
      {step === "phone" ? (
        <form onSubmit={send} style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
          <label htmlFor="phone-gate-number" className="sr-only">Mobile number</label>
          <input id="phone-gate-number" type="tel" autoComplete="tel" inputMode="tel" required maxLength={32}
            placeholder="Mobile number, like +1 555 123 4567" value={phone} onChange={(e) => setPhone(e.target.value)} style={field} />
          <button type="submit" disabled={working} style={primary}>{working ? "Sending…" : "Text me a code"}</button>
        </form>
      ) : (
        <form onSubmit={check} style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
          <label htmlFor="phone-gate-code" className="sr-only">Code from the text</label>
          <input id="phone-gate-code" type="text" autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{4,10}" required maxLength={10}
            placeholder="6-digit code" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} style={{ ...field, flex: "0 1 160px", fontFamily: MONO }} />
          <button type="submit" disabled={working} style={primary}>{working ? "Checking…" : "Confirm code"}</button>
          <button type="button" onClick={() => void send()} disabled={working} style={quiet}>Send again</button>
          <button type="button" onClick={() => { setStep("phone"); setCode(""); setError(null); }} style={quiet}>Use a different number</button>
        </form>
      )}
      {error && <p role="alert" style={{ margin: "8px 0 0", fontSize: 12.5, color: "#b42318" }}>{error}</p>}
    </section>
  );
}
