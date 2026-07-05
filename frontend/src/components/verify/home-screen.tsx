"use client";

/**
 * HOME — the verification desk (design: renderHome / SCREEN: HOME).
 *
 * Every number on this surface is a REAL engine/DB output or is WITHHELD — no
 * design fixtures are ported (the design's Midwest / V-0117 / object.stl $14.14 /
 * 268-in-house data is illustrative mockup and must NOT appear as real). When the
 * org has no data, the honest EMPTY state renders, never invented lookalikes.
 *
 * Wiring:
 *   - RECORDS + IN FLIGHT   ← GET /api/v1/cost-decisions
 *   - MACHINES / YOUR FLOOR ← GET /api/v1/machine-inventory
 *   - NEEDS YOUR ACTION     ← proposed GET /api/v1/governance/change-requests
 *                             + KNOWN-zero floor / ground-truth nudges
 *   - GROUND-TRUTH FLYWHEEL ← GET /api/v1/ground-truth  (real, non-stand-in count)
 *   - ACTIVITY              ← cost-decisions ⊕ governance events (merged, real)
 *
 * The row-shaping is pure + unit-tested in home-derive.ts; this component only
 * fetches, renders, and navigates. No scripted walkthroughs live here (design
 * rule — those are ⌘K only).
 */
import { useEffect, useState } from "react";
import { fetchCostDecisions, type CostDecisionSummary } from "@/lib/api";
import { listMachines } from "@/lib/verify/machine-api";
import { listChangeRequests, type ChangeRequest } from "@/lib/verify/governance-api";
import { listGroundTruth, realActualCount } from "@/lib/verify/ground-truth-api";
import { buildQueue, buildActivity, proposedCount, type QueueRow } from "@/lib/verify/home-derive";
import { C, MONO, NUM, procLabel } from "@/lib/verify/tokens";
import { Kicker } from "./primitives";

export function HomeScreen({ onPickFile, nav }: { onPickFile: () => void; nav: (s: string) => void }) {
  const [records, setRecords] = useState<CostDecisionSummary[] | null>(null);
  const [recordsMore, setRecordsMore] = useState(false);
  const [machineCount, setMachineCount] = useState<number | null>(null);
  const [changeRequests, setChangeRequests] = useState<ChangeRequest[] | null>(null);
  const [actuals, setActuals] = useState<number | null>(null);

  useEffect(() => {
    fetchCostDecisions({ limit: 8 }).then(
      (p) => { setRecords(p.cost_decisions); setRecordsMore(p.has_more); },
      () => setRecords([])
    );
    listMachines().then((p) => setMachineCount(p.machines.length), () => setMachineCount(null));
    // Governance + ground-truth are viewer-scoped; a null result means we don't
    // know yet and never produce a nudge. Failures degrade to "no signal", never
    // to a fabricated one.
    listChangeRequests().then((p) => setChangeRequests(p.change_requests), () => setChangeRequests([]));
    listGroundTruth().then((p) => setActuals(realActualCount(p.records)), () => setActuals(null));
  }, []);

  const today = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  const recordCount = records == null ? null : records.length;
  const proposed = changeRequests == null ? null : proposedCount(changeRequests);

  const queue: QueueRow[] | null =
    changeRequests == null && machineCount == null && actuals == null
      ? null
      : buildQueue({
          changeRequests: changeRequests ?? [],
          machineCount,
          recordCount,
          realActualCount: actuals,
        });

  const activity = buildActivity({ records: records ?? [], changeRequests: changeRequests ?? [] });

  // KPI strip — five honest slots. A count we don't have is "—" (loading) or a
  // real value; the validated-band count is not derivable from any list summary,
  // so it stays WITHHELD ([no data yet]) rather than invented.
  const kpis: { n: string; l: string; c: string; go: string }[] = [
    { n: recordCount == null ? "—" : `${NUM(recordCount)}${recordsMore ? "+" : ""}`, l: "RECORDS", c: recordCount ? C.ink : C.ink45, go: "records" },
    { n: machineCount == null ? "—" : NUM(machineCount), l: "MACHINES DECLARED", c: machineCount ? C.ink : C.fail, go: "machines" },
    { n: proposed == null ? "—" : NUM(proposed), l: "IN REVIEW · GOVERNED", c: proposed ? C.cond : C.ink45, go: "calibration" },
    { n: actuals == null ? "—" : actuals === 0 ? "n=0" : NUM(actuals), l: "ACTUALS · GROUND TRUTH", c: actuals ? C.ink : C.cond, go: "calibration" },
    { n: "—", l: "VALIDATED BANDS · NO DATA YET", c: C.ink45, go: "calibration" },
  ];

  const sevColor = (s: "cond" | "fail") => (s === "fail" ? C.fail : C.cond);

  return (
    <main style={{ animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both", flex: 1, overflowY: "auto", padding: "28px 38px", background: C.bg }}>
      <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.16em", color: C.ink40 }}>{today.toUpperCase()}</p>
      <h1 style={{ margin: "8px 0 0", fontSize: 28, fontWeight: 300, letterSpacing: "-0.018em", lineHeight: 1.25 }}>Good morning.</h1>

      <button
        type="button"
        onClick={() => nav("palette")}
        style={{ marginTop: 18, width: "100%", maxWidth: 1160, display: "flex", alignItems: "center", gap: 12, border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "15px 18px", cursor: "pointer", fontFamily: "inherit", textAlign: "left", boxShadow: "0 1px 2px rgba(23,24,26,0.03)" }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={C.ink40} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v3" /><path d="M18.4 5.6 16 8" /><path d="M21 12h-3" /><path d="M12 21a9 9 0 1 1 9-9" /><circle cx="12" cy="12" r="1" /></svg>
        <span style={{ flex: 1, fontSize: 14.5, color: C.ink45, fontWeight: 300 }}>Ask the engine, search, or jump anywhere…</span>
        <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink45, border: `1px solid ${C.hair}`, borderRadius: 6, padding: "3px 8px" }}>⌘K</span>
      </button>

      {/* KPI strip */}
      <div style={{ marginTop: 20, display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12, maxWidth: 1160 }}>
        {kpis.map((kp) => (
          <button key={kp.l} type="button" onClick={() => nav(kp.go)} style={{ textAlign: "left", border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "14px 16px", cursor: "pointer", fontFamily: "inherit", color: "inherit" }}>
            <p style={{ margin: 0, fontFamily: MONO, fontSize: 22, fontWeight: 500, letterSpacing: "-0.01em", color: kp.c }}>{kp.n}</p>
            <p style={{ margin: "5px 0 0", fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", color: C.ink45 }}>{kp.l}</p>
          </button>
        ))}
      </div>

      <div style={{ marginTop: 16, display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 16, maxWidth: 1160, alignItems: "start" }}>
        {/* left: work */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* NEEDS YOUR ACTION */}
          <section style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "20px 22px" }}>
            <Kicker>NEEDS YOUR ACTION</Kicker>
            {queue == null ? (
              <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink45 }}>loading…</p>
            ) : queue.length === 0 ? (
              <div style={{ marginTop: 14, border: "1.5px dashed #d3d3d8", borderRadius: 12, padding: "22px 20px", textAlign: "center" }}>
                <p style={{ margin: 0, fontSize: 13.5, fontWeight: 500 }}>Nothing needs you yet.</p>
                <p style={{ margin: "6px 0 0", fontSize: 12, color: C.ink50 }}>
                  {machineCount === 0
                    ? "Declare your floor — everything starts from the denominator."
                    : "No governed changes are waiting on review, and no verdict is blocked."}
                </p>
              </div>
            ) : (
              <div style={{ marginTop: 6, display: "flex", flexDirection: "column" }}>
                {queue.map((qr) => (
                  <div key={qr.key} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 2px", borderBottom: "1px solid #efeff2" }}>
                    {qr.hatched ? (
                      <span aria-hidden style={{ width: 8, height: 8, borderRadius: 2, flexShrink: 0, backgroundImage: "repeating-linear-gradient(135deg, rgba(23,24,26,0.5) 0 1.5px, transparent 1.5px 4px)", border: `1px solid ${sevColor(qr.severity)}` }} />
                    ) : (
                      <span aria-hidden style={{ width: 7, height: 7, borderRadius: "50%", background: sevColor(qr.severity), flexShrink: 0 }} />
                    )}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ margin: 0, fontSize: 13, color: C.ink }}>{qr.title}</p>
                      <p style={{ margin: "3px 0 0", fontFamily: MONO, fontSize: 10, lineHeight: 1.5, color: C.ink45, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{qr.meta}</p>
                    </div>
                    <button type="button" onClick={() => nav(qr.go)} style={{ flexShrink: 0, background: "none", border: "1px solid #d8d8dc", borderRadius: 999, color: C.ink, padding: "6px 15px", fontSize: 11.5, cursor: "pointer", fontFamily: "inherit" }}>{qr.action}</button>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* IN FLIGHT — recent verifications */}
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
                    <span style={{ fontSize: 12.5, color: r.make_now_process ? C.pass : C.ink45, flex: 1 }}>{r.make_now_process ? procLabel(r.make_now_process) : "verdict withheld"}</span>
                    <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink35 }}>{new Date(r.created_at).toLocaleDateString()}</span>
                  </button>
                ))}
              </div>
            )}
          </section>
        </div>

        {/* right stack */}
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

          <button type="button" onClick={() => nav("triage")} style={{ border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "16px 18px", cursor: "pointer", fontFamily: "inherit", color: "inherit", textAlign: "left" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Kicker>TRIAGE · MAKEABILITY AT SCALE</Kicker>
              <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.08em", color: C.pass }}>LIVE</span>
            </div>
            <p style={{ margin: "10px 0 0", fontSize: 13, color: C.ink }}>Sort a BOM into makeable in-house / outside / needs capability / not makeable.</p>
            <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>buckets compute from an uploaded BOM — no counts are shown until one is run</p>
          </button>

          {/* GROUND-TRUTH FLYWHEEL — real actuals count only */}
          <button type="button" onClick={() => nav("calibration")} style={{ border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "16px 18px", cursor: "pointer", fontFamily: "inherit", color: "inherit", textAlign: "left" }}>
            <Kicker>GROUND-TRUTH FLYWHEEL</Kicker>
            <div style={{ marginTop: 10, position: "relative", height: 6, borderRadius: 3, background: "#ececef", overflow: "hidden" }}>
              <span style={{ position: "absolute", inset: 0, backgroundImage: "repeating-linear-gradient(135deg, rgba(23,24,26,0.35) 0 2px, transparent 2px 7px)" }} />
            </div>
            <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10.5, color: actuals ? C.ink45 : C.cond }}>
              {actuals == null
                ? "loading…"
                : actuals === 0
                  ? "n=0 · every band still hatched — send actuals back to flip them"
                  : `${NUM(actuals)} actual${actuals === 1 ? "" : "s"} received · bands flip solid as each process reaches enough residuals`}
            </p>
          </button>

          {/* ACTIVITY */}
          <section style={{ border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "16px 18px" }}>
            <Kicker>ACTIVITY</Kicker>
            {records == null && changeRequests == null ? (
              <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>loading…</p>
            ) : activity.length === 0 ? (
              <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>nothing yet — your first verification will land here</p>
            ) : (
              <div style={{ marginTop: 6, display: "flex", flexDirection: "column" }}>
                {activity.map((av) => (
                  <div key={av.key} style={{ display: "flex", gap: 10, padding: "8px 0", borderBottom: "1px solid #f0f0f3", fontFamily: MONO, fontSize: 10.5 }}>
                    <span style={{ color: C.ink35, minWidth: 44 }}>{av.d}</span>
                    <span style={{ color: C.ink60, lineHeight: 1.5 }}>{av.t}</span>
                  </div>
                ))}
              </div>
            )}
            <button type="button" onClick={() => nav("calibration")} style={{ marginTop: 10, background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 10, color: C.measured }}>full audit log →</button>
          </section>
        </div>
      </div>
    </main>
  );
}
