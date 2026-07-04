"use client";

/**
 * RECORDS — the system of record, real GET /api/v1/cost-decisions (list) +
 * /cost-decisions/{id} (detail). Every verification is a keepable artifact with
 * its verdict and receipts. Empty list → the honest "no records yet" state.
 * The shared read-only record view is time-boxed IN DEVELOPMENT.
 */
import { useCallback, useEffect, useState } from "react";
import {
  fetchCostDecisions,
  fetchCostDecision,
  type CostDecisionSummary,
  type CostDecisionDetail,
} from "@/lib/api";
import { C, MONO, USD, NUM, procLabel } from "@/lib/verify/tokens";
import { makeNowEstimate, driverViews } from "@/lib/verify/derive";
import { Kicker, ProvChip, GhostButton, EmptyState, Spinner, InDev } from "./primitives";
import { normProv } from "@/lib/verify/tokens";

export function RecordsScreen({ nav }: { nav: (s: string) => void }) {
  const [rows, setRows] = useState<CostDecisionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const page = await fetchCostDecisions({ limit: 50 });
      setRows(page.cost_decisions);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load records");
      setRows([]);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <main style={{ animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both", flex: 1, overflowY: "auto", padding: "30px 34px", background: C.bg }}>
      <h1 style={{ margin: 0, fontSize: 26, fontWeight: 300, letterSpacing: "-0.015em" }}>Records</h1>
      <p style={{ margin: "8px 0 0", maxWidth: 640, fontSize: 14, lineHeight: 1.6, color: C.ink55 }}>
        Every verification is a keepable, shareable artifact — the org&apos;s make-vs-buy memory. A record carries its
        world, its verdict, its receipts, and whoever decided.
      </p>

      {error && <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: C.fail }}>couldn&apos;t load records — {error}</p>}

      {rows === null ? (
        <div style={{ marginTop: 24 }}><Spinner label="loading records…" /></div>
      ) : rows.length === 0 ? (
        <div style={{ marginTop: 24, maxWidth: 640 }}>
          <EmptyState
            title="No records yet — and that's the point."
            body="Your first verification becomes your first record: a keepable artifact with its world, its verdict, and every receipt. This page becomes the org's make-vs-buy memory."
          >
            <GhostButton primary onClick={() => nav("verify")}>Verify your first part</GhostButton>
          </EmptyState>
        </div>
      ) : (
        <>
          <div style={{ marginTop: 18, display: "flex", alignItems: "center", gap: 8, maxWidth: 1100 }}>
            <span style={{ border: `1px solid ${C.ink}`, background: C.ink, color: "#fff", borderRadius: 999, padding: "6px 14px", fontSize: 12 }}>All · {rows.length}</span>
            <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>immutable · nothing is ever deleted</span>
          </div>
          <div style={{ marginTop: 18, border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, overflow: "hidden", maxWidth: 1100 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 90px 120px", gap: 12, padding: "12px 20px", borderBottom: `1px solid ${C.hair2}`, fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", color: C.ink40 }}>
              <span>PART</span><span>MAKE-NOW ROUTE</span><span>CROSSOVER</span><span>QTYS</span><span>DATE</span>
            </div>
            {rows.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setOpenId(r.id)}
                style={{ width: "100%", display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 90px 120px", gap: 12, alignItems: "center", padding: "14px 20px", border: "none", borderBottom: `1px solid #f0f0f3`, background: "none", cursor: "pointer", fontFamily: MONO, fontSize: 12, color: "inherit", textAlign: "left" }}
              >
                <span style={{ color: C.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.label || r.filename}</span>
                <span style={{ color: C.ink55 }}>{procLabel(r.make_now_process)}</span>
                <span style={{ color: C.ink55 }}>{r.crossover_qty != null ? NUM(r.crossover_qty) : "—"}</span>
                <span style={{ color: C.ink45 }}>{r.quantities.length}</span>
                <span style={{ color: C.ink45 }}>{new Date(r.created_at).toLocaleDateString()}</span>
              </button>
            ))}
          </div>
          <p style={{ margin: "16px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink35 }}>
            a shared record renders read-only with full provenance — the receiver can open every number, not edit it{" "}
            <InDev label="SHARED VIEW — IN DEVELOPMENT" />
          </p>
        </>
      )}

      {openId && <RecordDetail id={openId} onClose={() => setOpenId(null)} />}
    </main>
  );
}

function RecordDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const [detail, setDetail] = useState<CostDecisionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCostDecision(id).then(setDetail, (e) => setError(e instanceof Error ? e.message : "load failed"));
  }, [id]);

  const est = detail?.result ? makeNowEstimate(detail.result) : null;
  const drivers = driverViews(est);

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 60, background: "rgba(23,24,26,0.35)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 640, maxWidth: "100%", maxHeight: "90vh", overflowY: "auto", background: C.panel, border: `1px solid ${C.hair}`, borderRadius: 18, boxShadow: "0 18px 50px -18px rgba(23,24,26,0.35)", padding: 24, animation: "vscreenIn 220ms cubic-bezier(0.2,0,0,1) both" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <p style={{ margin: 0, fontSize: 18, fontWeight: 500 }}>{detail?.label || detail?.filename || "Record"}</p>
          <button type="button" onClick={onClose} style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", fontFamily: MONO, fontSize: 14, color: C.ink40 }}>✕</button>
        </div>
        {error && <p style={{ marginTop: 14, fontFamily: MONO, fontSize: 11, color: C.fail }}>{error}</p>}
        {!detail && !error && <div style={{ marginTop: 16 }}><Spinner label="loading record…" /></div>}
        {detail && (
          <>
            <p style={{ margin: "6px 0 16px", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>
              {new Date(detail.created_at).toLocaleString()} · engine {detail.engine_version ?? "—"}
            </p>
            <div style={{ border: `1.5px solid rgba(31,138,91,0.4)`, borderRadius: 14, background: "rgba(31,138,91,0.03)", padding: "16px 18px" }}>
              <Kicker color={C.pass}>MAKE-NOW · {procLabel(detail.make_now_process)}</Kicker>
              <p style={{ margin: "8px 0 0", fontSize: 22, fontWeight: 400 }}>
                {USD(est?.unit_cost_usd)} <span style={{ fontSize: 13, color: C.ink45 }}>/unit</span>
              </p>
              <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink50 }}>
                crossover {detail.crossover_qty != null ? NUM(detail.crossover_qty) : "—"} · {est?.confidence?.label ?? (est ? `±${Math.round(est.est_error_band_pct)}% assumption band` : "band withheld")}
              </p>
            </div>
            <Kicker color={C.ink45}>DRIVERS — EVERY NUMBER SOURCED</Kicker>
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column" }}>
              {drivers.map((d) => (
                <div key={d.name} style={{ display: "flex", alignItems: "baseline", gap: 12, padding: "10px 2px", borderBottom: `1px solid #f0f0f3` }}>
                  <span style={{ fontSize: 13, color: C.ink, minWidth: 130 }}>{d.label}</span>
                  <span style={{ fontFamily: MONO, fontSize: 12, color: C.ink }}>{d.unit === "usd" ? USD(d.value) : NUM(d.value)}</span>
                  <span style={{ marginLeft: "auto" }}><ProvChip p={normProv(d.provenance)} /></span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
