"use client";

/**
 * Rates › Finishing, heat treatment and inspection: the prices and lead days a
 * declared part spec adds, typical (each with its source) or your own from the
 * rate card in effect. A change is a new rate-card version sent for review, like
 * the labor rate; every other value is copied from the card in effect.
 */
import * as React from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/api-base";
import { R } from "../routes";
import { Loading, Panel, Src } from "../ui";
import { Banner, isOrgAdmin, type useOrg } from "./common";
import { ShopApiError, createRateDraft, discardRateDraft, proposeChange, updateRateDraft } from "./shop-api";
import type { RateVersionLike } from "./shop-derive";

type Fields = Record<string, number>;
interface SpecOp {
  op: string;
  label: string;
  group: "finish" | "heat" | "inspection";
  kind: "area" | "mass" | "labor";
  typical: Fields;
  source: string;
  yours: Fields;
}

const GROUPS: [SpecOp["group"], string][] = [
  ["finish", "Finishing"],
  ["heat", "Heat treatment"],
  ["inspection", "Inspection and fine finish"],
];
const FIELD_LABEL: Record<string, string> = {
  lot_usd: "Lot minimum, $",
  per_m2_usd: "Per m² of surface, $",
  per_kg_usd: "Per kg, $",
  hr_per_order: "Hours per order",
  hr_per_part: "Hours per part",
  hr_per_dm2: "Hours per dm² of surface",
  lead_days: "Lead days",
};
const SQFT_PER_M2 = 10.763910417;

function money(v: number): string {
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: v % 1 ? 2 : 0, maximumFractionDigits: 2 })}`;
}

/** "$125 lot minimum · $16.15/m² ($1.50/ft²) · 5 days". */
export function specOpLine(kind: SpecOp["kind"], f: Fields): string {
  const bits: string[] = [];
  if (kind === "area") {
    bits.push(`${money(f.lot_usd ?? 0)} lot minimum`, `${money(f.per_m2_usd ?? 0)}/m² (${money((f.per_m2_usd ?? 0) / SQFT_PER_M2)}/ft²)`);
  } else if (kind === "mass") {
    bits.push(`${money(f.lot_usd ?? 0)} furnace-load minimum`, `${money(f.per_kg_usd ?? 0)}/kg`);
  } else {
    if (f.hr_per_order) bits.push(`${f.hr_per_order} h per order`);
    if (f.hr_per_part) bits.push(`${f.hr_per_part} h per part`);
    if (f.hr_per_dm2) bits.push(`${f.hr_per_dm2} h per dm²`);
    bits.push("at your labor rate");
  }
  if (f.lead_days) bits.push(`${f.lead_days} ${f.lead_days === 1 ? "day" : "days"}`);
  return bits.join(" · ");
}

export function SpecRates({ org, baseVersion, inEffectName, onSent }: { org: ReturnType<typeof useOrg>; baseVersion: RateVersionLike | null; inEffectName: string; onSent: () => void }) {
  const [ops, setOps] = React.useState<SpecOp[] | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [n, setN] = React.useState(0);
  const [edit, setEdit] = React.useState<string | null>(null);
  const [vals, setVals] = React.useState<Record<string, string>>({});
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState<{ ok: boolean; text: string } | null>(null);
  const admin = isOrgAdmin(org);
  React.useEffect(() => {
    let live = true;
    setErr(null);
    fetch(`${API_BASE}/rate-library/spec-defaults`, { cache: "no-store" })
      .then(async (r) => (r.ok ? ((await r.json()) as { ops: SpecOp[] }) : Promise.reject(new Error(`(${r.status})`))))
      .then((b) => live && setOps(b.ops), (e: Error) => live && setErr(e.message));
    return () => {
      live = false;
    };
  }, [n]);

  const open = (o: SpecOp) => {
    const cur = { ...o.typical, ...o.yours };
    setEdit(o.op);
    setMsg(null);
    setVals(Object.fromEntries(Object.keys(o.typical).map((k) => [k, String(cur[k] ?? "")])));
  };

  const send = async (o: SpecOp) => {
    const out: Fields = {};
    for (const [k, raw] of Object.entries(vals)) {
      const v = Number(raw.trim().replace(/^\$/, ""));
      if (!raw.trim() || !Number.isFinite(v) || v < 0) {
        setMsg({ ok: false, text: `${FIELD_LABEL[k] ?? k} must be a number, 0 or more.` });
        return;
      }
      if (v !== o.typical[k] || k in o.yours) out[k] = v;
    }
    setBusy(true);
    setMsg(null);
    let draftId: number | null = null;
    try {
      const note = `${o.label}: ${specOpLine(o.kind, { ...o.typical, ...o.yours, ...out })}`;
      const draft = await createRateDraft({ name: o.label, change_note: note, from_version_id: baseVersion ? Number(baseVersion.id) : null });
      draftId = draft.id;
      const pay = (draft.payload ?? {}) as Record<string, unknown>;
      const specOps = { ...((pay.spec_ops as Record<string, Fields>) ?? {}), [o.op]: out };
      if (!Object.keys(out).length) delete specOps[o.op];
      await updateRateDraft(draft.id, { payload: { ...pay, spec_ops: specOps } });
      await proposeChange({ asset_type: "rate_card", target_version_id: draft.id, title: `Rate card v${draft.version}: ${o.label.toLowerCase()}`, note });
      setMsg({ ok: true, text: `v${draft.version} sent for review. ${inEffectName} stays in use until approved.` });
      setEdit(null);
      onSent();
    } catch (e) {
      if (draftId != null) await discardRateDraft(draftId).catch(() => {});
      setMsg({ ok: false, text: e instanceof ShopApiError && e.status === 403 ? "Only an organization admin can draft rates." : e instanceof Error ? e.message : "Couldn't send it for review." });
    } finally {
      setBusy(false);
    }
  };

  const yoursCount = (ops ?? []).filter((o) => Object.keys(o.yours).length).length;
  return (
    <Panel title="Finishing, heat treatment and inspection" note={ops ? (yoursCount ? `${yoursCount} yours` : "Typical") : undefined}>
      <p className="fh" style={{ margin: "0 16px 8px" }}>
        What a declared part spec adds to a price, per order and per part. Typical values say where they come from; set your own supplier&apos;s or shop&apos;s numbers.
      </p>
      {err ? (
        <div style={{ padding: "0 16px 12px" }}>
          <Banner tone="bad" alert actions={<button className="btn sm" type="button" onClick={() => setN((x) => x + 1)}>Retry</button>}>
            <b>Couldn&apos;t read the spec prices.</b> {err}
          </Banner>
        </div>
      ) : !ops ? (
        <Loading rows={3} label="Reading the spec prices" />
      ) : (
        <div style={{ padding: "0 16px 8px" }}>
          {GROUPS.map(([g, name]) => (
            <div key={g} role="group" aria-label={name}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--ink3)", margin: "8px 0 2px" }}>{name}</div>
              {ops.filter((o) => o.group === g || (g === "inspection" && o.op === "fine_finish")).filter((o) => g !== "finish" || o.op !== "fine_finish").map((o) => {
                const mine = Object.keys(o.yours).length > 0;
                return (
                  <div key={o.op}>
                    <div className="rk">
                      <span>
                        {o.label} <Src kind={mine ? "yours" : "typ"}>{mine ? "Yours" : "Typical"}</Src>
                        <small title={o.source}>{mine ? "From your rate card" : o.source}</small>
                      </span>
                      <b className="num" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", justifyContent: "flex-end" }}>
                        {specOpLine(o.kind, { ...o.typical, ...o.yours })}
                        {admin && edit !== o.op ? (
                          <button className="btn sm ghost" type="button" onClick={() => open(o)} aria-label={`Change ${o.label}`}>
                            Change
                          </button>
                        ) : null}
                      </b>
                    </div>
                    {edit === o.op ? (
                      <div className="draft" style={{ flexWrap: "wrap" }}>
                        {Object.keys(o.typical).map((k) => (
                          <label className="field" key={k}>
                            {FIELD_LABEL[k] ?? k}
                            <input type="text" inputMode="decimal" value={vals[k] ?? ""} onChange={(e) => setVals((v) => ({ ...v, [k]: e.target.value }))} />
                          </label>
                        ))}
                        <button className="btn ink sm" type="button" disabled={busy} onClick={() => void send(o)}>
                          {busy ? "Sending…" : "Send for review"}
                        </button>
                        <button className="btn sm" type="button" disabled={busy} onClick={() => setEdit(null)}>
                          Cancel
                        </button>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
      <p className="fh" role={msg && !msg.ok ? "alert" : undefined} aria-live="polite" style={{ margin: "0 16px 12px", color: msg && !msg.ok ? "var(--bad)" : undefined }}>
        {msg ? msg.text : admin ? (
          <>Changes go to <Link href={R.changes}>Changes to review</Link> as a new card version.</>
        ) : (
          "Admins change these; a change is reviewed like any rate card version."
        )}
      </p>
    </Panel>
  );
}
