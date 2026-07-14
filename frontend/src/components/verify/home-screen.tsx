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
import Link from "next/link";
import { fetchCostDecisions, type CostDecisionSummary } from "@/lib/api";
import { listMachines } from "@/lib/verify/machine-api";
import { listChangeRequests, type ChangeRequest } from "@/lib/verify/governance-api";
import { listGroundTruth, realActualCount } from "@/lib/verify/ground-truth-api";
import { getPortfolio, declaredPrograms } from "@/lib/verify/program-api";
import { buildQueue, buildActivity, buildDayZeroSetup, proposedCount, type QueueRow } from "@/lib/verify/home-derive";
import { C, MONO, NUM, procLabel } from "@/lib/verify/tokens";
import { Kicker } from "./primitives";

export function HomeScreen({ onPickFile, nav }: { onPickFile: () => void; nav: (s: string) => void }) {
  const [records, setRecords] = useState<CostDecisionSummary[] | null>(null);
  const [recordsMore, setRecordsMore] = useState(false);
  const [machineCount, setMachineCount] = useState<number | null>(null);
  const [ratedMachineCount, setRatedMachineCount] = useState<number | null>(null);
  const [programCount, setProgramCount] = useState<number | null>(null);
  const [changeRequests, setChangeRequests] = useState<ChangeRequest[] | null>(null);
  const [actuals, setActuals] = useState<number | null>(null);
  const [retryToken, setRetryToken] = useState(0);
  const [unavailable, setUnavailable] = useState({
    records: false,
    machines: false,
    changes: false,
    actuals: false,
    programs: false,
  });

  useEffect(() => {
    let active = true;
    setUnavailable({ records: false, machines: false, changes: false, actuals: false, programs: false });
    fetchCostDecisions({ limit: 8 }).then(
      (p) => {
        if (!active) return;
        setRecords(p.cost_decisions);
        setRecordsMore(p.has_more);
      },
      () => active && setUnavailable((current) => ({ ...current, records: true }))
    );
    listMachines().then(
      (p) => {
        if (!active) return;
        setMachineCount(p.machines.length);
        setRatedMachineCount(
          p.machines.filter(
            (machine) =>
              typeof machine.hourly_rate_usd === "number" &&
              Number.isFinite(machine.hourly_rate_usd)
          ).length
        );
      },
      () => active && setUnavailable((current) => ({ ...current, machines: true }))
    );
    // Governance + ground-truth are viewer-scoped. Unknown and failed are kept
    // distinct so a transport failure is never presented as an empty org.
    listChangeRequests().then(
      (p) => active && setChangeRequests(p.change_requests),
      () => active && setUnavailable((current) => ({ ...current, changes: true }))
    );
    listGroundTruth().then(
      (p) => active && setActuals(realActualCount(p.records)),
      () => active && setUnavailable((current) => ({ ...current, actuals: true }))
    );
    getPortfolio().then(
      (p) => active && setProgramCount(declaredPrograms(p).length),
      () => active && setUnavailable((current) => ({ ...current, programs: true }))
    );
    return () => {
      active = false;
    };
  }, [retryToken]);

  const today = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  const recordCount = records == null ? null : records.length;
  const proposed = changeRequests == null ? null : proposedCount(changeRequests);
  const missingRateCount =
    machineCount == null || ratedMachineCount == null
      ? null
      : Math.max(0, machineCount - ratedMachineCount);

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
  const setup = buildDayZeroSetup({
    machineCount,
    recordCount,
    programCount,
    realActualCount: actuals,
    unavailable,
  });
  const unavailableLabels = [
    unavailable.records ? "records" : null,
    unavailable.machines ? "machine inventory" : null,
    unavailable.changes ? "governance reviews" : null,
    unavailable.actuals ? "ground truth" : null,
    unavailable.programs ? "programs" : null,
  ].filter((label): label is string => label != null);
  const hasUnavailable = unavailableLabels.length > 0;
  const queueUnavailable =
    queue == null && (unavailable.changes || unavailable.machines || unavailable.actuals);

  const runSetupStep = (key: (typeof setup)[number]["key"]) => {
    if (key === "machines") nav("machines");
    else if (key === "verify") {
      if (recordCount) nav("records");
      else onPickFile();
    }
    else if (key === "program") nav("programs");
    else nav("calibration");
  };

  // KPI strip — five honest slots. A count we don't have is "—" (loading) or a
  // real value; the validated-band count is not derivable from any list summary,
  // so it stays WITHHELD ([no data yet]) rather than invented.
  const kpis: { n: string; l: string; c: string; go: string }[] = [
    { n: recordCount == null ? "—" : `${NUM(recordCount)}${recordsMore ? "+" : ""}`, l: unavailable.records ? "RECORDS · RETRY NEEDED" : "RECORDS", c: unavailable.records ? C.fail : recordCount ? C.ink : C.ink45, go: "records" },
    { n: machineCount == null ? "—" : NUM(machineCount), l: unavailable.machines ? "MACHINES · RETRY NEEDED" : "MACHINES DECLARED", c: unavailable.machines ? C.fail : machineCount ? C.ink : C.fail, go: "machines" },
    { n: proposed == null ? "—" : NUM(proposed), l: unavailable.changes ? "REVIEWS · RETRY NEEDED" : "IN REVIEW · GOVERNED", c: unavailable.changes ? C.fail : proposed ? C.cond : C.ink45, go: "calibration" },
    { n: actuals == null ? "—" : actuals === 0 ? "n=0" : NUM(actuals), l: unavailable.actuals ? "ACTUALS · RETRY NEEDED" : "ACTUALS · GROUND TRUTH", c: unavailable.actuals ? C.fail : actuals ? C.ink : C.cond, go: "calibration" },
    { n: "—", l: "VALIDATED BANDS · NO DATA YET", c: C.ink45, go: "calibration" },
  ];

  const sevColor = (s: "cond" | "fail") => (s === "fail" ? C.fail : C.cond);

  return (
    <main className="cv-verify-home" style={{ animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both", flex: 1, overflowY: "auto", padding: "28px 38px", background: C.bg }}>
      <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.16em", color: C.ink40 }}>{today.toUpperCase()}</p>
      <h1 style={{ margin: "8px 0 0", fontSize: 28, fontWeight: 300, letterSpacing: "-0.018em", lineHeight: 1.25 }}>Good morning.</h1>

      <button
        type="button"
        onClick={() => nav("palette")}
        style={{ marginTop: 18, width: "100%", maxWidth: 1160, display: "flex", alignItems: "center", gap: 12, border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "15px 18px", cursor: "pointer", fontFamily: "inherit", textAlign: "left", boxShadow: "0 1px 2px rgba(23,24,26,0.03)" }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={C.ink40} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v3" /><path d="M18.4 5.6 16 8" /><path d="M21 12h-3" /><path d="M12 21a9 9 0 1 1 9-9" /><circle cx="12" cy="12" r="1" /></svg>
        <span style={{ flex: 1, fontSize: 14.5, color: C.ink45, fontWeight: 300 }}>Jump to a surface, action, or sample walkthrough…</span>
        <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink45, border: `1px solid ${C.hair}`, borderRadius: 6, padding: "3px 8px" }}>⌘K</span>
      </button>

      {hasUnavailable ? (
        <div role="alert" style={{ marginTop: 14, maxWidth: 1160, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", border: "1px solid rgba(190,61,45,0.34)", borderRadius: 12, background: "rgba(190,61,45,0.06)", padding: "11px 14px" }}>
          <p style={{ margin: 0, flex: 1, minWidth: 220, fontSize: 12.5, lineHeight: 1.5, color: C.ink }}>
            Couldn&apos;t load {unavailableLabels.join(", ")}. Related totals and actions are marked unavailable; nothing is being presented as an empty result.
          </p>
          <button type="button" onClick={() => setRetryToken((token) => token + 1)} style={{ border: `1px solid ${C.fail}`, borderRadius: 999, background: C.panel, color: C.fail, padding: "7px 14px", fontFamily: "inherit", fontSize: 11.5, fontWeight: 500, cursor: "pointer" }}>
            Retry organization data
          </button>
        </div>
      ) : null}

      <section className="cv-verify-setup" style={{ marginTop: 16, maxWidth: 1160, border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "16px 18px" }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <Kicker>DAY ZERO SETUP</Kicker>
          <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>
            real org state only · no seeded tenant facts
          </span>
        </div>
        <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10 }}>
          {setup.map((s, i) => {
            const done = s.state === "done";
            const locked = s.state === "locked" || s.state === "pending";
            const failed = s.state === "unavailable";
            return (
              <button
                key={s.key}
                type="button"
                onClick={() => runSetupStep(s.key)}
                disabled={locked}
                aria-label={`${s.title}: ${s.meta}`}
                style={{
                  minHeight: 104,
                  textAlign: "left",
                  border: `1px solid ${done ? "rgba(85,184,128,0.34)" : failed ? "rgba(190,61,45,0.34)" : C.hair}`,
                  borderRadius: 12,
                  background: done ? "rgba(85,184,128,0.06)" : C.sunken,
                  padding: "13px 14px",
                  fontFamily: "inherit",
                  cursor: locked ? "not-allowed" : "pointer",
                  color: "inherit",
                  opacity: locked ? 0.64 : 1,
                }}
              >
                <span style={{ display: "inline-flex", width: 23, height: 23, alignItems: "center", justifyContent: "center", borderRadius: "50%", background: done ? C.pass : "#e6e7ea", color: done ? "#fff" : C.ink45, fontFamily: MONO, fontSize: 10 }}>
                  {done ? "✓" : i + 1}
                </span>
                <p style={{ margin: "11px 0 0", fontSize: 13, fontWeight: 500 }}>{s.title}</p>
                <p style={{ margin: "5px 0 0", fontFamily: MONO, fontSize: 10.5, lineHeight: 1.5, color: failed ? C.fail : s.state === "needed" ? C.cond : C.ink45 }}>{s.meta}</p>
              </button>
            );
          })}
        </div>
      </section>

      {/* KPI strip */}
      <div className="cv-verify-home-kpis" style={{ marginTop: 20, display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12, maxWidth: 1160 }}>
        {kpis.map((kp) => (
          <button key={kp.l} type="button" onClick={() => nav(kp.go)} style={{ textAlign: "left", border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "14px 16px", cursor: "pointer", fontFamily: "inherit", color: "inherit" }}>
            <p style={{ margin: 0, fontFamily: MONO, fontSize: 22, fontWeight: 500, letterSpacing: "-0.01em", color: kp.c }}>{kp.n}</p>
            <p style={{ margin: "5px 0 0", fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", color: C.ink45 }}>{kp.l}</p>
          </button>
        ))}
      </div>

      <div className="cv-verify-home-grid" style={{ marginTop: 16, display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 16, maxWidth: 1160, alignItems: "start" }}>
        {/* left: work */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* NEEDS YOUR ACTION */}
          <section style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "20px 22px" }}>
            <Kicker>NEEDS YOUR ACTION</Kicker>
            {queue == null ? (
              <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: queueUnavailable ? C.fail : C.ink45 }}>
                {queueUnavailable ? "action queue unavailable — retry organization data above" : "loading…"}
              </p>
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
              <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: unavailable.records ? C.fail : C.ink45 }}>
                {unavailable.records ? "recent verifications unavailable — retry organization data above" : "loading…"}
              </p>
            ) : records.length === 0 ? (
              <div style={{ marginTop: 14, border: "1.5px dashed #d3d3d8", borderRadius: 12, padding: "26px 20px", textAlign: "center" }}>
                <p style={{ margin: 0, fontSize: 14, fontWeight: 500 }}>Nothing in flight.</p>
                <p style={{ margin: "7px 0 0", fontSize: 12, color: C.ink50 }}>Create a safe parametric design or upload existing CAD — either path reaches the same honest verification.</p>
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
          <Link href="/designs" style={{ border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: 18, cursor: "pointer", fontFamily: "inherit", color: "inherit", textAlign: "left", textDecoration: "none", display: "block" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Kicker>START FROM SCRATCH</Kicker>
              <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.08em", color: C.measured }}>DESIGN STUDIO</span>
            </div>
            <p style={{ margin: "10px 0 0", fontSize: 14, fontWeight: 500 }}>Create a plate, bracket, or enclosure</p>
            <p style={{ margin: "5px 0 0", fontSize: 11.5, lineHeight: 1.55, color: C.ink45 }}>real STEP + STL · immutable revisions · returns here to verify</p>
            <span style={{ display: "inline-block", marginTop: 10, border: `1px solid ${C.hair}`, borderRadius: 999, padding: "7px 15px", fontSize: 11.5, fontWeight: 500 }}>Open Design Studio →</span>
          </Link>

          <button type="button" onClick={onPickFile} style={{ border: `1.5px dashed #c9cbd0`, borderRadius: 14, background: C.panel, padding: 18, cursor: "pointer", fontFamily: "inherit", color: "inherit", textAlign: "center" }}>
            <p style={{ margin: 0, fontSize: 14, fontWeight: 500 }}>Drop a part — STL, STEP or IGES</p>
            <p style={{ margin: "5px 0 0", fontSize: 11, color: C.ink45 }}>parsed in-process · discarded</p>
            <span style={{ display: "inline-block", marginTop: 10, background: C.ink, color: "#fff", borderRadius: 999, padding: "8px 18px", fontSize: 12, fontWeight: 500 }}>Browse files</span>
          </button>

          <button type="button" onClick={() => nav("machines")} style={{ border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "16px 18px", cursor: "pointer", fontFamily: "inherit", color: "inherit", textAlign: "left" }}>
            <Kicker>YOUR FLOOR</Kicker>
            <p style={{ margin: "8px 0 0", fontSize: 14 }}>
              {machineCount == null || missingRateCount == null
                ? unavailable.machines ? "Machine inventory unavailable" : "—"
                : machineCount === 0
                  ? "No machines declared"
                  : missingRateCount === 0
                    ? `${machineCount} machine${machineCount === 1 ? "" : "s"} owned · all rates declared`
                    : `${machineCount} machine${machineCount === 1 ? "" : "s"} owned · ${missingRateCount} rate${missingRateCount === 1 ? "" : "s"} missing`}
            </p>
            <p style={{ margin: "5px 0 0", fontSize: 12, color: machineCount && missingRateCount === 0 ? C.ink45 : C.cond }}>
              {machineCount == null || missingRateCount == null
                ? unavailable.machines ? "retry organization data above" : "checking machine rates..."
                : machineCount === 0
                ? "declare your floor — everything starts from the denominator"
                : missingRateCount === 0
                  ? "marginal costing uses your declared hourly rates"
                  : "set hourly rates before relying on marginal cost"}
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
                ? unavailable.actuals ? "ground truth unavailable — retry organization data above" : "loading…"
                : actuals === 0
                  ? "n=0 · every band still hatched — send actuals back to flip them"
                  : `${NUM(actuals)} actual${actuals === 1 ? "" : "s"} received · bands flip solid as each process reaches enough residuals`}
            </p>
          </button>

          {/* ACTIVITY */}
          <section style={{ border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "16px 18px" }}>
            <Kicker>ACTIVITY</Kicker>
            {records == null && changeRequests == null ? (
              <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: unavailable.records || unavailable.changes ? C.fail : C.ink45 }}>
                {unavailable.records || unavailable.changes ? "activity unavailable — retry organization data above" : "loading…"}
              </p>
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
