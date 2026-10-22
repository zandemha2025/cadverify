"use client";

/**
 * Calibration from your actuals: what ScaleCAD would change for each method
 * (fitted on your matched actuals, measured with each part held out), apply it
 * to future estimates (pilot plan), who applied it and when, and undo. Seeing
 * what would change works on every plan; applying it is part of the pilot.
 */
import * as React from "react";
import { ConfirmButton, Loading, Panel } from "../ui";
import { ActualsApiError, applyCalibration, getCalibration, undoCalibration, type CalibrationEntry, type CalibrationState } from "./api";
import { changeWord, dateWord, effectWord, factorWord, methodWord, whyNot } from "./words";
import "./validation.css";

function factorsLine(e: CalibrationEntry): string {
  return Object.entries(e.factors)
    .map(([p, f]) => {
      const bits = [];
      if (f.hours) bits.push(`machine time ${factorWord(f.hours)}`);
      if (f.cost) bits.push(`cost ${factorWord(f.cost)}`);
      return `${methodWord(p)}: ${bits.join(", ")}`;
    })
    .join("; ");
}

/** The applied factors match what the actuals support now (same as the backend's same_factors). */
function sameAs(inEffect: CalibrationEntry | null, process: string, hours: number | null, cost: number | null): boolean {
  const f = inEffect?.factors[process];
  if (!f) return false;
  const eq = (a: number | null | undefined, b: number | null) => (a == null) === (b == null) && (a == null || b == null || Math.abs(a - b) <= 5e-4);
  return eq(f.hours, hours) && eq(f.cost, cost);
}

export function CalibrationPanel({ ask, onChanged }: { ask?: number; onChanged?: () => void }) {
  const [state, setState] = React.useState<CalibrationState | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [n, setN] = React.useState(0);
  const [picked, setPicked] = React.useState<Record<string, boolean>>({});
  const [confirm, setConfirm] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState<{ tone: "ok" | "bad" | "warn"; text: string } | null>(null);
  const confirmRef = React.useRef<HTMLButtonElement>(null);
  const applyRef = React.useRef<HTMLButtonElement>(null);
  const panelRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    let live = true;
    setError(null);
    getCalibration().then(
      (s) => {
        if (!live) return;
        setState(s);
        setPicked((old) => {
          const next: Record<string, boolean> = {};
          for (const p of s.proposal.processes) if (p.hours.offer || p.cost.offer) next[p.process] = old[p.process] ?? true;
          return next;
        });
      },
      (e) => live && setError(e instanceof Error ? e.message : "The calibration didn’t load.")
    );
    return () => {
      live = false;
    };
  }, [n]);

  // The page's Recalibrate button asks here.
  React.useEffect(() => {
    if (!ask) return;
    setConfirm(true);
    panelRef.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, [ask]);
  React.useEffect(() => {
    if (confirm) confirmRef.current?.focus();
  }, [confirm]);

  const inEffect = state?.history.find((h) => h.in_effect) ?? null;
  const factorsOf = (p: CalibrationState["proposal"]["processes"][number]) => [p.hours.offer ? p.hours.factor : null, p.cost.offer ? p.cost.factor : null] as const;
  const current = (p: CalibrationState["proposal"]["processes"][number]) => sameAs(inEffect, p.process, ...factorsOf(p));
  const offered = (state?.proposal.processes ?? []).filter((p) => (p.hours.offer || p.cost.offer) && !current(p));
  const chosen = offered.filter((p) => picked[p.process]).map((p) => p.process);

  const doApply = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await applyCalibration(chosen);
      setConfirm(false);
      setMsg({ tone: "ok", text: `Applied to new estimates for ${chosen.map(methodWord).join(", ")}. Records already saved keep their numbers.` });
      setN((x) => x + 1);
      onChanged?.();
    } catch (e) {
      if (e instanceof ActualsApiError && e.status === 403) setMsg({ tone: "warn", text: "Not applied: your plan doesn’t include applying a calibration. It’s part of the pilot." });
      else setMsg({ tone: "bad", text: e instanceof Error ? e.message : "The calibration wasn’t applied." });
      setConfirm(false);
    } finally {
      setBusy(false);
      applyRef.current?.focus();
    }
  };

  const doUndo = async () => {
    setMsg(null);
    try {
      const r = await undoCalibration();
      setMsg({ tone: "ok", text: r.in_effect ? `Undone. The calibration from ${dateWord(r.in_effect.applied_at)} is in effect again.` : "Undone. New estimates use ScaleCAD’s own numbers again." });
      setN((x) => x + 1);
      onChanged?.();
    } catch (e) {
      setMsg({ tone: "bad", text: e instanceof Error ? e.message : "The calibration wasn’t undone." });
    }
  };

  const p = state?.proposal;
  return (
    <div ref={panelRef} style={{ scrollMarginTop: 80 }}>
      <Panel title={<>Calibration from your actuals</>} note={<span className="pilot">Pilot</span>}>
        {error ? (
          <p className="val-lead warn" role="alert" style={{ paddingBottom: 12 }}>
            The calibration didn’t load: {error}{" "}
            <button className="btn sm" type="button" onClick={() => setN((x) => x + 1)}>
              Retry
            </button>
          </p>
        ) : !state || !p ? (
          <Loading rows={2} label="Reading what your actuals support" />
        ) : (
          <>
            {inEffect ? (
              <div className="val-effect" role="status">
                <span>
                  <b>In effect since {dateWord(inEffect.applied_at)}</b>
                  {inEffect.applied_by ? `, applied by ${inEffect.applied_by}` : ""}. {factorsLine(inEffect)}. New estimates for these methods include it; ScaleCAD’s own numbers stay on each record.
                </span>
                <ConfirmButton label="Undo calibration" question="Undo it for new estimates?" confirmLabel="Undo it" onConfirm={doUndo} />
              </div>
            ) : null}
            <p className="val-lead">
              {!p.processes.length
                ? "Nothing to calibrate yet: import actuals that match your parts."
                : !p.enough
                  ? `${p.parts} ${p.parts === 1 ? "part" : "parts"} with actuals. A calibration needs ${p.min_parts} or more, and ${p.min_per_method} actuals for the method it changes.`
                  : offered.length || inEffect
                    ? "What your actuals say ScaleCAD should change. Each figure is checked part by part: the part’s own actual never grades the factor fitted on it."
                    : "Your actuals don’t support a change for any method right now."}
            </p>
            {p.processes.length ? (
              <div className="val-cal" role="group" aria-label="Changes by method">
                {p.processes.map((x) => {
                  const live = current(x);
                  const offer = (x.hours.offer || x.cost.offer) && !live;
                  const id = `cal-${x.process}`;
                  return (
                    <div className="val-prop" key={x.process}>
                      {live ? (
                        <span className="chip c-ok" style={{ width: "fit-content", gridColumn: "1 / -1" }}>
                          <i aria-hidden="true" />
                          In effect
                        </span>
                      ) : null}
                      {offer ? (
                        <input id={id} type="checkbox" checked={!!picked[x.process]} onChange={(e) => setPicked((o) => ({ ...o, [x.process]: e.target.checked }))} aria-label={`Include ${methodWord(x.process)}`} />
                      ) : (
                        <span className="dot" aria-hidden="true" />
                      )}
                      <span>
                        <b>{methodWord(x.process)}</b>
                        {(["hours", "cost"] as const).map((k) => {
                          const e = x[k];
                          if (!e.n) return null;
                          return (
                            <small key={k}>
                              {e.offer && e.factor != null ? (
                                <>
                                  {changeWord(x.process, k, e.factor)}
                                  {k === "cost" && e.after_hours ? " (after the machine-time change)" : ""}. {effectWord(e)}
                                </>
                              ) : (
                                <>
                                  {k === "hours" ? "Machine hours" : "Cost"}: {whyNot(e, k, p.parts, p.min_parts)}
                                </>
                              )}
                            </small>
                          );
                        })}
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : null}
            <p className="val-pilot">
              Applying a calibration is part of the pilot. The comparison with your actuals and this list work on every plan. Applied, it changes new estimates only, records who applied it and when, and can be undone.
            </p>
            {confirm ? (
              <div className="banner" role="alertdialog" aria-label="Recalibrate" style={{ margin: "0 16px 12px" }}>
                <span>
                  {offered.length ? (
                    chosen.length ? (
                      <>
                        <b>Apply to new estimates for {chosen.map(methodWord).join(", ")}?</b> Records already saved keep their numbers. You can undo it.
                      </>
                    ) : (
                      <>
                        <b>Pick at least one method.</b> Tick the methods to calibrate above.
                      </>
                    )
                  ) : (
                    <>
                      <b>Nothing to apply yet.</b> {p.enough ? "No method has a change that makes ScaleCAD more accurate on your parts." : `${p.min_parts} parts with actuals are needed; you have ${p.parts}.`}
                    </>
                  )}
                </span>
                <span className="bx">
                  {offered.length && chosen.length ? (
                    <button className="btn ink sm" type="button" onClick={() => void doApply()} disabled={busy}>
                      {busy ? "Applying…" : "Apply"}
                    </button>
                  ) : null}
                  <button className="btn sm" type="button" ref={confirmRef} onClick={() => setConfirm(false)} disabled={busy}>
                    {offered.length && chosen.length ? "Cancel" : "Close"}
                  </button>
                </span>
              </div>
            ) : null}
            {msg ? (
              <p className={`val-lead${msg.tone === "ok" ? "" : " warn"}`} role={msg.tone === "bad" ? "alert" : "status"} style={{ paddingBottom: 10 }}>
                {msg.text}
              </p>
            ) : null}
            <div className="pact" style={{ padding: "0 16px 14px" }}>
              <button className="btn ink sm" type="button" ref={applyRef} onClick={() => setConfirm(true)} disabled={busy || !offered.length || !chosen.length}>
                Apply to future estimates <span className="pilot">Pilot</span>
              </button>
              {!state.can_apply ? (
                <a className="fh" href="/pilot">
                  About the pilot
                </a>
              ) : null}
            </div>
            {state.history.length ? (
              <>
                <div className="gh" style={{ padding: "4px 16px 4px" }}>
                  <span>History</span>
                  <span />
                </div>
                <ul className="val-hist">
                  {state.history.map((h) => (
                    <li key={h.id}>
                      <b>{h.in_effect ? "In effect" : h.status === "undone" ? "Undone" : "Replaced"}</b> · applied {dateWord(h.applied_at)}
                      {h.applied_by ? ` by ${h.applied_by}` : ""}
                      {h.undone_at ? ` · undone ${dateWord(h.undone_at)}${h.undone_by ? ` by ${h.undone_by}` : ""}` : ""} · {factorsLine(h)}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </>
        )}
      </Panel>
    </div>
  );
}
