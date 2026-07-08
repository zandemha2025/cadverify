"use client";

/**
 * TRIAGE AT SCALE — the whole org inventory walked through the same verification
 * and collapsed into honest makeability buckets. Real GET /api/v1/catalog/makeability
 * (the four design buckets + unknown + geometry_invalid, a SQL GROUP BY over the
 * materialized part-summary projection — sums to total, nothing silently skipped)
 * and GET /api/v1/catalog/capability-investment (which ONE acquisition unlocks the
 * most currently-blocked parts). Every count opens into its verdicts via the
 * keyset drill-down. Empty org → the honest empty state; a cold projection says so.
 *
 * HONESTY: no design fixtures. No acquisition dollar cost is invented (none is
 * engine-derived). Stale verdicts (computed before a machine change) are counted,
 * flagged, never served as fresh. Recreated in the light-instrument register.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { C, MONO, NUM, procLabel } from "@/lib/verify/tokens";
import { Kicker, EmptyState, Spinner, GhostButton } from "./primitives";
import {
  fetchMakeability,
  fetchMakeabilityBucket,
  fetchCapabilityInvestment,
  fetchCapabilityUnlocked,
  importManifestCsv,
  verdictPhrase,
  type MakeabilityRollup,
  type MakeabilitySummary,
  type MakeabilityBucketKey,
  type MakeabilityRow,
  type CapabilityRanking,
  type CapabilityEntry,
} from "@/lib/verify/triage-api";

/** Translucent fill from an opaque hex — the design's soft bucket tint. */
function tint(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

interface BucketDef {
  key: MakeabilityBucketKey;
  label: string;
  desc: string;
  color: string;
  primary: boolean;
}

// The four primary design buckets (in-house / outside / capability / not-makeable),
// then the two honesty buckets that keep the sum whole (unknown / geometry_invalid).
const BUCKETS: BucketDef[] = [
  {
    key: "makeable_in_house",
    label: "Makeable in-house",
    desc: "Verified against your envelopes, materials, and physics. Marginal-costed on owned machines.",
    color: C.pass,
    primary: true,
  },
  {
    key: "makeable_outside",
    label: "Makeable outside",
    desc: "No owned route passes, but a standard process does. Candidates for the supplier book.",
    color: C.measured,
    primary: true,
  },
  {
    key: "needs_capability",
    label: "Needs new capability",
    desc: "Feasible only on equipment you don't own — each carries its acquisition consideration.",
    color: C.cond,
    primary: true,
  },
  {
    key: "not_makeable",
    label: "Not makeable as drawn",
    desc: "Fails physics on every route, with the measured blocker named. Redesign targets.",
    color: C.fail,
    primary: true,
  },
  {
    key: "unknown",
    label: "Evaluation required",
    desc: "No declared inventory or costed verdict against one. Never assumed makeable.",
    color: C.def,
    primary: false,
  },
  {
    key: "geometry_invalid",
    label: "Invalid geometry",
    desc: "The geometry itself is invalid — surfaced for repair, never silently skipped.",
    color: C.ink,
    primary: false,
  },
];

export function TriageScreen({ nav }: { nav: (s: string) => void }) {
  const [rollup, setRollup] = useState<MakeabilityRollup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [capability, setCapability] = useState<CapabilityRanking | null>(null);
  const [open, setOpen] = useState<MakeabilityBucketKey | null>(null);

  useEffect(() => {
    fetchMakeability().then(
      (r) => {
        setRollup(r);
        setError(null);
      },
      (e) => {
        setError(e instanceof Error ? e.message : "Could not load triage");
        setRollup(null);
      }
    );
    // The capability ranking is a second cheap GROUP BY; a failure here never
    // blocks the buckets — the panel just stays absent.
    fetchCapabilityInvestment().then(setCapability, () => setCapability(null));
  }, []);

  const s = rollup?.summary;
  const total = s?.total ?? 0;

  return (
    <main
      style={{
        animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both",
        flex: 1,
        overflowY: "auto",
        padding: "30px 34px",
        background: C.bg,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 300, letterSpacing: "-0.015em" }}>
          Triage at scale
        </h1>
      </div>
      <p style={{ margin: "8px 0 0", maxWidth: 660, fontSize: 14, lineHeight: 1.6, color: C.ink55 }}>
        {total > 0 ? (
          <>
            {NUM(total)} part{total === 1 ? "" : "s"}, each walked through the same verification. The
            catalog collapses into honest makeability buckets — no part is scored without a reason you
            can open.
          </>
        ) : (
          <>Your whole inventory, walked through the same verification and collapsed into honest
          makeability buckets — nothing silently skipped, every count opens into its verdicts.</>
        )}
      </p>

      {error && (
        <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: C.fail }}>
          couldn&apos;t load triage — {error}
        </p>
      )}

      {rollup === null && !error && (
        <div style={{ marginTop: 24 }}>
          <Spinner label="reading the makeability projection…" />
        </div>
      )}

      {rollup && s && total === 0 && (
        <TriageEmpty rollup={rollup} nav={nav} />
      )}

      {rollup && s && total > 0 && (
        <>
          {/* honesty notes surfaced verbatim from the engine, never hidden */}
          {(rollup.stale_note || rollup.evaluation_note || rollup.note) && (
            <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 6, maxWidth: 720 }}>
              {rollup.evaluation_note && (
                <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, color: C.cond }}>{rollup.evaluation_note}</p>
              )}
              {rollup.stale_note && (
                <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, color: C.cond }}>{rollup.stale_note}</p>
              )}
              {rollup.note && (
                <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>{rollup.note}</p>
              )}
            </div>
          )}

          {/* the stacked bucket bar — every non-zero bucket, proportional, sums to total */}
          <BucketBar summary={s} total={total} />

          {/* the four primary bucket cards */}
          <div style={{ marginTop: 18, display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, maxWidth: 1180 }}>
            {BUCKETS.filter((b) => b.primary).map((b) => (
              <BucketCard
                key={b.key}
                def={b}
                count={(s as unknown as Record<string, number>)[b.key] ?? 0}
                total={total}
                active={open === b.key}
                onOpen={() => setOpen((k) => (k === b.key ? null : b.key))}
              />
            ))}
          </div>

          {/* the two honesty buckets — only when non-empty, never silently dropped */}
          {(s.unknown > 0 || s.geometry_invalid > 0) && (
            <div style={{ marginTop: 12, display: "flex", gap: 10, flexWrap: "wrap", maxWidth: 1180 }}>
              {BUCKETS.filter((b) => !b.primary && ((s as unknown as Record<string, number>)[b.key] ?? 0) > 0).map((b) => {
                const count = (s as unknown as Record<string, number>)[b.key] ?? 0;
                const active = open === b.key;
                return (
                  <button
                    key={b.key}
                    type="button"
                    onClick={() => setOpen((k) => (k === b.key ? null : b.key))}
                    title={b.desc}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 9,
                      cursor: "pointer",
                      fontFamily: "inherit",
                      color: "inherit",
                      textAlign: "left",
                      border: `1.5px solid ${active ? C.ink : C.hair}`,
                      borderRadius: 999,
                      background: C.panel,
                      padding: "8px 15px",
                    }}
                  >
                    <span aria-hidden style={{ width: 8, height: 8, borderRadius: "50%", background: b.color, flexShrink: 0 }} />
                    <span style={{ fontFamily: MONO, fontSize: 13, fontWeight: 500, color: b.color }}>{NUM(count)}</span>
                    <span style={{ fontSize: 12.5 }}>{b.label}</span>
                  </button>
                );
              })}
            </div>
          )}

          {/* drill-down: every count opens into its verdicts */}
          {open && (
            <BucketDrillDown
              key={open}
              bucketKey={open}
              def={BUCKETS.find((b) => b.key === open)!}
              count={(s as unknown as Record<string, number>)[open] ?? 0}
              capability={open === "needs_capability" ? capability : null}
              onClose={() => setOpen(null)}
              nav={nav}
            />
          )}

          <p style={{ margin: "18px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink35, maxWidth: 720, lineHeight: 1.6 }}>
            {s.geometry_invalid > 0 && (
              <>
                {NUM(s.geometry_invalid)} part{s.geometry_invalid === 1 ? " has" : "s have"} invalid geometry — surfaced for
                repair, never silently skipped ·{" "}
              </>
            )}
            every bucket count opens into its verdicts · buckets sum to {NUM(total)} — a projection of the verification
            the cost path already computed, never re-invented
          </p>
        </>
      )}
    </main>
  );
}

// ── the honest empty / cold-projection state ────────────────────────────────
function TriageEmpty({ rollup, nav }: { rollup: MakeabilityRollup; nav: (s: string) => void }) {
  const cold = rollup.cold_projection;
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);

  const onManifest = useCallback(async (file: File) => {
    setBusy(true);
    setSummary(null);
    try {
      const s = await importManifestCsv(file);
      const msg = `${s.imported} imported · ${s.updated} updated · ${s.skipped} skipped`;
      setSummary(msg);
      toast.success(`Manifest import complete — ${msg}`);
      if (s.errors.length) {
        toast.message(`${s.errors.length} row error(s)`, {
          description: s.errors.slice(0, 3).map((e) => `line ${e.line}: ${e.reason}`).join(" · "),
        });
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "manifest import failed";
      setSummary(msg);
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  }, []);

  return (
    <div style={{ marginTop: 26, maxWidth: 660 }}>
      <EmptyState
        title={cold ? "The makeability projection is cold." : "No parts to triage yet."}
        body={
          cold
            ? rollup.note ??
              "This org has parts, but the makeability projection has not been populated (they predate it, or the one-time backfill has not run). Re-cost parts to populate the in-house breakdown."
            : "Verify parts — or import a whole BOM — and the catalog collapses into honest makeability buckets: makeable in-house, outside, needs new capability, not makeable as drawn. Failures surface live; nothing is silently skipped, and every count opens into its verdicts."
        }
      >
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
          <GhostButton primary onClick={() => nav("verify")}>
            Verify a part
          </GhostButton>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,text/csv"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void onManifest(f);
              e.target.value = "";
            }}
          />
          <GhostButton onClick={() => fileRef.current?.click()} disabled={busy}>
            {busy ? "Importing…" : "Import manifest CSV"}
          </GhostButton>
          <p style={{ margin: 0, display: "flex", alignItems: "center", gap: 8, fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
            {summary ?? "bulk BOM ingest posts to /manifest/import with per-line errors"}
          </p>
        </div>
      </EmptyState>
    </div>
  );
}

// ── the stacked bucket bar ──────────────────────────────────────────────────
function BucketBar({
  summary,
  total,
}: {
  summary: MakeabilitySummary;
  total: number;
}) {
  const counts = summary as unknown as Record<string, number>;
  const segs = BUCKETS.map((b) => ({ ...b, count: counts[b.key] ?? 0 })).filter((b) => b.count > 0);
  return (
    <div
      style={{
        marginTop: 26,
        display: "flex",
        height: 46,
        borderRadius: 12,
        overflow: "hidden",
        fontFamily: MONO,
        fontSize: 11,
        maxWidth: 1180,
      }}
    >
      {segs.map((seg, i) => {
        const pct = (seg.count / total) * 100;
        const first = i === 0;
        const last = i === segs.length - 1;
        return (
          <div
            key={seg.key}
            title={`${seg.label} — ${seg.count} of ${total}`}
            style={{
              width: `${pct}%`,
              minWidth: 22,
              background: tint(seg.color, 0.12),
              border: `1px solid ${tint(seg.color, 0.3)}`,
              borderLeft: first ? undefined : "none",
              borderRadius: first ? "12px 0 0 12px" : last ? "0 12px 12px 0" : undefined,
              display: "flex",
              alignItems: "center",
              justifyContent: pct < 6 ? "center" : "flex-start",
              padding: pct < 6 ? 0 : "0 14px",
              color: seg.color,
              whiteSpace: "nowrap",
              overflow: "hidden",
            }}
          >
            {pct < 6 ? NUM(seg.count) : `${NUM(seg.count)} · ${seg.label.toLowerCase()}`}
          </div>
        );
      })}
    </div>
  );
}

// ── one primary bucket card ─────────────────────────────────────────────────
function BucketCard({
  def,
  count,
  total,
  active,
  onOpen,
}: {
  def: BucketDef;
  count: number;
  total: number;
  active: boolean;
  onOpen: () => void;
}) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <button
      type="button"
      onClick={onOpen}
      style={{
        textAlign: "left",
        fontFamily: "inherit",
        color: "inherit",
        cursor: "pointer",
        border: `1.5px solid ${active ? C.ink : C.hair}`,
        borderRadius: 14,
        background: C.panel,
        padding: "18px 20px",
        transition: "border-color 150ms",
      }}
    >
      <p style={{ margin: 0, fontSize: 30, fontWeight: 300, letterSpacing: "-0.02em", color: def.color }}>
        {NUM(count)}
      </p>
      <p style={{ margin: "6px 0 0", fontSize: 13.5, fontWeight: 500 }}>{def.label}</p>
      <p style={{ margin: "8px 0 0", fontSize: 12, lineHeight: 1.6, color: C.ink50 }}>{def.desc}</p>
      <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
        {pct}% · {active ? "open — showing verdicts" : "open its verdicts"}
      </p>
    </button>
  );
}

// ── the drill-down: one keyset page of a bucket's parts, each with its why ───
function BucketDrillDown({
  bucketKey,
  def,
  count,
  capability,
  onClose,
  nav,
}: {
  bucketKey: MakeabilityBucketKey;
  def: BucketDef;
  count: number;
  capability: CapabilityRanking | null;
  onClose: () => void;
  nav: (s: string) => void;
}) {
  const [rows, setRows] = useState<MakeabilityRow[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    fetchMakeabilityBucket(bucketKey).then(
      (p) => {
        setRows(p.rows);
        setCursor(p.next_cursor);
        setErr(null);
      },
      (e) => {
        setErr(e instanceof Error ? e.message : "load failed");
        setRows([]);
      }
    );
  }, [bucketKey]);

  const loadMore = useCallback(async () => {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const p = await fetchMakeabilityBucket(bucketKey, cursor);
      setRows((prev) => [...(prev ?? []), ...p.rows]);
      setCursor(p.next_cursor);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoadingMore(false);
    }
  }, [bucketKey, cursor, loadingMore]);

  return (
    <div
      style={{
        marginTop: 16,
        border: `1.5px solid ${C.ink}`,
        borderRadius: 16,
        background: C.panel,
        padding: "20px 24px",
        maxWidth: 1180,
        animation: "vstepIn 300ms cubic-bezier(0.2,0,0,1) both",
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <p style={{ margin: 0, fontSize: 16, fontWeight: 500 }}>
          {def.label} — {NUM(count)} part{count === 1 ? "" : "s"}
        </p>
        <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
          each row opens its verdict · keyset-paged, whole inventory
        </span>
        <button
          type="button"
          onClick={onClose}
          style={{ marginLeft: "auto", background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 12, color: C.ink40 }}
        >
          ✕
        </button>
      </div>

      {err && <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 11, color: C.fail }}>{err}</p>}
      {rows === null && !err && (
        <div style={{ marginTop: 12 }}>
          <Spinner label="loading verdicts…" />
        </div>
      )}
      {rows && rows.length === 0 && !err && (
        <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink45 }}>
          no parts currently in this bucket.
        </p>
      )}

      {rows && rows.length > 0 && (
        <div style={{ marginTop: 10, display: "flex", flexDirection: "column" }}>
          {rows.map((r) => (
            <PartRow key={r.part_key} row={r} nav={nav} />
          ))}
        </div>
      )}

      {cursor && (
        <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 12 }}>
          <GhostButton onClick={() => void loadMore()} disabled={loadingMore}>
            {loadingMore ? "Loading…" : "Load more verdicts"}
          </GhostButton>
          <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
            more parts beyond the {rows?.length} loaded — cursor-paged
          </span>
        </div>
      )}

      {/* the capability-investment ranking, inside the capability bucket */}
      {bucketKey === "needs_capability" && (
        <CapabilityPanel capability={capability} nav={nav} />
      )}
    </div>
  );
}

// ── one drill-down part row ─────────────────────────────────────────────────
function PartRow({ row, nav }: { row: MakeabilityRow; nav: (s: string) => void }) {
  const route = row.recommended_route?.process ?? null;
  const gate = row.makeability?.gap?.gate ?? null;
  const bits: string[] = [verdictPhrase(row.makeability?.verdict ?? null)];
  if (route) bits.push(`route ${procLabel(route)}`);
  if (gate) bits.push(`${gate} gap`);
  if (row.makeability?.stale) bits.push("verdict STALE — re-cost to refresh");
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "11px 2px", borderBottom: "1px solid #f0f0f3" }}>
      <span style={{ fontFamily: MONO, fontSize: 12, color: C.ink, minWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {row.filename ?? row.part_key.slice(0, 12)}
      </span>
      <span style={{ fontFamily: MONO, fontSize: 11, color: row.makeability?.stale ? C.cond : C.ink50 }}>
        {bits.join(" · ")}
      </span>
      <button
        type="button"
        onClick={() => nav("catalog")}
        style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", fontFamily: MONO, fontSize: 10.5, color: C.measured }}
      >
        view in parts →
      </button>
    </div>
  );
}

// ── THE CAPABILITY INVESTMENT, RANKED ───────────────────────────────────────
function CapabilityPanel({ capability, nav }: { capability: CapabilityRanking | null; nav: (s: string) => void }) {
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  if (!capability) return null;
  const { ranking, summary } = capability;

  return (
    <div
      style={{
        marginTop: 14,
        border: `1px solid ${tint(C.cond, 0.35)}`,
        borderRadius: 12,
        background: tint(C.cond, 0.04),
        padding: "16px 18px",
      }}
    >
      <Kicker color={C.cond}>THE CAPABILITY INVESTMENT, RANKED</Kicker>

      {ranking.length === 0 ? (
        <p style={{ margin: "9px 0 0", fontSize: 13.5, lineHeight: 1.6, color: C.ink60 }}>
          {summary.blocked_by_multiple_constraints > 0 ? (
            <>
              No single acquisition closes the gap — {NUM(summary.blocked_by_multiple_constraints)} part
              {summary.blocked_by_multiple_constraints === 1 ? " is" : "s are"} blocked by multiple constraints, so no
              one machine unlocks them. Stated, not folded away.
            </>
          ) : (
            <>No single-acquisition unlock opportunities right now — nothing is blocked on exactly one missing capability.</>
          )}
        </p>
      ) : (
        <>
          <p style={{ margin: "9px 0 0", fontSize: 14.5, lineHeight: 1.6 }}>
            <span style={{ fontWeight: 500 }}>One acquisition unlocks the most:</span>{" "}
            {ranking[0].acquisition.process_label}
            {ranking[0].acquisition.spec?.summary ? ` — ${ranking[0].acquisition.spec.summary}` : ""} frees{" "}
            <span style={{ fontWeight: 500 }}>
              {NUM(ranking[0].parts_unlocked)} currently-blocked part{ranking[0].parts_unlocked === 1 ? "" : "s"}
            </span>
            .
          </p>

          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
            {ranking.map((e, i) => (
              <RankRow
                key={`${e.acquisition.process}:${e.acquisition.gate ?? ""}`}
                entry={e}
                rank={i}
                open={openIdx === i}
                onToggle={() => setOpenIdx((k) => (k === i ? null : i))}
                nav={nav}
              />
            ))}
          </div>

          {summary.blocked_by_multiple_constraints > 0 && (
            <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink45 }}>
              + {NUM(summary.blocked_by_multiple_constraints)} part
              {summary.blocked_by_multiple_constraints === 1 ? "" : "s"} blocked by multiple constraints — no single
              acquisition unlocks them (never folded into a ranking entry)
            </p>
          )}
        </>
      )}

      <p style={{ margin: "9px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40, lineHeight: 1.6 }}>
        ranked by parts unlocked, from stored per-part gaps · no acquisition dollar cost is shown — none is engine-derived
        (never fabricated)
      </p>
    </div>
  );
}

// ── one ranked acquisition, expandable into the parts it unlocks ─────────────
function RankRow({
  entry,
  rank,
  open,
  onToggle,
  nav,
}: {
  entry: CapabilityEntry;
  rank: number;
  open: boolean;
  onToggle: () => void;
  nav: (s: string) => void;
}) {
  const [rows, setRows] = useState<MakeabilityRow[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!open || rows !== null) return;
    fetchCapabilityUnlocked(entry.acquisition.process, entry.acquisition.gate).then(
      (p) => {
        setRows(p.rows);
        setCursor(p.next_cursor);
      },
      (e) => {
        setErr(e instanceof Error ? e.message : "load failed");
        setRows([]);
      }
    );
  }, [open, rows, entry.acquisition.process, entry.acquisition.gate]);

  return (
    <div style={{ borderRadius: 10, border: `1px solid ${open ? tint(C.cond, 0.4) : "transparent"}`, background: open ? C.panel : "transparent" }}>
      <button
        type="button"
        onClick={onToggle}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 12,
          cursor: "pointer",
          fontFamily: "inherit",
          color: "inherit",
          textAlign: "left",
          background: "none",
          border: "none",
          padding: "9px 10px",
        }}
      >
        <span style={{ fontFamily: MONO, fontSize: 11, color: C.ink40, width: 18 }}>{rank === 0 ? "①" : `#${rank + 1}`}</span>
        <span style={{ fontSize: 13, fontWeight: rank === 0 ? 500 : 400 }}>
          {entry.acquisition.kind === "acquire" ? "Acquire " : "Upgrade to "}
          {entry.acquisition.process_label}
          {entry.acquisition.spec?.summary ? (
            <span style={{ color: C.ink50 }}> — {entry.acquisition.spec.summary}</span>
          ) : null}
        </span>
        <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 11.5, color: C.cond, fontWeight: 500 }}>
          {NUM(entry.parts_unlocked)} unlocked
        </span>
        {entry.stale && (
          <span title="some of these verdicts predate a machine change" style={{ fontFamily: MONO, fontSize: 9.5, color: C.cond, border: `1px solid ${tint(C.cond, 0.35)}`, borderRadius: 4, padding: "1px 5px" }}>
            {NUM(entry.stale_parts)} STALE
          </span>
        )}
        <span style={{ fontFamily: MONO, fontSize: 12, color: C.ink35 }}>{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div style={{ padding: "0 10px 10px" }}>
          {err && <p style={{ margin: "4px 0 0", fontFamily: MONO, fontSize: 11, color: C.fail }}>{err}</p>}
          {rows === null && !err && (
            <div style={{ marginTop: 6 }}>
              <Spinner label="loading unlocked parts…" />
            </div>
          )}
          {rows && rows.length > 0 && (
            <div style={{ marginTop: 4, display: "flex", flexDirection: "column" }}>
              {rows.map((r) => (
                <PartRow key={r.part_key} row={r} nav={nav} />
              ))}
            </div>
          )}
          <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 12 }}>
            <GhostButton onClick={() => nav("acquisition")}>Open acquisition consideration →</GhostButton>
            {cursor && (
              <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
                more unlocked parts beyond the {rows?.length} shown — cursor-paged
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
