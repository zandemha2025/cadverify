"use client";

/**
 * RECORDS — the system of record, real GET /api/v1/cost-decisions (list) +
 * /cost-decisions/{id} (detail). Every verification is a keepable artifact with
 * its verdict and receipts. Empty list → the honest "no records yet" state.
 *
 * Opening a record renders the read-only SHARED-RECORD view: the drivers with
 * their provenance and sources, the sum, the honest (hatched = assumption)
 * confidence band, and the export / share actions — all wired to the real
 * endpoints (export.json | export.csv | /pdf, POST/DELETE /{id}/share). The
 * receiver can open every number; no one can edit one. Records are immutable and
 * PINNED to the rate version they were computed under — a calibration switch
 * never rewrites them. Nothing on screen is fabricated: every value is an engine
 * output or is withheld.
 */
import { useCallback, useEffect, useState } from "react";
import {
  fetchCostDecisions,
  fetchCostDecision,
  shareCostDecision,
  unshareCostDecision,
  downloadCostPdf,
  exportCostCsv,
  exportCostJson,
  type CostDecisionSummary,
  type CostDecisionDetail,
} from "@/lib/api";
import { C, MONO, USD, NUM, procLabel, normProv } from "@/lib/verify/tokens";
import { makeNowEstimate, driverViews } from "@/lib/verify/derive";
import { recordVerdictModel, type Tone } from "@/lib/verify/verification";
import {
  Kicker,
  ProvDot,
  ProvChip,
  GhostButton,
  EmptyState,
  Spinner,
  ConfidenceBand,
} from "./primitives";
import { useToast } from "./toast";

const PAGE = 50;

export function RecordsScreen({ nav }: { nav: (s: string) => void }) {
  const [rows, setRows] = useState<CostDecisionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const page = await fetchCostDecisions({ limit: PAGE });
      setRows(page.cost_decisions);
      setCursor(page.next_cursor);
      setHasMore(page.has_more);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load records");
      setRows([]);
      setCursor(null);
      setHasMore(false);
    }
  }, []);

  const loadMore = useCallback(async () => {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await fetchCostDecisions({ limit: PAGE, cursor });
      setRows((prev) => [...(prev ?? []), ...page.cost_decisions]);
      setCursor(page.next_cursor);
      setHasMore(page.has_more);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load more records");
    } finally {
      setLoadingMore(false);
    }
  }, [cursor, loadingMore]);

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
            <span style={{ border: `1px solid ${C.ink}`, background: C.ink, color: "#fff", borderRadius: 999, padding: "6px 14px", fontSize: 12 }}>
              {hasMore ? `Loaded ${rows.length}${cursor ? "+" : ""}` : `All · ${rows.length}`}
            </span>
            <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>immutable · nothing is ever deleted</span>
          </div>
          <div style={{ marginTop: 18, border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, overflow: "hidden", maxWidth: 1100 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 90px 120px 60px", gap: 12, padding: "12px 20px", borderBottom: `1px solid ${C.hair2}`, fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", color: C.ink40 }}>
              <span>PART</span><span>MAKE-NOW ROUTE</span><span>CROSSOVER</span><span>QTYS</span><span>DATE</span><span></span>
            </div>
            {rows.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setOpenId(r.id)}
                style={{ width: "100%", display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 90px 120px 60px", gap: 12, alignItems: "center", padding: "14px 20px", border: "none", borderBottom: `1px solid #f0f0f3`, background: "none", cursor: "pointer", fontFamily: MONO, fontSize: 12, color: "inherit", textAlign: "left" }}
              >
                <span style={{ color: C.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.label || r.filename}</span>
                <span style={{ color: C.ink55 }}>{procLabel(r.make_now_process)}</span>
                <span style={{ color: C.ink55 }}>{r.crossover_qty != null ? NUM(r.crossover_qty) : "—"}</span>
                <span style={{ color: C.ink45 }}>{r.quantities.length}</span>
                <span style={{ color: C.ink45 }}>{new Date(r.created_at).toLocaleDateString()}</span>
                <span style={{ color: r.is_public ? C.measured : C.ink35, fontSize: 11, textAlign: "right" }}>
                  {r.is_public ? "shared →" : "open →"}
                </span>
              </button>
            ))}
          </div>
          {hasMore && (
            <div style={{ marginTop: 14, maxWidth: 1100, display: "flex", alignItems: "center", gap: 12 }}>
              <GhostButton onClick={() => void loadMore()} disabled={loadingMore}>
                {loadingMore ? "Loading…" : "Load more"}
              </GhostButton>
              <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink40 }}>more records beyond the {rows.length} loaded — cursor-paged</span>
            </div>
          )}
          <p style={{ margin: "16px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink35 }}>
            a shared record renders read-only with full provenance — the receiver can open every number, not edit it
          </p>
        </>
      )}

      {openId && <RecordDetail id={openId} onClose={() => setOpenId(null)} />}
    </main>
  );
}

/** Format a driver value verbatim: engine currency drivers carry unit "$"/"usd";
 *  everything else keeps its own unit (hr, kg, …). No fabrication — value as-is. */
function fmtDriverValue(value: number, unit: string): string {
  const u = (unit || "").toLowerCase();
  if (u === "$" || u === "usd") return USD(value);
  return unit && unit !== "$" ? `${NUM(value)} ${unit}` : NUM(value);
}

const VERDICT_COLOR: Record<Tone, string> = {
  pass: C.pass,
  cond: C.cond,
  fail: C.fail,
  neutral: C.ink45,
};

function RecordDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const toast = useToast();
  const [detail, setDetail] = useState<CostDecisionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchCostDecision(id).then(
      (d) => {
        if (!alive) return;
        setDetail(d);
        setShareUrl(d.share_url);
      },
      (e) => alive && setError(e instanceof Error ? e.message : "load failed")
    );
    return () => {
      alive = false;
    };
  }, [id]);

  const est = detail?.result ? makeNowEstimate(detail.result) : null;
  const drivers = driverViews(est);
  const conf = est?.confidence ?? null;
  const verdictModel = detail
    ? recordVerdictModel(detail.result, {
        hasCostedRoute: Boolean(detail.make_now_process && est),
        dfmReady: est?.dfm_ready,
        dfmVerdict: est?.dfm_verdict,
      })
    : null;
  const v = verdictModel
    ? { ...verdictModel, color: VERDICT_COLOR[verdictModel.tone] }
    : { text: "", kicker: "", tone: "neutral" as Tone, color: C.ink };
  const material = detail?.result?.decision?.make_now_material ?? null;

  const pf =
    conf && conf.high_usd > conf.low_usd
      ? (conf.point_usd - conf.low_usd) / (conf.high_usd - conf.low_usd)
      : 0.5;

  const filename = detail?.filename ?? "record";
  const fullShareUrl =
    shareUrl && typeof window !== "undefined"
      ? `${window.location.origin}${shareUrl}`
      : shareUrl;

  const run = async (name: string, fn: () => Promise<void>, ok?: string) => {
    if (busy) return;
    setBusy(name);
    try {
      await fn();
      if (ok) toast(ok);
    } catch (e) {
      toast(`${name} failed — ${e instanceof Error ? e.message : "error"}`);
    } finally {
      setBusy(null);
    }
  };

  const createShare = () =>
    run(
      "create share link",
      async () => {
        const res = await shareCostDecision(id);
        setShareUrl(res.share_url);
      },
      "share link created — read-only, provenance travels with it"
    );

  const revokeShare = () =>
    run(
      "revoke share link",
      async () => {
        await unshareCostDecision(id);
        setShareUrl(null);
      },
      "share link revoked — the public link 404s immediately"
    );

  const copyLink = async () => {
    if (!fullShareUrl) return;
    try {
      await navigator.clipboard.writeText(fullShareUrl);
      toast("share link copied to clipboard");
    } catch {
      toast(`share link — ${fullShareUrl}`);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 60, background: "rgba(23,24,26,0.4)", backdropFilter: "blur(3px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 30 }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 680, maxWidth: "100%", maxHeight: "88vh", overflowY: "auto", background: C.panel, border: `1px solid ${C.hair}`, borderRadius: 18, boxShadow: "0 18px 50px -18px rgba(23,24,26,0.35)", padding: "26px 28px", animation: "vscreenIn 220ms cubic-bezier(0.2,0,0,1) both" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Kicker>{shareUrl ? "SHARED RECORD" : "RECORD"} · READ-ONLY</Kicker>
          <span style={{ fontFamily: MONO, fontSize: 9.5, border: `1px solid ${C.hair}`, borderRadius: 4, padding: "2px 7px", color: C.ink45 }}>PROVENANCE TRAVELS WITH IT</span>
          <button type="button" onClick={onClose} style={{ marginLeft: "auto", background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 14, color: C.ink40 }}>✕</button>
        </div>

        {error && <p style={{ marginTop: 16, fontFamily: MONO, fontSize: 11, color: C.fail }}>{error}</p>}
        {!detail && !error && <div style={{ marginTop: 16 }}><Spinner label="loading record…" /></div>}

        {detail && (
          <>
            <h2 style={{ margin: "14px 0 0", fontSize: 24, fontWeight: 300, letterSpacing: "-0.015em" }}>
              {detail.label || detail.filename} — <span style={{ color: v.color }}>{v.text}</span>
            </h2>
            <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink50 }}>
              {detail.filename}
              {detail.make_now_process ? ` · ${procLabel(detail.make_now_process)}` : ""}
              {material ? ` (${material})` : ""}
              {" · "}
              {new Date(detail.created_at).toLocaleString()}
              {detail.engine_version ? ` · engine ${detail.engine_version}` : ""}
            </p>
            <p style={{ margin: "4px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
              pinned to the rate version it was computed under — a calibration switch never rewrites it
            </p>

            <div
              data-testid="record-disposition-summary"
              style={{ marginTop: 14, border: `1px solid ${C.hair}`, borderRadius: 10, padding: "11px 12px", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}
            >
              <span style={{ fontFamily: MONO, fontSize: 9.5, color: C.ink45, letterSpacing: "0.08em" }}>
                RECORDED OUTCOME
              </span>
              <strong style={{ fontSize: 12.5, color: detail.user_disposition ? C.pass : C.cond }}>
                {detail.user_disposition_label ?? "Not decided"}
              </strong>
              <a
                href={`/cost-decisions/${id}`}
                style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 10.5, color: C.ink, textDecoration: "underline", textUnderlineOffset: 3 }}
              >
                Open governance →
              </a>
              {detail.disposition_note && (
                <p
                  data-testid="record-disposition-note-summary"
                  style={{ width: "100%", margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontFamily: MONO, fontSize: 10.5, color: C.ink50, lineHeight: 1.6 }}
                >
                  {detail.disposition_note}
                </p>
              )}
            </div>

            {drivers.length > 0 ? (
              <div style={{ marginTop: 18, borderTop: `1px solid #efeff2`, paddingTop: 6 }}>
                {drivers.map((d) => (
                  <div key={d.name} style={{ padding: "11px 2px", borderBottom: `1px solid #f0f0f3` }}>
                    <div style={{ display: "flex", alignItems: "baseline", gap: 10, fontFamily: MONO, fontSize: 12.5 }}>
                      <span style={{ color: C.ink70, display: "inline-flex", alignItems: "center", gap: 6 }}>
                        <ProvDot p={normProv(d.provenance)} /> {d.label}
                      </span>
                      <span style={{ marginLeft: "auto", color: C.ink, fontWeight: 600 }}>
                        {fmtDriverValue(d.value, d.unit)}
                      </span>
                      <ProvChip p={normProv(d.provenance)} />
                    </div>
                    {d.source && (
                      <p style={{ margin: "5px 0 0", fontFamily: MONO, fontSize: 10, lineHeight: 1.65, color: C.ink40 }}>{d.source}</p>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p style={{ marginTop: 18, fontFamily: MONO, fontSize: 11, color: C.ink45 }}>
                estimate withheld — this record carries no costed make-now route.
              </p>
            )}

            {est && (
              <>
                <div style={{ marginTop: 12, display: "flex", justifyContent: "space-between", fontFamily: MONO, fontSize: 12.5 }}>
                  <span style={{ color: C.ink55 }}>Σ line items = unit resource cost</span>
                  <span style={{ color: v.color }}>{USD(est.unit_cost_usd)}{v.tone === "pass" ? " ✓" : ""}</span>
                </div>
                <div style={{ marginTop: 12 }}>
                  <ConfidenceBand validated={conf?.validated ?? false} pointFraction={pf} />
                </div>
                <p style={{ margin: "7px 0 0", fontFamily: MONO, fontSize: 10 }}>
                  {conf ? (
                    <span style={{ color: conf.validated ? C.pass : C.cond }}>
                      {USD(conf.low_usd)} – {USD(conf.high_usd)} · ±{Math.round(conf.half_width_pct)}%{" "}
                      {conf.validated ? `· validated · n=${conf.n_samples}` : `[assumption, not shop-validated] · n=${conf.n_samples}`}
                    </span>
                  ) : (
                    <span style={{ color: C.cond }}>±{Math.round(est.est_error_band_pct)}% assumption band</span>
                  )}
                </p>
              </>
            )}

            <div style={{ marginTop: 16, borderTop: `1px solid #efeff2`, paddingTop: 12, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
              <ExportButton label={busy === "Export PDF" ? "Exporting…" : "Export PDF"} disabled={!!busy} onClick={() => run("Export PDF", () => downloadCostPdf(id, filename))} />
              <ExportButton label={busy === "CSV (drivers)" ? "Exporting…" : "CSV (drivers)"} disabled={!!busy} onClick={() => run("CSV (drivers)", () => exportCostCsv(id, filename))} />
              <ExportButton label={busy === "JSON" ? "Exporting…" : "JSON"} disabled={!!busy} onClick={() => run("JSON", () => exportCostJson(id, filename))} />
              {shareUrl ? (
                <>
                  <ExportButton label="Copy share link" disabled={!!busy} onClick={() => void copyLink()} />
                  <ExportButton label={busy === "revoke share link" ? "Revoking…" : "Revoke share"} disabled={!!busy} danger onClick={() => void revokeShare()} />
                </>
              ) : (
                <ExportButton label={busy === "create share link" ? "Creating…" : "Create share link"} disabled={!!busy} onClick={() => void createShare()} />
              )}
              <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>computed evidence is immutable</span>
            </div>

            {shareUrl && (
              <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10, color: C.measured, wordBreak: "break-all" }}>
                public link · {fullShareUrl}
              </p>
            )}

            <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10, lineHeight: 1.7, color: C.ink40 }}>
              the receiver can open every number — not edit one. This page is the org&apos;s make-vs-buy memory, one record at a time.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function ExportButton({
  label,
  onClick,
  disabled,
  danger,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        background: "none",
        border: `1px solid ${danger ? "rgba(194,69,58,0.4)" : "#d8d8dc"}`,
        borderRadius: 999,
        color: danger ? C.fail : C.ink,
        padding: "7px 15px",
        fontSize: 11.5,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        fontFamily: "inherit",
      }}
    >
      {label}
    </button>
  );
}
