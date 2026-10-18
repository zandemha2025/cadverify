"use client";

/**
 * The selected machine (board O9's right sheet): figures, the declared spec,
 * printer details, the rate it carries and the rate card around it, and the
 * saved records whose recommended method matches (a method match, not a fit).
 */
import * as React from "react";
import Link from "next/link";
import type { OwnedMachine } from "@/lib/verify/machine-api";
import { capitalPercentText, printerFieldsFor } from "@/lib/verify/machine-form";
import { R } from "../routes";
import { cx } from "../ui";
import type { RateCardState } from "./common";
import type { RecordSummary } from "./shop-api";
import { envelopeOf, longDate, machineName, machineStatus, perHour, plain, procName, procShort, shortWhen } from "./shop-derive";

const ENCLOSURE_TEXT: Record<string, string> = { none: "Open", enclosed: "Closed, not heated", heated: "Heated chamber" };

function num(cap: Record<string, unknown>, k: string): number | null {
  const v = cap[k];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** The printer rows to show, from what's declared. Empty when this method has no printer fields. */
export function printerRows(m: OwnedMachine): [string, string][] {
  const shown = printerFieldsFor(m.process);
  if (!shown.any) return [];
  const cap = m.capabilities ?? {};
  const rows: [string, string][] = [];
  const not = "Not declared";
  if (shown.nozzle) {
    const n = num(cap, "nozzle_dia_mm");
    rows.push(["Nozzle", n != null ? `${plain(n)} mm` : not]);
  }
  if (shown.layers) {
    const lo = num(cap, "min_layer_um");
    const hi = num(cap, "max_layer_um");
    const mm = (u: number) => plain(u / 1000);
    rows.push(["Layer height", lo != null && hi != null ? `${mm(lo)}–${mm(hi)} mm` : lo != null ? `from ${mm(lo)} mm` : hi != null ? `up to ${mm(hi)} mm` : not]);
  }
  if (shown.enclosure) {
    const e = typeof cap.enclosure === "string" ? cap.enclosure : null;
    const c = num(cap, "max_chamber_c");
    rows.push(["Enclosure", e ? `${ENCLOSURE_TEXT[e] ?? e}${e === "heated" && c != null ? `, up to ${plain(c)} °C` : ""}` : not]);
  }
  if (shown.stocked) {
    const s = Array.isArray(cap.stocked_materials) ? (cap.stocked_materials as unknown[]).filter((x): x is string => typeof x === "string") : [];
    rows.push([m.process === "fdm" ? "Filament in stock" : "Resin in stock", s.length ? s.join(", ") : not]);
  }
  return rows;
}

export function MachineSheet({
  m,
  records,
  recordsError,
  onRetryRecords,
  rc,
  onEdit,
  onDelete,
}: {
  m: OwnedMachine;
  records: RecordSummary[] | null;
  recordsError: string | null;
  onRetryRecords: () => void;
  rc: RateCardState;
  onEdit: () => void;
  onDelete: () => Promise<void>;
}) {
  const [asking, setAsking] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [delError, setDelError] = React.useState<string | null>(null);
  const cancelRef = React.useRef<HTMLButtonElement>(null);
  const deleteBtn = React.useRef<HTMLButtonElement>(null);
  const name = machineName(m);
  const env = envelopeOf(m);
  const st = machineStatus(m);
  const method = procName(m.process);
  const cap = m.capabilities ?? {};

  React.useEffect(() => {
    setAsking(false);
    setDelError(null);
  }, [m.id]);
  React.useEffect(() => {
    if (asking) cancelRef.current?.focus();
  }, [asking]);

  const matching = (records ?? []).filter((r) => r.make_now_process === m.process);
  const prn = printerRows(m);
  const kgText = m.max_workpiece_kg != null ? plain(m.max_workpiece_kg) : "—";

  return (
    <>
      <div className="top">
        <h2 className="stitle">{name}</h2>
        <p className="smeta">
          {procShort(m.process)} · ×{m.count ?? 1} ·{" "}
          <span className={cx("chip", st.rated ? "st-user" : "st-norate")} style={{ height: 20 }}>
            <i aria-hidden="true" />
            {st.label}
          </span>
        </p>
        <div className="figs">
          <div className="fig">
            <span>Rate</span>
            <b className={cx("num", m.hourly_rate_usd == null && "t")}>{m.hourly_rate_usd != null ? perHour(m.hourly_rate_usd) : "Not set"}</b>
            <small>{m.hourly_rate_usd != null ? "yours" : "card rate used"}</small>
          </div>
          <div className="fig">
            <span>{env?.label === "Swing × between centers" ? "Swing × length" : "Work area"}</span>
            <b className={cx("num", !env && "t")}>{env ? env.fig : "Not declared"}</b>
            {env ? <small>mm</small> : null}
          </div>
          <div className="fig">
            <span>Max part</span>
            <b className={cx("num", m.max_workpiece_kg == null && "t")}>{m.max_workpiece_kg != null ? kgText : "Not set"}</b>
            {m.max_workpiece_kg != null ? <small>kg</small> : null}
          </div>
        </div>
      </div>
      <div className="scroll">
        <div className="gh">
          <span>Spec</span>
          <span style={{ display: "flex", gap: 6 }}>
            <button className="btn sm" type="button" onClick={onEdit}>
              Edit specs
            </button>
            <button className="btn sm" type="button" ref={deleteBtn} onClick={() => setAsking(true)} aria-expanded={asking}>
              Delete
            </button>
          </span>
        </div>
        {asking ? (
          <div className="confirm" role="alertdialog" aria-label="Delete machine">
            <b>Delete {name}?</b>
            <span>Saved decisions are marked for re-costing. This can&apos;t be undone.</span>
            {delError ? (
              <span className="err" role="alert">
                {delError}
              </span>
            ) : null}
            <span className="bx">
              <button
                className="btn danger sm"
                type="button"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setDelError(null);
                  try {
                    await onDelete();
                  } catch (e) {
                    setDelError(e instanceof Error ? e.message : "Couldn't delete.");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {busy ? "Deleting…" : "Delete machine"}
              </button>
              <button
                className="btn sm"
                type="button"
                ref={cancelRef}
                disabled={busy}
                onClick={() => {
                  setAsking(false);
                  deleteBtn.current?.focus();
                }}
              >
                Cancel
              </button>
            </span>
          </div>
        ) : null}
        <div className="kv">
          <span>{env?.label ?? "Work area"}</span>
          <b className="num">{env ? env.text : "Not declared"}</b>
          <span>Materials</span>
          <b>{m.materials?.length ? m.materials.join(", ") : "Not declared"}</b>
          <span>Count</span>
          <b className="num">{m.count ?? 1}</b>
          <span>Max workpiece</span>
          <b className="num">{m.max_workpiece_kg != null ? `${kgText} kg` : "Not set"}</b>
          <span>Capital fraction</span>
          <b className="num">{m.capital_frac != null ? `${capitalPercentText(m.capital_frac)}%` : "Rate card default"}</b>
          {typeof cap.axes === "number" ? (
            <>
              <span>Axes</span>
              <b className="num">{cap.axes}</b>
            </>
          ) : null}
          <span>Notes</span>
          <b>{m.notes?.trim() || "None"}</b>
          <span>ID</span>
          <b className="mono">{m.id}</b>
        </div>
        {prn.length ? (
          <>
            <div className="gh" style={{ marginTop: 6 }}>
              <span>Printer</span>
              <span />
            </div>
            <div className="prn">
              <div className="kv">
                {prn.map(([k, v]) => (
                  <React.Fragment key={k}>
                    <span>{k}</span>
                    <b>{v}</b>
                  </React.Fragment>
                ))}
              </div>
            </div>
          </>
        ) : null}

        <div className="gh" style={{ marginTop: 6 }}>
          <span>Rate history</span>
          <span />
        </div>
        <div style={{ padding: "0 0 4px" }}>
          {m.hourly_rate_usd != null ? (
            <div className="hist">
              <span>{longDate(m.updated_at || m.created_at)} · current</span>
              <span className="src s-yours">Yours</span>
              <b className="num">{perHour(m.hourly_rate_usd)}</b>
            </div>
          ) : (
            <div className="hist">
              <span>No machine rate declared</span>
              <span className="src s-typ">Typical</span>
              <b>Card rate</b>
            </div>
          )}
          <div className="hist">
            <span style={{ color: "var(--ink3)" }}>Earlier values aren&apos;t kept; edits overwrite.</span>
            <span />
            <span />
          </div>
          {rc.error ? (
            <div className="hist">
              <span style={{ color: "#8A1C12" }}>Couldn&apos;t read rates.</span>
              <span />
              <button className="btn sm" type="button" onClick={rc.reload}>
                Retry
              </button>
            </div>
          ) : (
            <div className="hist">
              <span>Rate card in effect</span>
              <span className={cx("src", rc.view?.governed ? "s-yours" : "s-typ")}>{rc.view?.governed ? "Governed" : "Typical"}</span>
              <b>{rc.view ? (rc.view.governed ? (rc.view.inEffect?.version != null ? `v${rc.view.inEffect.version}` : "Published") : "Default v0") : "…"}</b>
            </div>
          )}
        </div>

        <div className="gh" style={{ marginTop: 6 }}>
          <span>Records recommending {method}</span>
          <span className="num">{records ? matching.length : ""}</span>
        </div>
        {recordsError ? (
          <div className="rec">
            <span style={{ color: "#8A1C12" }}>Couldn&apos;t load records.</span>
            <button className="btn sm" type="button" onClick={onRetryRecords}>
              Retry
            </button>
          </div>
        ) : records == null ? (
          <p className="sh-note" role="status">
            Loading records…
          </p>
        ) : matching.length === 0 ? (
          <p style={{ margin: "4px 12px", color: "var(--ink3)", fontSize: 13 }}>No saved records recommend {method} yet.</p>
        ) : (
          <>
            {matching.slice(0, 10).map((r) => {
              const file = r.label || r.filename;
              return (
                <div className="rec" key={r.id}>
                  <span>
                    {file}
                    <small>
                      {method} · {shortWhen(r.created_at)}
                      {r.is_stale ? " · marked for re-costing" : ""}
                    </small>
                  </span>
                  <Link href={R.record(r.id)} aria-label={`Open ${file} record`}>
                    Open
                  </Link>
                </div>
              );
            })}
            {matching.length > 10 ? <p className="sh-note">Newest 10 of {matching.length}.</p> : null}
          </>
        )}
        <p className="sh-note">A matching method doesn&apos;t mean the part fits this machine.</p>
      </div>
    </>
  );
}
