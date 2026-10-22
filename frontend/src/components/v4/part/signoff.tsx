"use client";

/**
 * Sign-off on a recorded make-or-buy decision: who may sign off is the
 * organization's rule (Account › Organization); the sign-off keeps a name, a
 * time and an optional note, and says plainly when what was signed off has
 * changed since (rates, machines, specs, conditions or a calibration).
 */
import * as React from "react";
import type { CostDecisionDetail } from "@/lib/api";
import { API_BASE } from "@/lib/api-base";
import { ConfirmButton } from "../ui";
import { staleText } from "../records/words";
import "./specs.css";

export interface SignoffRule {
  signoff_role: "member" | "admin";
  label: string;
  can_sign_off: boolean;
  can_change: boolean;
}

let rule: Promise<SignoffRule | null> | null = null;

/** The org's sign-off rule for the person viewing (cached for the session). */
export function useSignoffRule(): SignoffRule | null | undefined {
  const [r, setR] = React.useState<SignoffRule | null | undefined>(undefined);
  React.useEffect(() => {
    let live = true;
    rule ??= fetch(`${API_BASE}/orgs/signoff`, { cache: "no-store" })
      .then((res) => (res.ok ? (res.json() as Promise<SignoffRule>) : null))
      .catch(() => null);
    void rule.then((v) => live && setR(v));
    return () => {
      live = false;
    };
  }, []);
  return r;
}

export function forgetSignoffRule() {
  rule = null;
}

const STALE_WORDS: Record<string, string> = {
  part_specs_changed: "The part's specs changed",
  conditions_changed: "The part's service conditions changed",
  calibration_changed: "A calibration was applied or undone",
};

export function outOfDateText(reason: string | null | undefined): string {
  const code = (reason ?? "").split(":")[0];
  return STALE_WORDS[code] ?? staleText(reason);
}

function when(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("en-US", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

async function call(id: string, method: "POST" | "DELETE", note?: string): Promise<Partial<CostDecisionDetail>> {
  const res = await fetch(`${API_BASE}/cost-decisions/${encodeURIComponent(id)}/approve`, {
    method,
    headers: method === "POST" ? { "content-type": "application/json" } : undefined,
    body: method === "POST" ? JSON.stringify({ note: note?.trim() || null }) : undefined,
    cache: "no-store",
  });
  const body = (await res.json().catch(() => null)) as Record<string, unknown> | null;
  if (!res.ok) {
    const d = body?.detail as { message?: string } | string | undefined;
    throw new Error(typeof d === "string" ? d : d?.message ?? `The sign-off wasn't saved (${res.status}).`);
  }
  return (body ?? {}) as Partial<CostDecisionDetail>;
}

export function SignOff({ id, gov, onChange }: { id: string | null; gov: CostDecisionDetail | null; onChange: (patch: Partial<CostDecisionDetail>) => void }) {
  const r = useSignoffRule();
  const [note, setNote] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  if (!id || !gov?.user_disposition) return null;
  const so = gov.signoff ?? null;
  const signed = gov.approval_status === "approved";
  const stale = !!gov.is_stale;
  const can = !!r?.can_sign_off;
  // The quantity the outcome was recorded at: what the sign-off is for (op-08).
  const at = gov.disposition_basis?.quantity ? ` · at ${gov.disposition_basis.quantity.toLocaleString("en-US")} parts` : "";

  const run = async (method: "POST" | "DELETE") => {
    setBusy(true);
    setErr(null);
    try {
      const res = await call(id, method, note);
      onChange(res);
      if (method === "POST") setNote("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The sign-off wasn't saved.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="signoff" aria-live="polite">
      <div className="who">
        <b style={{ fontWeight: 600 }}>Sign-off</b>
        {signed ? (
          <span>
            {so?.by ?? "Signed off"} · {when(so?.at ?? gov.approved_at)}
            {at}
            {(so?.note ?? gov.approval_note) ? ` · “${so?.note ?? gov.approval_note}”` : ""}
          </span>
        ) : (
          <span style={{ color: "var(--ink3)" }}>Not signed off · {r ? r.label.toLowerCase() : "…"} sign off</span>
        )}
      </div>
      {stale ? (
        <div className="stale" role="note">
          <b style={{ fontWeight: 600 }}>{signed ? "Out of date since it was signed off" : "Out of date"}:</b> {outOfDateText(gov.stale_reason)}
          {gov.stale_at ? ` (${when(gov.stale_at)})` : ""}. Check the part again{signed ? " and sign off the new record" : " before signing off"}.
        </div>
      ) : null}
      {!signed && !stale && can ? (
        <>
          <label className="field">
            Note with the sign-off, optional
            <input type="text" maxLength={1000} value={note} placeholder="Reviewed with production" onChange={(e) => setNote(e.target.value)} />
          </label>
          <span style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn sm ink" type="button" disabled={busy} onClick={() => void run("POST")}>
              {busy ? "Signing off…" : "Sign off"}
            </button>
            <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>
              Signs off {gov.user_disposition_label ?? "the outcome"}{at.replace(" · ", " ")}. Your name and the time go on the record. A changed outcome or quantity reopens it.
            </span>
          </span>
        </>
      ) : null}
      {!signed && !can && r ? <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{r.signoff_role === "admin" ? "Admins sign off decisions in this organization." : "Viewers can't sign off."}</span> : null}
      {signed && can ? (
        <span>
          <ConfirmButton className="btn sm ghost" label="Reopen sign-off" question="Reopen the sign-off? The record goes back to not signed off." confirmLabel="Reopen" onConfirm={() => run("DELETE")} disabled={busy} />
        </span>
      ) : null}
      {err ? (
        <p role="alert" style={{ margin: 0, color: "var(--bad)", fontSize: 12.5 }}>
          {err}
        </p>
      ) : null}
    </div>
  );
}
