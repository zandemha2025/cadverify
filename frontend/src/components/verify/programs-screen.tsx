"use client";

/**
 * PROGRAMS — the portfolio roll-up (volume → exposure), real GET
 * /api/v1/catalog/portfolio + PUT /api/v1/part-context/{mesh_hash}. Group your
 * verified parts into programs and declare each part's annual build volume; the
 * engine annualizes an honest EXPOSURE ($/year = verified unit cost × your
 * declared volume) and rolls it up per program.
 *
 * HONESTY (binding): every $/year is the engine's own annualized figure, surfaced
 * ONLY for a verified part with a USER-declared annual_volume. No volume →
 * exposure WITHHELD, never $0 or a guessed demand quantity. A costed part with a
 * DFM-withheld price can never be exposed. Programs are listed from
 * `summary.programs`; there are no invented programs, worlds, or member counts.
 * World alignment is derived from member part contexts when present.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { C, MONO, USD, NUM, procLabel } from "@/lib/verify/tokens";
import {
  fetchPortfolio,
  declarePartProgram,
  hasVerifiedCost,
  programOf,
  type Portfolio,
  type PortfolioRow,
  type PortfolioProgram,
} from "@/lib/verify/programs-api";
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

/** Compact $/year, matching the design's exposure formatting (never fabricated —
 *  the caller only passes a real engine-annualized figure). */
function exposureLabel(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
  return `$${Math.round(v).toLocaleString("en-US")}`;
}

export function ProgramsScreen() {
  const [pf, setPf] = useState<Portfolio | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openProgram, setOpenProgram] = useState<string | null>(null);
  const toast = useToast();

  const refresh = useCallback(async () => {
    try {
      const data = await fetchPortfolio();
      setPf(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load portfolio");
      setPf({ summary: { parts: 0, costed: 0, drafted: 0, excluded_no_cost_count: 0, truncated: false, posture: {} }, rows: [] });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const programs: PortfolioProgram[] = useMemo(() => pf?.summary.programs ?? [], [pf]);
  const rows: PortfolioRow[] = useMemo(() => pf?.rows ?? [], [pf]);

  // Member parts per program (from the real rows — never invented).
  const membersOf = useCallback(
    (name: string) => rows.filter((r) => programOf(r) === name),
    [rows]
  );

  // Costed parts with no program home yet — the honest "unassigned" bucket.
  const unassigned = useMemo(
    () => rows.filter((r) => programOf(r) === null),
    [rows]
  );

  const onAssign = useCallback(
    async (row: PortfolioRow, program: string, annualVolume: number | null) => {
      await declarePartProgram(row.part_key, { program, annual_volume: annualVolume });
      const vol = annualVolume != null ? ` · ${NUM(annualVolume)} units/yr` : "";
      toast(`${row.filename ?? "part"} assigned to ${program}${vol} — exposure recomputed`);
      await refresh();
    },
    [refresh, toast]
  );

  return (
    <main style={{ animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both", flex: 1, overflowY: "auto", padding: "30px 34px", background: C.bg }}>
      <h1 style={{ margin: 0, fontSize: 26, fontWeight: 300, letterSpacing: "-0.015em" }}>Programs</h1>
      <p style={{ margin: "8px 0 0", maxWidth: 660, fontSize: 14, lineHeight: 1.6, color: C.ink55 }}>
        Group your verified parts into programs and declare each part&apos;s annual build volume — the portfolio rolls up
        an honest annual <strong style={{ fontWeight: 500 }}>exposure</strong> (verified unit cost × your volume). No
        volume declared, no exposure — never a guessed demand quantity.
      </p>
      <p style={{ margin: "12px 0 0", display: "inline-flex", alignItems: "center", gap: 8, fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>
        worlds are read from each part&apos;s declared service environment — shared, mixed, or missing states stay visible
      </p>

      {error && (
        <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: C.fail }}>
          couldn&apos;t load the portfolio — {error}
        </p>
      )}

      {pf === null ? (
        <div style={{ marginTop: 26 }}><Spinner label="loading portfolio…" /></div>
      ) : pf.summary.costed === 0 ? (
        <div style={{ marginTop: 24, maxWidth: 660 }}>
          <EmptyState
            title="No verified parts yet — so no exposure to roll up."
            body="Programs group your verified parts and turn a per-unit price into an annual exposure. Verify a part first; then declare which program it belongs to and how many you build a year."
          >
            {pf.summary.excluded_no_cost_count > 0 && (
              <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>
                {NUM(pf.summary.excluded_no_cost_count)} drafted part(s) require cost — excluded until they carry a verified unit cost
              </p>
            )}
          </EmptyState>
        </div>
      ) : (
        <>
          <div style={{ marginTop: 20, display: "flex", alignItems: "center", gap: 8, maxWidth: 900, flexWrap: "wrap" }}>
            <span style={{ border: `1px solid ${C.ink}`, background: C.ink, color: "#fff", borderRadius: 999, padding: "6px 14px", fontSize: 12 }}>
              {NUM(programs.length)} program{programs.length === 1 ? "" : "s"} · {NUM(pf.summary.costed)} verified part{pf.summary.costed === 1 ? "" : "s"}
            </span>
            {pf.summary.truncated && (
              <span style={{ fontFamily: MONO, fontSize: 10, color: C.cond }}>capped scan — older parts not included</span>
            )}
          </div>

          {/* ── Programs (real summary.programs) ── */}
          {programs.length === 0 ? (
            <div style={{ marginTop: 16, maxWidth: 900, border: `1.5px dashed #d3d3d8`, borderRadius: 16, background: C.panel, padding: "20px 24px" }}>
              <p style={{ margin: 0, fontSize: 14.5, fontWeight: 500 }}>No programs declared yet.</p>
              <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink50, lineHeight: 1.6 }}>
                Your {NUM(pf.summary.costed)} verified part{pf.summary.costed === 1 ? " has" : "s have"} no program home. Assign one below — the moment a part with a
                declared annual volume lands in a program, its exposure appears here.
              </p>
            </div>
          ) : (
            <div style={{ marginTop: 16, maxWidth: 900, display: "flex", flexDirection: "column", gap: 12 }}>
              {programs.map((p) => (
                <ProgramCard
                  key={p.program}
                  program={p}
                  members={membersOf(p.program)}
                  open={openProgram === p.program}
                  onToggle={() => setOpenProgram((cur) => (cur === p.program ? null : p.program))}
                />
              ))}
            </div>
          )}

          {/* ── Unassigned — the honest no-home bucket ── */}
          {unassigned.length > 0 && (
            <div style={{ marginTop: 22, maxWidth: 900 }}>
              <Kicker color={C.ink45}>
                UNASSIGNED — {NUM(unassigned.length)} PART{unassigned.length === 1 ? "" : "S"} WITH NO HOME YET
              </Kicker>
              <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 10 }}>
                {unassigned.map((r) => (
                  <UnassignedRow
                    key={r.part_key}
                    row={r}
                    programNames={programs.map((p) => p.program)}
                    onAssign={onAssign}
                  />
                ))}
              </div>
            </div>
          )}

          {pf.context_note && (
            <p style={{ margin: "18px 0 0", maxWidth: 900, fontFamily: MONO, fontSize: 10, lineHeight: 1.7, color: C.ink40 }}>
              {pf.context_note}
            </p>
          )}
        </>
      )}
    </main>
  );
}

/** One program: name + parts + rolled-up exposure, expandable to its members. */
function ProgramCard({
  program,
  members,
  open,
  onToggle,
}: {
  program: PortfolioProgram;
  members: PortfolioRow[];
  open: boolean;
  onToggle: () => void;
}) {
  const exposed = program.annualized_cost_usd != null && Number.isFinite(program.annualized_cost_usd);
  // Any member still validated=false → the exposure inherits an assumption band.
  const anyUnvalidated = members.some((m) => m.validated !== true);
  const withVolume = members.filter((m) => m.context?.annual_volume != null).length;

  return (
    <section style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "20px 22px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <p style={{ margin: 0, fontSize: 17, fontWeight: 500 }}>{program.program}</p>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          <ProvDot p="USER" size={7} />
          <span style={{ fontFamily: MONO, fontSize: 10, color: C.user }}>USER — declared by your team</span>
        </span>
        <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 10.5, color: C.ink40 }}>
          {NUM(program.parts)} part{program.parts === 1 ? "" : "s"}
        </span>
        <button
          type="button"
          onClick={onToggle}
          style={{ background: C.ink, color: "#fff", border: "none", borderRadius: 999, padding: "8px 18px", fontSize: 12, fontWeight: 500, cursor: "pointer", fontFamily: "inherit" }}
        >
          {open ? "Close" : "Open →"}
        </button>
      </div>

      {/* rolled-up exposure line (always visible) */}
      <div style={{ marginTop: 14, display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        {exposed ? (
          <>
            <span style={{ fontSize: 26, fontWeight: 300, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums" }}>
              {exposureLabel(program.annualized_cost_usd)}
            </span>
            <span style={{ fontSize: 12.5, color: C.ink45 }}>/yr exposure</span>
            <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
              Σ over {NUM(withVolume)} part{withVolume === 1 ? "" : "s"} with a declared volume
            </span>
          </>
        ) : (
          <span style={{ fontFamily: MONO, fontSize: 11.5, color: C.ink50, lineHeight: 1.6 }}>
            exposure withheld — no member part has a declared annual volume yet (not guessed, not extrapolated)
          </span>
        )}
      </div>
      {exposed && anyUnvalidated && (
        <div style={{ marginTop: 10, maxWidth: 320 }}>
          <ConfidenceBand validated={false} />
          <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.cond }}>
            inherits each unit cost&apos;s assumption band — hatched until validated
          </p>
        </div>
      )}

      {open && (
        <div style={{ marginTop: 16, borderTop: `1px solid #efeff2`, paddingTop: 12 }}>
          <Kicker color={C.ink45}>MEMBER PARTS — EVERY EXPOSURE SOURCED</Kicker>
          <div style={{ marginTop: 6, display: "flex", flexDirection: "column" }}>
            {members.length === 0 ? (
              <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink40 }}>
                grouped in the roll-up but no member rows in this page&apos;s scan
              </p>
            ) : (
              members.map((m) => <MemberRow key={m.part_key} row={m} />)
            )}
          </div>
        </div>
      )}
    </section>
  );
}

/** One member part inside an open program: filename · unit cost · volume · $/year. */
function MemberRow({ row }: { row: PortfolioRow }) {
  const cost = row.unit_cost;
  const hasCost = hasVerifiedCost(row);
  const vol = row.context?.annual_volume ?? null;
  const annualized = row.annualized_cost_usd ?? null;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr 1fr 1fr", gap: 12, alignItems: "center", padding: "11px 2px", borderBottom: `1px solid #f0f0f3` }}>
      <span style={{ fontFamily: MONO, fontSize: 12, color: C.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {row.filename ?? row.part_key.slice(0, 10)}
      </span>
      <span style={{ fontFamily: MONO, fontSize: 11.5, color: hasCost ? C.ink : C.ink40 }}>
        {hasCost ? `${USD(cost?.usd)}/unit` : "cost withheld"}
        {hasCost && row.make_now_process ? <span style={{ color: C.ink40 }}> · {procLabel(row.make_now_process)}</span> : null}
      </span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontFamily: MONO, fontSize: 11.5, color: vol != null ? C.ink : C.ink40 }}>
        {vol != null ? (
          <>
            <ProvDot p="USER" size={6} />
            {NUM(vol)} /yr
          </>
        ) : (
          "no volume"
        )}
      </span>
      <span style={{ fontFamily: MONO, fontSize: 11.5, color: annualized != null ? C.pass : C.ink40, textAlign: "right" }}>
        {annualized != null ? `${exposureLabel(annualized)}/yr` : "withheld"}
      </span>
    </div>
  );
}

/** An unassigned costed part with an inline assign form (program + volume → PUT). */
function UnassignedRow({
  row,
  programNames,
  onAssign,
}: {
  row: PortfolioRow;
  programNames: string[];
  onAssign: (row: PortfolioRow, program: string, annualVolume: number | null) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [program, setProgram] = useState("");
  const [volume, setVolume] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const hasCost = hasVerifiedCost(row);
  const listId = `prog-list-${row.part_key.slice(0, 10)}`;

  const submit = useCallback(async () => {
    const name = program.trim();
    if (!name) {
      setErr("a program name is required");
      return;
    }
    // Volume optional; when present it must be a positive integer (backend 400s
    // otherwise) — no fabricated demand quantity if left blank.
    let vol: number | null = null;
    if (volume.trim() !== "") {
      const n = Number(volume.trim());
      if (!Number.isInteger(n) || n <= 0) {
        setErr("annual volume must be a whole number greater than 0");
        return;
      }
      vol = n;
    }
    setBusy(true);
    setErr(null);
    try {
      await onAssign(row, name, vol);
      setEditing(false);
      setProgram("");
      setVolume("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "assign failed");
    } finally {
      setBusy(false);
    }
  }, [program, volume, row, onAssign]);

  return (
    <div style={{ border: `1.5px dashed #d3d3d8`, borderRadius: 16, background: "none", padding: "16px 20px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <p style={{ margin: 0, fontSize: 14, fontWeight: 500, fontFamily: MONO }}>{row.filename ?? row.part_key.slice(0, 12)}</p>
          <p style={{ margin: "5px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>
            {hasCost ? (
              <>verified · {USD(row.unit_cost?.usd)}/unit{row.make_now_process ? ` · ${procLabel(row.make_now_process)}` : ""} — no program home yet</>
            ) : (
              <>cost withheld{row.unit_cost?.withheld_reason ? ` · ${row.unit_cost.withheld_reason}` : ""} — can&apos;t be exposed until it carries a verified cost</>
            )}
          </p>
        </div>
        {!editing && (
          <GhostButton onClick={() => setEditing(true)}>Assign to a program</GhostButton>
        )}
      </div>

      {editing && (
        <div style={{ marginTop: 14, borderTop: `1px solid #ececef`, paddingTop: 14, display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
            <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.08em", color: C.ink45 }}>PROGRAM</span>
              <input
                value={program}
                onChange={(e) => setProgram(e.target.value)}
                list={listId}
                placeholder="e.g. Hydraulic actuator"
                style={{ width: 240, background: "#fff", border: `1px solid #dcdce0`, borderRadius: 8, padding: "8px 12px", fontSize: 13, color: C.ink, fontFamily: "inherit", outline: "none" }}
              />
              {programNames.length > 0 && (
                <datalist id={listId}>
                  {programNames.map((n) => (
                    <option key={n} value={n} />
                  ))}
                </datalist>
              )}
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontFamily: MONO, fontSize: 10, letterSpacing: "0.08em", color: C.ink45 }}>
                ANNUAL VOLUME <ProvDot p="USER" size={6} />
              </span>
              <input
                value={volume}
                onChange={(e) => setVolume(e.target.value.replace(/[^0-9]/g, ""))}
                inputMode="numeric"
                placeholder="units/yr (optional)"
                style={{ width: 150, background: "#fff", border: `1px solid #dcdce0`, borderRadius: 8, padding: "8px 12px", fontSize: 13, color: C.ink, fontFamily: MONO, outline: "none", textAlign: "right" }}
              />
            </label>
            <GhostButton primary onClick={() => void submit()} disabled={busy}>
              {busy ? "Assigning…" : "Assign"}
            </GhostButton>
            <GhostButton onClick={() => { setEditing(false); setErr(null); }} disabled={busy}>Cancel</GhostButton>
          </div>

          {/* honest exposure preview — only when a real unit cost AND a volume exist */}
          {hasCost && volume.trim() !== "" && Number(volume) > 0 && (
            <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, color: C.ink50 }}>
              exposure will be {exposureLabel((row.unit_cost?.usd ?? 0) * Number(volume))}/yr = {USD(row.unit_cost?.usd)} (engine, marginal) × {NUM(Number(volume))} units <ProvChip p="USER" />
            </p>
          )}
          {!hasCost && (
            <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, color: C.cond }}>
              no verified unit cost — you can still group this part, but exposure stays withheld
            </p>
          )}
          {err && <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, color: C.fail }}>{err}</p>}
        </div>
      )}
    </div>
  );
}
