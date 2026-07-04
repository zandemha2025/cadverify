"use client";

/**
 * HOME — the verification desk. Drop zone wired to the real verify flow; KPIs are
 * REAL counts (records, machines) or honestly withheld — never invented. In-flight
 * shows the org's recent real records; nothing is padded with lookalikes.
 */
import { useEffect, useState } from "react";
import { fetchCostDecisions, type CostDecisionSummary } from "@/lib/api";
import { listMachines } from "@/lib/verify/machine-api";
import { C, MONO, NUM, procLabel } from "@/lib/verify/tokens";
import { Kicker } from "./primitives";

export function HomeScreen({ onPickFile, nav }: { onPickFile: () => void; nav: (s: string) => void }) {
  const [records, setRecords] = useState<CostDecisionSummary[] | null>(null);
  const [recordsMore, setRecordsMore] = useState(false);
  const [machineCount, setMachineCount] = useState<number | null>(null);

  useEffect(() => {
    fetchCostDecisions({ limit: 10 }).then(
      (p) => { setRecords(p.cost_decisions); setRecordsMore(p.has_more); },
      () => setRecords([])
    );
    listMachines().then((p) => setMachineCount(p.machines.length), () => setMachineCount(null));
  }, []);

  const today = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });

  const kpis: { n: string; l: string; c: string; go: string }[] = [
    { n: records == null ? "—" : `${NUM(records.length)}${recordsMore ? "+" : ""}`, l: "RECORDS", c: C.ink, go: "records" },
    { n: machineCount == null ? "—" : NUM(machineCount), l: "MACHINES DECLARED", c: machineCount ? C.ink : C.cond, go: "machines" },
    // Validated-band counts aren't carried on the list summaries, so this is not a
    // number we can honestly compute here — it is labelled [no data yet], never a
    // hardcoded stat. It resolves on the Calibration surface once actuals arrive.
    { n: "—", l: "VALIDATED BANDS · NO DATA YET", c: C.ink45, go: "calibration" },
  ];

  return (
    <main style={{ animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both", flex: 1, overflowY: "auto", padding: "28px 38px", background: C.bg }}>
      <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.16em", color: C.ink40 }}>{today.toUpperCase()}</p>
      <h1 style={{ margin: "8px 0 0", fontSize: 28, fontWeight: 300, letterSpacing: "-0.018em", lineHeight: 1.25 }}>Good morning.</h1>

      <button
        type="button"
        onClick={() => nav("palette")}
        style={{ marginTop: 18, width: "100%", maxWidth: 1160, display: "flex", alignItems: "center", gap: 12, border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "15px 18px", cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}
      >
        <span style={{ flex: 1, fontSize: 14.5, color: C.ink45, fontWeight: 300 }}>Ask the engine, search, or jump anywhere…</span>
        <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink45, border: `1px solid ${C.hair}`, borderRadius: 6, padding: "3px 8px" }}>⌘K</span>
      </button>

      <div style={{ marginTop: 20, display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, maxWidth: 720 }}>
        {kpis.map((kp) => (
          <button key={kp.l} type="button" onClick={() => nav(kp.go)} style={{ textAlign: "left", border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "14px 16px", cursor: "pointer", fontFamily: "inherit", color: "inherit" }}>
            <p style={{ margin: 0, fontFamily: MONO, fontSize: 22, fontWeight: 500, letterSpacing: "-0.01em", color: kp.c }}>{kp.n}</p>
            <p style={{ margin: "5px 0 0", fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", color: C.ink45 }}>{kp.l}</p>
          </button>
        ))}
      </div>

      <div style={{ marginTop: 16, display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 16, maxWidth: 1160, alignItems: "start" }}>
        <section style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "20px 22px" }}>
          <Kicker>IN FLIGHT — RECENT VERIFICATIONS</Kicker>
          {records == null ? (
            <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink45 }}>loading…</p>
          ) : records.length === 0 ? (
            <div style={{ marginTop: 14, border: "1.5px dashed #d3d3d8", borderRadius: 12, padding: "26px 20px", textAlign: "center" }}>
              <p style={{ margin: 0, fontSize: 14, fontWeight: 500 }}>Nothing in flight.</p>
              <p style={{ margin: "7px 0 0", fontSize: 12, color: C.ink50 }}>Your first verdict is one drop away — and it will be honest about what it doesn&apos;t know yet.</p>
            </div>
          ) : (
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column" }}>
              {records.map((r) => (
                <button key={r.id} type="button" onClick={() => nav("records")} style={{ display: "flex", alignItems: "center", gap: 12, background: "none", border: "none", borderBottom: `1px solid #efeff2`, padding: "13px 2px", cursor: "pointer", fontFamily: "inherit", color: "inherit", textAlign: "left" }}>
                  <span style={{ fontFamily: MONO, fontSize: 12.5, color: C.ink, minWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.label || r.filename}</span>
                  <span style={{ fontSize: 12.5, color: C.pass, flex: 1 }}>{procLabel(r.make_now_process)}</span>
                  <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink35 }}>{new Date(r.created_at).toLocaleDateString()}</span>
                </button>
              ))}
            </div>
          )}
        </section>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <button type="button" onClick={onPickFile} style={{ border: `1.5px dashed #c9cbd0`, borderRadius: 14, background: C.panel, padding: 18, cursor: "pointer", fontFamily: "inherit", color: "inherit", textAlign: "center" }}>
            <p style={{ margin: 0, fontSize: 14, fontWeight: 500 }}>Drop a part — STEP or STL</p>
            <p style={{ margin: "5px 0 0", fontSize: 11, color: C.ink45 }}>parsed in-process · discarded</p>
            <span style={{ display: "inline-block", marginTop: 10, background: C.ink, color: "#fff", borderRadius: 999, padding: "8px 18px", fontSize: 12, fontWeight: 500 }}>Browse files</span>
          </button>
          <button type="button" onClick={() => nav("machines")} style={{ border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "16px 18px", cursor: "pointer", fontFamily: "inherit", color: "inherit", textAlign: "left" }}>
            <Kicker>YOUR FLOOR</Kicker>
            <p style={{ margin: "8px 0 0", fontSize: 14 }}>
              {machineCount == null ? "—" : machineCount === 0 ? "No machines declared" : `${machineCount} machine${machineCount === 1 ? "" : "s"} owned · marginal costing active`}
            </p>
            <p style={{ margin: "5px 0 0", fontSize: 12, color: machineCount ? C.ink45 : C.cond }}>
              {machineCount ? "the denominator of every verdict" : "declare your floor — everything starts from the denominator"}
            </p>
          </button>
          <div style={{ border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "16px 18px" }}>
            <Kicker>GROUND-TRUTH FLYWHEEL</Kicker>
            <div style={{ marginTop: 10, position: "relative", height: 6, borderRadius: 3, background: "#ececef", overflow: "hidden" }}>
              <span style={{ position: "absolute", inset: 0, backgroundImage: "repeating-linear-gradient(135deg, rgba(23,24,26,0.35) 0 2px, transparent 2px 7px)" }} />
            </div>
            <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>no validated bands yet — send actuals back to flip a hatched band solid</p>
          </div>
        </div>
      </div>
    </main>
  );
}
