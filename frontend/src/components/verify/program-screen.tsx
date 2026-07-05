"use client";

/**
 * PROGRAMS + PROGRAM DETAIL — the "declare a world once, exposure = your volume ×
 * the engine's unit cost" surface, recreated in the light-instrument register and
 * wired to the REAL org roll-up.
 *
 * Data:
 *  - GET /api/v1/catalog/portfolio (via program-api) → declared programs, the
 *    parts assigned to each, and the honest annualized `$/year` (engine unit cost
 *    × USER-declared volume, withheld when no volume is declared).
 *  - PUT /api/v1/part-context/{mesh} (merge-then-write) → assign a part to a
 *    program / declare its annual volume, without clobbering its declared world.
 *
 * Honesty (binding): every figure is engine/DB output or is WITHHELD. Exposure is
 * NEVER computed without a USER-declared volume ("not guessed, not extrapolated").
 * Unit-cost bands are HATCHED until the engine says validated (they are not, today).
 * The single shared program-world that "every part inherits" is a design concept
 * with no backend home yet → shown as IN DEVELOPMENT, never faked with chips.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { C, MONO, USD, NUM, procLabel } from "@/lib/verify/tokens";
import {
  getPortfolio,
  assignContext,
  declaredPrograms,
  rowsInProgram,
  assignableRows,
  type Portfolio,
  type PortfolioRow,
  type ProgramRollup,
} from "@/lib/verify/program-api";
import {
  Kicker,
  ProvChip,
  ProvDot,
  InDev,
  GhostButton,
  EmptyState,
  Spinner,
} from "./primitives";
import { useToast } from "./toast";

/** Exposure formatting matching the design: $X.XXM at scale, else $X,XXX. */
function fmtExposure(n: number): string {
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  return `$${Math.round(n).toLocaleString("en-US")}`;
}

const HATCH =
  "repeating-linear-gradient(135deg, rgba(23,24,26,0.35) 0 2px, transparent 2px 7px)";

interface ProgramScreenProps {
  /** shell nav (setScreen) — "programs" (index) / "program" (detail) / "catalog". */
  nav: (s: string) => void;
  /** the shell screen key — "programs" shows the index, "program" the detail. */
  screen: string;
}

export function ProgramScreen({ nav, screen }: ProgramScreenProps) {
  const toast = useToast();
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const p = await getPortfolio();
      setPortfolio(p);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the portfolio");
      setPortfolio({ summary: { parts: 0, costed: 0, drafted: 0, excluded_no_cost_count: 0, truncated: false, posture: {} }, rows: [] });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const open = useCallback(
    (name: string) => {
      setSelected(name);
      nav("program");
    },
    [nav]
  );

  const back = useCallback(() => {
    nav("programs");
  }, [nav]);

  const detail = screen === "program" && !!selected;

  if (detail && selected && portfolio) {
    return (
      <ProgramDetail
        portfolio={portfolio}
        program={selected}
        onBack={back}
        nav={nav}
        refresh={refresh}
        toast={toast}
      />
    );
  }

  return (
    <ProgramIndex
      portfolio={portfolio}
      error={error}
      onOpen={open}
    />
  );
}

// ── INDEX (Programs list) ──────────────────────────────────────────────────

function ProgramIndex({
  portfolio,
  error,
  onOpen,
}: {
  portfolio: Portfolio | null;
  error: string | null;
  onOpen: (name: string) => void;
}) {
  const [newName, setNewName] = useState("");
  const programs = useMemo(
    () => (portfolio ? declaredPrograms(portfolio) : []),
    [portfolio]
  );

  const create = () => {
    const name = newName.trim();
    if (name) onOpen(name);
  };

  return (
    <main style={mainStyle} data-screen-label="Programs">
      <h1 style={h1Style}>Programs</h1>
      <p style={{ margin: "8px 0 0", maxWidth: 640, fontSize: 14, lineHeight: 1.6, color: C.ink55 }}>
        Declare a world once, at the program — every part underneath inherits it, and every inheritance is
        visible. Exposure is the engine&apos;s verified unit cost × your declared annual volume, computed only
        when a verified part is assigned.
      </p>

      {error && (
        <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: C.fail }}>
          couldn&apos;t load the portfolio — {error}
        </p>
      )}

      {/* New program: a program exists once a verified part is assigned to it. */}
      <div style={{ marginTop: 22, maxWidth: 640, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") create(); }}
          placeholder="Name a program — e.g. Hydraulic actuator"
          style={{ flex: "1 1 260px", minWidth: 220, background: C.panel, border: `1px solid #dcdce0`, borderRadius: 10, padding: "10px 14px", fontSize: 13.5, color: C.ink, fontFamily: "inherit", outline: "none" }}
        />
        <GhostButton primary disabled={!newName.trim()} onClick={create}>Open →</GhostButton>
      </div>
      <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
        a program becomes real when its first verified part is assigned — nothing is stored for an empty name
      </p>

      {portfolio === null ? (
        <div style={{ marginTop: 26 }}><Spinner label="loading the portfolio…" /></div>
      ) : programs.length === 0 ? (
        <div style={{ marginTop: 24, maxWidth: 640 }}>
          <EmptyState
            title="No programs declared yet."
            body="A program groups verified parts under one world and rolls their exposure up to a single $/year. Name one above, then assign a verified part to it — its exposure computes the moment it has a home and a declared volume."
          />
        </div>
      ) : (
        <div style={{ marginTop: 24, display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 16, maxWidth: 1100 }}>
          {programs.map((g) => (
            <ProgramCard key={g.program} g={g} onOpen={() => onOpen(g.program)} />
          ))}
        </div>
      )}
    </main>
  );
}

function ProgramCard({ g, onOpen }: { g: ProgramRollup; onOpen: () => void }) {
  return (
    <div style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "18px 20px", display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <p style={{ margin: 0, fontSize: 17, fontWeight: 500 }}>{g.program}</p>
        <span style={{ fontFamily: MONO, fontSize: 10, color: C.user }}>● USER</span>
      </div>
      <p style={{ margin: 0, fontFamily: MONO, fontSize: 11, color: C.ink50 }}>
        {NUM(g.parts)} verified {g.parts === 1 ? "part" : "parts"} assigned
      </p>
      <div>
        {g.annualized_cost_usd != null ? (
          <p style={{ margin: 0, fontSize: 22, fontWeight: 300, letterSpacing: "-0.01em", fontVariantNumeric: "tabular-nums" }}>
            {fmtExposure(g.annualized_cost_usd)} <span style={{ fontSize: 12, color: C.ink45 }}>/yr exposure</span>
          </p>
        ) : (
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 11.5, color: C.cond }}>
            exposure withheld — no declared volume yet
          </p>
        )}
      </div>
      <div style={{ marginTop: "auto", paddingTop: 4 }}>
        <GhostButton primary onClick={onOpen}>Open →</GhostButton>
      </div>
    </div>
  );
}

// ── DETAIL (Program detail) ────────────────────────────────────────────────

function ProgramDetail({
  portfolio,
  program,
  onBack,
  nav,
  refresh,
  toast,
}: {
  portfolio: Portfolio;
  program: string;
  onBack: () => void;
  nav: (s: string) => void;
  refresh: () => Promise<void>;
  toast: (m: string) => void;
}) {
  const assigned = useMemo(() => rowsInProgram(portfolio, program), [portfolio, program]);
  const candidates = useMemo(() => assignableRows(portfolio, program), [portfolio, program]);

  // Exposure = Σ of each assigned part's honest annualized $/year (engine unit
  // cost × USER-declared volume). Withheld entirely until at least one assigned
  // part has a declared volume — never guessed.
  const withVolume = assigned.filter((r) => r.annualized_cost_usd != null);
  const exposureSum = withVolume.length
    ? withVolume.reduce((s, r) => s + (r.annualized_cost_usd ?? 0), 0)
    : null;
  // A cost band is HATCHED (assumption) until the engine's confidence says
  // validated — which it is not, today. Only when EVERY exposure-bearing part is
  // validated could this be solid.
  const allValidated = withVolume.length > 0 && withVolume.every((r) => r.unit_cost?.validated === true);

  const [busy, setBusy] = useState(false);

  const doAssign = useCallback(
    async (row: PortfolioRow, volume: number | null) => {
      setBusy(true);
      try {
        await assignContext(row.part_key, { program, annual_volume: volume });
        await refresh();
        toast(
          volume != null
            ? `${row.filename} assigned to ${program} — inherits its world · exposure computed`
            : `${row.filename} assigned to ${program} — exposure computes once a volume is declared`
        );
      } catch (e) {
        toast(`Couldn't assign ${row.filename} — ${e instanceof Error ? e.message : "write failed"}`);
      } finally {
        setBusy(false);
      }
    },
    [program, refresh, toast]
  );

  const setVolume = useCallback(
    async (row: PortfolioRow, volume: number | null) => {
      setBusy(true);
      try {
        await assignContext(row.part_key, { annual_volume: volume });
        await refresh();
        toast(
          volume != null
            ? `${row.filename}: ${NUM(volume)} units/yr declared · exposure updated`
            : `${row.filename}: volume cleared · exposure withheld`
        );
      } catch (e) {
        toast(`Couldn't update ${row.filename} — ${e instanceof Error ? e.message : "write failed"}`);
      } finally {
        setBusy(false);
      }
    },
    [refresh, toast]
  );

  const unassign = useCallback(
    async (row: PortfolioRow) => {
      setBusy(true);
      try {
        await assignContext(row.part_key, { program: null });
        await refresh();
        toast(`${row.filename} removed from ${program}`);
      } catch (e) {
        toast(`Couldn't remove ${row.filename} — ${e instanceof Error ? e.message : "write failed"}`);
      } finally {
        setBusy(false);
      }
    },
    [program, refresh, toast]
  );

  return (
    <main style={mainStyle} data-screen-label="Program detail">
      <button type="button" onClick={onBack} style={backLinkStyle}>← PROGRAMS</button>

      <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", maxWidth: 1100 }}>
        <h1 style={{ ...h1Style, fontSize: 26 }}>{program}</h1>
        <span style={{ fontFamily: MONO, fontSize: 10, color: C.user }}>● USER — declared by your team</span>
        <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 11, color: C.ink50 }}>
          {NUM(assigned.length)} assigned · {NUM(withVolume.length)} with a declared volume
        </span>
      </div>

      {/* Inherit-world — honest. Per-part world today; a single program world that
          every part inherits is in development, never faked with condition chips. */}
      <div style={{ marginTop: 14, maxWidth: 1100, border: `1px solid ${C.hair}`, borderRadius: 12, background: C.panel, padding: "12px 16px", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <InDev label="INHERIT-WORLD IN DEVELOPMENT" />
        <span style={{ fontFamily: MONO, fontSize: 10.5, lineHeight: 1.6, color: C.ink50, flex: "1 1 380px" }}>
          A single world declared once here and inherited by every part is in development. Today each part
          declares its own world at the environment door on Verify; that world (● USER) travels with the part
          and is never overwritten when it is assigned to a program.
        </span>
      </div>

      <div style={{ marginTop: 20, display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 16, maxWidth: 1100, alignItems: "start" }}>
        {/* Assigned parts */}
        <section style={cardStyle}>
          <Kicker>ASSIGNED PARTS — {NUM(assigned.length)}</Kicker>
          {assigned.length === 0 ? (
            <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 11, lineHeight: 1.7, color: C.ink45 }}>
              nothing assigned yet — assign a verified part below · it inherits this program&apos;s world and its
              exposure computes the moment it has a declared volume
            </p>
          ) : (
            <div style={{ marginTop: 6, display: "flex", flexDirection: "column" }}>
              {assigned.map((r) => (
                <AssignedRow
                  key={r.part_key}
                  row={r}
                  busy={busy}
                  onSetVolume={(v) => setVolume(r, v)}
                  onUnassign={() => unassign(r)}
                />
              ))}
            </div>
          )}
          <button type="button" onClick={() => nav("catalog")} style={{ marginTop: 12, background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 10.5, color: C.measured }}>
            view all in Parts →
          </button>
        </section>

        {/* Program exposure */}
        <section style={cardStyle}>
          <Kicker>PROGRAM EXPOSURE</Kicker>
          {exposureSum != null ? (
            <>
              <p style={{ margin: "12px 0 0", fontSize: 30, fontWeight: 300, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums" }}>
                {fmtExposure(exposureSum)} <span style={{ fontSize: 13, color: C.ink45 }}>/yr</span>
              </p>
              <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 11, lineHeight: 1.7, color: C.ink50 }}>
                = Σ (engine unit cost × your declared volume) over {NUM(withVolume.length)}{" "}
                {withVolume.length === 1 ? "part" : "parts"} · <span style={{ color: C.user }}>● USER</span> volume
              </p>
              <div style={{ marginTop: 12, position: "relative", height: 5, borderRadius: 3, background: "#ececef", overflow: "hidden" }}>
                <span aria-hidden style={{ position: "absolute", inset: 0, ...(allValidated ? { background: "rgba(31,138,91,0.5)" } : { backgroundImage: HATCH }) }} />
              </div>
              <p style={{ margin: "7px 0 0", fontFamily: MONO, fontSize: 9.5, color: allValidated ? C.pass : C.cond }}>
                {allValidated
                  ? "unit costs validated against measured actuals"
                  : "inherits the unit cost's band — hatched until validated by measured actuals"}
              </p>
            </>
          ) : (
            <div style={{ marginTop: 12, border: `1.5px dashed #d3d3d8`, borderRadius: 12, padding: 20, textAlign: "center" }}>
              <p style={{ margin: 0, fontSize: 13.5, fontWeight: 500 }}>
                {assigned.length === 0 ? "No verified parts assigned." : "No declared volume yet."}
              </p>
              <p style={{ margin: "7px 0 0", fontSize: 12, lineHeight: 1.6, color: C.ink50 }}>
                Exposure is not computed — not guessed, not extrapolated.{" "}
                {assigned.length === 0
                  ? "Assign a verified part below."
                  : "Declare a part's annual volume to compute it."}
              </p>
            </div>
          )}
        </section>
      </div>

      {/* Assign a verified part */}
      <section style={{ ...cardStyle, marginTop: 16, maxWidth: 1100 }}>
        <Kicker>ASSIGN A VERIFIED PART</Kicker>
        {candidates.length === 0 ? (
          <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 11, lineHeight: 1.7, color: C.ink45 }}>
            no other costed parts to assign — verify a part (it must have a should-cost decision) and it will
            appear here
          </p>
        ) : (
          <div style={{ marginTop: 8, display: "flex", flexDirection: "column" }}>
            {candidates.map((r) => (
              <CandidateRow key={r.part_key} row={r} busy={busy} onAssign={(v) => doAssign(r, v)} />
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

// ── rows ───────────────────────────────────────────────────────────────────

/** A part already assigned to the program: its unit cost, an editable annual
 *  volume (● USER), and its honest $/year exposure (withheld until a volume). */
function AssignedRow({
  row,
  busy,
  onSetVolume,
  onUnassign,
}: {
  row: PortfolioRow;
  busy: boolean;
  onSetVolume: (v: number | null) => void;
  onUnassign: () => void;
}) {
  const declared = row.context?.annual_volume ?? null;
  const [draft, setDraft] = useState<string>(declared != null ? String(declared) : "");

  // Keep the input in sync when the underlying declared volume changes (refresh).
  useEffect(() => {
    setDraft(declared != null ? String(declared) : "");
  }, [declared]);

  const parsed = draft.trim() === "" ? null : parseInt(draft.replace(/[^0-9]/g, ""), 10);
  const normalized = parsed != null && Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  const changed = normalized !== declared;

  const unit = row.unit_cost;
  const priceLabel = unit?.withheld
    ? "cost withheld"
    : unit?.usd != null
      ? USD(unit.usd)
      : "—";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 2px", borderBottom: `1px solid #f0f0f3`, flexWrap: "wrap" }}>
      <span style={{ fontFamily: MONO, fontSize: 12, color: C.ink, minWidth: 170, flex: "1 1 170px" }}>{row.filename}</span>
      <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink45, minWidth: 96 }}>{procLabel(row.make_now_process)}</span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontFamily: MONO, fontSize: 11, color: unit?.withheld ? C.cond : C.ink }}>
        {priceLabel}
        {!unit?.withheld && unit?.usd != null && (
          <ProvChip p={unit.validated ? "MEASURED" : "MODEL"} />
        )}
      </span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <input
          value={draft}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value.replace(/[^0-9]/g, ""))}
          onKeyDown={(e) => { if (e.key === "Enter" && changed) onSetVolume(normalized); }}
          onBlur={() => { if (changed) onSetVolume(normalized); }}
          placeholder="volume"
          title="annual volume — USER-declared; blank withholds exposure"
          style={{ width: 96, background: C.panel, border: `1px solid #dcdce0`, borderRadius: 8, padding: "6px 10px", fontSize: 12, color: C.ink, fontFamily: MONO, outline: "none", textAlign: "right" }}
        />
        <ProvDot p="USER" size={7} />
      </span>
      <span style={{ minWidth: 108, textAlign: "right", fontFamily: MONO, fontSize: 12, fontVariantNumeric: "tabular-nums", color: row.annualized_cost_usd != null ? C.ink : C.cond }}>
        {row.annualized_cost_usd != null ? `${fmtExposure(row.annualized_cost_usd)}/yr` : "withheld"}
      </span>
      <button type="button" onClick={onUnassign} disabled={busy} title="remove from this program" style={{ background: "none", border: "none", padding: 0, cursor: busy ? "default" : "pointer", fontFamily: MONO, fontSize: 10.5, color: C.ink40 }}>
        remove
      </button>
    </div>
  );
}

/** A costed part not yet in this program: assign it, optionally with a volume. */
function CandidateRow({
  row,
  busy,
  onAssign,
}: {
  row: PortfolioRow;
  busy: boolean;
  onAssign: (v: number | null) => void;
}) {
  const [draft, setDraft] = useState("");
  const parsed = draft.trim() === "" ? null : parseInt(draft.replace(/[^0-9]/g, ""), 10);
  const volume = parsed != null && Number.isFinite(parsed) && parsed > 0 ? parsed : null;

  const unit = row.unit_cost;
  const inOther = row.context?.program;
  const priceLabel = unit?.withheld ? "cost withheld" : unit?.usd != null ? USD(unit.usd) : "—";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 2px", borderBottom: `1px solid #f0f0f3`, flexWrap: "wrap" }}>
      <span style={{ fontFamily: MONO, fontSize: 12, color: C.ink, minWidth: 170, flex: "1 1 170px" }}>{row.filename}</span>
      <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink45, minWidth: 96 }}>{procLabel(row.make_now_process)}</span>
      <span style={{ fontFamily: MONO, fontSize: 11, color: unit?.withheld ? C.cond : C.ink }}>{priceLabel}</span>
      {inOther ? (
        <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink40 }}>in {inOther}</span>
      ) : null}
      <input
        value={draft}
        disabled={busy}
        onChange={(e) => setDraft(e.target.value.replace(/[^0-9]/g, ""))}
        placeholder="volume (opt)"
        title="optional annual volume — declare now or later"
        style={{ width: 104, background: C.panel, border: `1px solid #dcdce0`, borderRadius: 8, padding: "6px 10px", fontSize: 12, color: C.ink, fontFamily: MONO, outline: "none", textAlign: "right" }}
      />
      <GhostButton disabled={busy} onClick={() => onAssign(volume)}>Assign →</GhostButton>
    </div>
  );
}

// ── shared style atoms (light instrument) ──────────────────────────────────

const mainStyle: React.CSSProperties = {
  animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both",
  flex: 1,
  overflowY: "auto",
  padding: "30px 34px",
  background: C.bg,
};

const h1Style: React.CSSProperties = {
  margin: 0,
  fontSize: 26,
  fontWeight: 300,
  letterSpacing: "-0.015em",
};

const cardStyle: React.CSSProperties = {
  border: `1px solid ${C.hair}`,
  borderRadius: 16,
  background: C.panel,
  padding: "20px 22px",
};

const backLinkStyle: React.CSSProperties = {
  background: "none",
  border: "none",
  padding: 0,
  cursor: "pointer",
  fontFamily: MONO,
  fontSize: 11,
  letterSpacing: "0.1em",
  color: C.ink45,
};
