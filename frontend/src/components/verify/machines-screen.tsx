"use client";

/**
 * YOUR MACHINES — real CRUD against /api/v1/machine-inventory (list / create /
 * get / patch / delete + CSV import) PLUS the full machine DETAIL the design calls
 * `renderMachine`: the SPEC denominator, a governed RATE HISTORY read from the real
 * rate-library, and PARTS ROUTED HERE = real cost-decisions whose make-now route is
 * this machine's process. Every declared capability is ● USER (an assertion, never a
 * measurement); a rate only re-tags ● SHOP once a governed accounting card is bound.
 * Absent inventory → the honest "declare your floor" empty state.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { C, MONO, NUM, USD, procLabel, PROCESS_LABELS } from "@/lib/verify/tokens";
import {
  listMachines,
  createMachine,
  updateMachine,
  deleteMachine,
  importMachinesCsv,
  machineImportTemplate,
  envelopeSummary,
  type OwnedMachine,
  type MachineInput,
  type MachineImportSummary,
} from "@/lib/verify/machine-api";
import {
  parseMachineNumbers,
  type MachineNumberErrors,
  type MachineNumberField,
} from "@/lib/verify/machine-form";
import {
  fetchMachineCatalog,
  type MachineCatalogTemplate,
} from "@/lib/verify/machine-catalog-api";
import { effectiveRateCard, listRateVersions, type EffectiveRateCard, type RateVersionsPage } from "@/lib/verify/rate-api";
import { fetchCostDecisions, type CostDecisionSummary } from "@/lib/api";
import { Kicker, ProvDot, GhostButton, EmptyState, Spinner } from "./primitives";

const PROCESS_OPTIONS = Object.keys(PROCESS_LABELS);

/** The design's machine glyph (renderMachines / machine-detail header). */
function MachineIcon({ color = C.ink60, size = 17 }: { color?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ display: "inline-flex", flexShrink: 0 }}>
      <rect x="3" y="8" width="18" height="12" rx="2" />
      <path d="M7 8V5a1 1 0 0 1 1-1h8a1 1 0 0 1 1 1v3" />
      <circle cx="9" cy="14" r="1.6" />
      <path d="M14 13h4" />
      <path d="M14 16h4" />
    </svg>
  );
}

/** Honest owned-machine status: everything in YOUR inventory is owned, so the only
 *  real distinction is whether a rate is declared (marginal costing active) or the
 *  marginal cost is withheld until one is. Never fabricates "NOT OWNED → ACQUIRE". */
function machineStatus(m: OwnedMachine): { label: string; color: string } {
  return m.hourly_rate_usd != null
    ? { label: "OWNED → MARGINAL", color: C.pass }
    : { label: "OWNED · NO RATE", color: C.cond };
}

export function MachinesScreen({ nav }: { nav: (s: string) => void }) {
  const [machines, setMachines] = useState<OwnedMachine[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [form, setForm] = useState<{ mode: "add" } | { mode: "edit"; machine: OwnedMachine } | null>(null);
  const [csvResult, setCsvResult] = useState<MachineImportSummary | null>(null);
  const [csvError, setCsvError] = useState<string | null>(null);
  const csvRef = useRef<HTMLInputElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      const page = await listMachines();
      setMachines(page.machines);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load machines");
      setMachines([]);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onDelete = useCallback(
    async (m: OwnedMachine) => {
      try {
        await deleteMachine(m.id);
        toast.success(`Removed ${m.name || procLabel(m.process)}`);
        setDetailId(null);
        await refresh();
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Delete failed");
      }
    },
    [refresh]
  );

  const onCsv = useCallback(
    async (file: File) => {
      try {
        const summary = await importMachinesCsv(file);
        setCsvResult(summary);
        setCsvError(null);
        toast.success(`Imported ${summary.imported} · skipped ${summary.skipped}`);
        if (summary.errors.length) {
          toast.message(`${summary.errors.length} row error(s)`, {
            description: summary.errors.slice(0, 3).map((e) => `line ${e.line}: ${e.reason}`).join(" · "),
          });
        }
        await refresh();
      } catch (e) {
        const message = e instanceof Error ? e.message : "Import failed";
        setCsvError(message);
        setCsvResult(null);
        toast.error(message);
      }
    },
    [refresh]
  );

  const downloadCsvTemplate = useCallback(async () => {
    try {
      const csv = await machineImportTemplate();
      const href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = "machines-template.csv";
      anchor.click();
      URL.revokeObjectURL(href);
      setCsvError(null);
      toast.success("Downloaded the exact machine import template");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Template download failed";
      setCsvError(message);
      toast.error(message);
    }
  }, []);

  const detail = detailId ? (machines ?? []).find((m) => m.id === detailId) ?? null : null;

  // A hidden CSV picker shared by every "import" affordance.
  const csvInput = (
    <input
      ref={csvRef}
      type="file"
      accept=".csv,text/csv"
      style={{ display: "none" }}
      onChange={(e) => {
        const f = e.target.files?.[0];
        if (f) void onCsv(f);
        e.target.value = "";
      }}
    />
  );

  // ── DETAIL VIEW (renderMachine) ─────────────────────────────────────────────
  if (detail) {
    return (
      <main style={{ animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both", flex: 1, overflowY: "auto", padding: "30px 34px", background: C.bg }}>
        <MachineDetail
          m={detail}
          nav={nav}
          onBack={() => setDetailId(null)}
          onEdit={() => setForm({ mode: "edit", machine: detail })}
          onDelete={() => onDelete(detail)}
        />
        {form && (
          <MachineFormModal
            mode={form.mode}
            machine={form.mode === "edit" ? form.machine : undefined}
            onClose={() => setForm(null)}
            onSaved={async () => { setForm(null); await refresh(); }}
          />
        )}
      </main>
    );
  }

  // ── LIST VIEW (renderMachines) ──────────────────────────────────────────────
  return (
    <main style={{ animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both", flex: 1, overflowY: "auto", padding: "30px 34px", background: C.bg }}>
      {csvInput}
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 300, letterSpacing: "-0.015em" }}>Your machines</h1>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <GhostButton primary onClick={() => setForm({ mode: "add" })}>Add machine</GhostButton>
          <GhostButton onClick={() => csvRef.current?.click()}>Import CSV</GhostButton>
          <GhostButton onClick={() => void downloadCsvTemplate()}>Download CSV template</GhostButton>
        </div>
      </div>
      <p style={{ margin: "8px 0 0", maxWidth: 620, fontSize: 14, lineHeight: 1.6, color: C.ink55 }}>
        Every verdict is computed against this inventory — envelope, materials, rate, throughput. Owned means marginal
        cost; missing means an acquisition consideration, stated as one.
      </p>

      {error && (
        <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: C.fail }}>couldn&apos;t load inventory — {error}</p>
      )}
      {csvError && (
        <div role="alert" data-testid="machine-import-error" style={{ marginTop: 14, border: `1px solid ${C.fail}55`, borderRadius: 10, padding: "10px 12px", fontFamily: MONO, fontSize: 11, color: C.fail }}>
          Import failed — {csvError}. Correct the CSV and choose Import CSV again; existing machines were not removed.
        </div>
      )}
      {csvResult && (
        <div role="status" data-testid="machine-import-result" style={{ marginTop: 14, border: `1px solid ${csvResult.errors.length ? C.cond : C.pass}55`, borderRadius: 10, padding: "10px 12px", fontFamily: MONO, fontSize: 11, color: C.ink55 }}>
          <strong style={{ color: C.ink }}>Import complete: {csvResult.imported} imported · {csvResult.skipped} skipped · {csvResult.total} total</strong>
          {csvResult.errors.length > 0 && (
            <ul style={{ margin: "7px 0 0", paddingLeft: 18 }}>
              {csvResult.errors.map((item, i) => <li key={`${item.line}-${i}`}>line {item.line}: {item.reason}</li>)}
            </ul>
          )}
        </div>
      )}

      {machines === null ? (
        <div style={{ marginTop: 26 }}>
          <Spinner label="loading your floor…" />
        </div>
      ) : machines.length === 0 ? (
        <div style={{ marginTop: 26, maxWidth: 640 }}>
          <EmptyState
            title="Declare your floor."
            body="Every verdict is computed against this inventory — envelope, materials, rate, throughput. It's an afternoon of typing or one CSV, and it's the difference between “can it be made” and “can YOU make it.”"
          >
            <div style={{ display: "flex", justifyContent: "center", gap: 10 }}>
              <GhostButton primary onClick={() => setForm({ mode: "add" })}>Add your first machine</GhostButton>
              <GhostButton onClick={() => csvRef.current?.click()}>Import machines.csv</GhostButton>
              <GhostButton onClick={() => void downloadCsvTemplate()}>Download template</GhostButton>
            </div>
          </EmptyState>
        </div>
      ) : (
        <div style={{ marginTop: 26, display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(310px, 1fr))", gap: 16 }}>
          {machines.map((m) => (
            <MachineCard key={m.id} m={m} onOpen={() => setDetailId(m.id)} />
          ))}
        </div>
      )}

      {form && (
        <MachineFormModal
          mode={form.mode}
          machine={form.mode === "edit" ? form.machine : undefined}
          onClose={() => setForm(null)}
          onSaved={async () => { setForm(null); await refresh(); }}
        />
      )}
    </main>
  );
}

function MachineCard({ m, onOpen }: { m: OwnedMachine; onOpen: () => void }) {
  const st = machineStatus(m);
  return (
    <button
      type="button"
      onClick={onOpen}
      style={{
        textAlign: "left",
        fontFamily: "inherit",
        color: "inherit",
        cursor: "pointer",
        border: `1px solid ${C.hair}`,
        borderRadius: 16,
        background: C.panel,
        padding: "20px 22px",
        transition: "transform 200ms",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <MachineIcon />
        <p style={{ margin: 0, fontSize: 16, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.name || procLabel(m.process)}</p>
        <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 10, letterSpacing: "0.08em", color: st.color, whiteSpace: "nowrap" }}>{st.label}</span>
      </div>
      <p style={{ margin: "4px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink45 }}>{procLabel(m.process)}{m.count && m.count > 1 ? ` · ×${m.count}` : ""}</p>
      <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 7, fontFamily: MONO, fontSize: 11.5 }}>
        <Row k="envelope" v={envelopeSummary(m) ?? "—"} />
        <Row k="materials" v={(m.materials && m.materials.length ? m.materials.join(", ") : "—")} />
        <Row k="rate" v={m.hourly_rate_usd != null ? `${USD(m.hourly_rate_usd)}/hr` : "—"} vColor={m.hourly_rate_usd != null ? C.user : C.ink40} tag={m.hourly_rate_usd != null ? "USER" : undefined} />
        <Row k="max workpiece" v={m.max_workpiece_kg != null ? `${m.max_workpiece_kg} kg` : "—"} />
      </div>
    </button>
  );
}

function Row({ k, v, vColor = C.ink, tag }: { k: string; v: string; vColor?: string; tag?: "USER" | "SHOP" }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
      <span style={{ color: C.ink45 }}>{k}</span>
      <span style={{ color: vColor, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "62%", display: "inline-flex", alignItems: "center", gap: 5 }}>
        {v}
        {tag && <ProvDot p={tag} size={6} />}
      </span>
    </div>
  );
}

// ── MACHINE DETAIL (renderMachine) ────────────────────────────────────────────
function MachineDetail({
  m,
  nav,
  onBack,
  onEdit,
  onDelete,
}: {
  m: OwnedMachine;
  nav: (s: string) => void;
  onBack: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const st = machineStatus(m);
  return (
    <>
      <button type="button" onClick={onBack} style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 11, letterSpacing: "0.1em", color: C.ink45 }}>← YOUR MACHINES</button>
      <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 12, maxWidth: 1100, flexWrap: "wrap" }}>
        <MachineIcon color={C.ink60} size={20} />
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 300, letterSpacing: "-0.015em" }}>{m.name || procLabel(m.process)}</h1>
        <span style={{ fontFamily: MONO, fontSize: 10, letterSpacing: "0.08em", color: st.color }}>{st.label}</span>
        <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 11, color: C.ink45 }}>{procLabel(m.process)}{m.count && m.count > 1 ? ` · ×${m.count}` : ""}</span>
      </div>

      <div style={{ marginTop: 20, display: "grid", gridTemplateColumns: "1fr 1.2fr", gap: 16, maxWidth: 1100, alignItems: "start" }}>
        {/* SPEC — THE DENOMINATOR */}
        <section style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "20px 22px" }}>
          <Kicker>SPEC — THE DENOMINATOR · ● USER</Kicker>
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 9, fontFamily: MONO, fontSize: 12 }}>
            <Row k="envelope" v={envelopeSummary(m) ?? "undeclared"} vColor={envelopeSummary(m) ? C.ink : C.ink40} />
            <Row k="materials" v={m.materials && m.materials.length ? m.materials.join(", ") : "undeclared"} vColor={m.materials && m.materials.length ? C.ink : C.ink40} />
            <Row k="rate" v={m.hourly_rate_usd != null ? `${USD(m.hourly_rate_usd)}/hr` : "undeclared"} vColor={m.hourly_rate_usd != null ? C.user : C.ink40} tag={m.hourly_rate_usd != null ? "USER" : undefined} />
            <Row k="count" v={String(m.count ?? 1)} />
            <Row k="max workpiece" v={m.max_workpiece_kg != null ? `${m.max_workpiece_kg} kg` : "undeclared"} vColor={m.max_workpiece_kg != null ? C.ink : C.ink40} />
            <Row k="capital fraction" v={m.capital_frac != null ? String(m.capital_frac) : "undeclared"} vColor={m.capital_frac != null ? C.ink : C.ink40} />
          </div>
          {m.notes && <p style={{ margin: "12px 0 0", fontSize: 12.5, lineHeight: 1.55, color: C.ink55 }}>{m.notes}</p>}
          <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 10, lineHeight: 1.7, color: C.ink40 }}>every envelope check and marginal cost on this floor divides through this card</p>
          <div style={{ marginTop: 16, display: "flex", gap: 8, alignItems: "center" }}>
            <GhostButton onClick={onEdit}>Edit specs</GhostButton>
            <GhostButton onClick={onDelete} style={{ marginLeft: "auto", borderColor: "rgba(194,69,58,0.4)", color: C.fail }}>Delete machine</GhostButton>
          </div>
          <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>id {m.id.slice(0, 12)}…</p>
        </section>

        {/* RATE HISTORY + PARTS ROUTED HERE */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <RateHistory m={m} />
          <RoutedParts m={m} nav={nav} />
        </div>
      </div>
    </>
  );
}

/** Rate history read from the REAL rate-library. A machine carries a single scalar
 *  USER rate; version-pinned governed history is shown through the effective card.
 *  We show exactly what is true: the declared rate + whether a governed card is
 *  currently in effect. */
function RateHistory({ m }: { m: OwnedMachine }) {
  const [eff, setEff] = useState<EffectiveRateCard | null>(null);
  const [versions, setVersions] = useState<RateVersionsPage | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let live = true;
    Promise.allSettled([effectiveRateCard(), listRateVersions()]).then(([e, v]) => {
      if (!live) return;
      if (e.status === "fulfilled") setEff(e.value);
      if (v.status === "fulfilled") setVersions(v.value);
      setLoaded(true);
    });
    return () => { live = false; };
  }, []);

  const declaredDate = m.updated_at || m.created_at;
  const dateFmt = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString() : "—");
  const usingGoverned = eff?.using_governed === true;
  const publishedCount = versions
    ? versions.versions.filter((x) => x.status === "published" || x.is_published).length
    : 0;

  return (
    <section style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "20px 22px" }}>
      <Kicker>RATE HISTORY — GOVERNED, VERSION-PINNED</Kicker>
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column" }}>
        {m.hourly_rate_usd != null ? (
          <>
            <HistRow a={`${dateFmt(declaredDate)} · current`} b={`${USD(m.hourly_rate_usd)}/hr`} tag="USER" note="declared by you" />
            {m.created_at && m.updated_at && m.created_at !== m.updated_at && (
              <HistRow a={`${dateFmt(m.created_at)} · declared`} b="prior value not retained" note="edits overwrite in place until a governed card is bound" muted />
            )}
          </>
        ) : (
          <p style={{ margin: "2px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink40 }}>no rate declared — marginal cost is withheld until you set one</p>
        )}
      </div>

      <div style={{ marginTop: 12, borderTop: `1px solid #f0f0f3`, paddingTop: 12 }}>
        {!loaded ? (
          <Spinner label="reading rate library…" />
        ) : usingGoverned ? (
          <p style={{ margin: 0, display: "inline-flex", alignItems: "center", gap: 7, fontFamily: MONO, fontSize: 11, color: C.shop }}>
            <ProvDot p="SHOP" size={6} /> governed rate card in effect · {publishedCount || versions?.versions.length || 0} published
          </p>
        ) : (
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 11, color: C.ink45 }}>
            {versions && versions.versions.length > 0
              ? `${versions.versions.length} rate card version(s) authored — none in effect; this rate is your ● USER declaration`
              : "no governed rate card in effect — this rate is your ● USER declaration"}
          </p>
        )}
      </div>

      <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40, lineHeight: 1.6 }}>
        old verdicts keep the rate version they were computed with · current effective card:{" "}
        {usingGoverned ? "governed published card" : "default table / user machine rate"}
      </p>
    </section>
  );
}

function HistRow({ a, b, tag, note, muted }: { a: string; b: string; tag?: "USER" | "SHOP"; note?: string; muted?: boolean }) {
  return (
    <div style={{ display: "flex", gap: 16, alignItems: "center", padding: "10px 2px", borderBottom: `1px solid #f0f0f3`, fontFamily: MONO, fontSize: 11.5 }}>
      <span style={{ color: C.ink40, minWidth: 140 }}>{a}</span>
      <span style={{ color: muted ? C.ink45 : C.ink, display: "inline-flex", alignItems: "center", gap: 6 }}>
        {b}
        {tag && <ProvDot p={tag} size={6} />}
      </span>
      {note && <span style={{ marginLeft: "auto", color: C.ink40, fontSize: 10 }}>{note}</span>}
    </div>
  );
}

/** PARTS ROUTED HERE — real cost-decisions whose make-now route is this machine's
 *  process (server-filtered by `process`, defensively re-filtered client-side).
 *  Empty → the design's honest "nothing routed yet" line. */
function RoutedParts({ m, nav }: { m: OwnedMachine; nav: (s: string) => void }) {
  const [rows, setRows] = useState<CostDecisionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setRows(null);
    setError(null);
    fetchCostDecisions({ process: m.process, limit: 25 }).then(
      (page) => {
        if (!live) return;
        setRows(page.cost_decisions.filter((r) => r.make_now_process === m.process));
      },
      (e) => {
        if (!live) return;
        setError(e instanceof Error ? e.message : "could not load routed parts");
        setRows([]);
      }
    );
    return () => { live = false; };
  }, [m.process]);

  return (
    <section style={{ border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "20px 22px" }}>
      <Kicker>PARTS ROUTED HERE</Kicker>
      {error && <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 11, color: C.fail }}>{error}</p>}
      {rows === null ? (
        <div style={{ marginTop: 12 }}><Spinner label="reading records…" /></div>
      ) : rows.length === 0 ? (
        <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink40 }}>
          nothing routed yet — verdicts routed to {procLabel(m.process)} will land here as parts are verified
        </p>
      ) : (
        <div style={{ marginTop: 6, display: "flex", flexDirection: "column" }}>
          {rows.map((r) => (
            <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "11px 2px", borderBottom: `1px solid #f0f0f3` }}>
              <span style={{ fontFamily: MONO, fontSize: 12, color: C.ink, minWidth: 150, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.label || r.filename}</span>
              <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink50, flex: 1 }}>
                {procLabel(r.make_now_process)} · crossover {r.crossover_qty != null ? NUM(r.crossover_qty) : "—"} · {new Date(r.created_at).toLocaleDateString()}
              </span>
              <button type="button" onClick={() => nav("records")} style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 10.5, color: C.measured }}>open →</button>
            </div>
          ))}
        </div>
      )}
      <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>routed = cost-decisions whose make-now route is this machine&apos;s process</p>
    </section>
  );
}

// ── ADD / EDIT MACHINE MODAL (mForm → POST/PATCH) ─────────────────────────────
function ModalShell({ title, subtitle, onClose, children }: { title: string; subtitle?: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div
      style={{ position: "fixed", inset: 0, zIndex: 60, background: "rgba(23,24,26,0.4)", backdropFilter: "blur(3px)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: 560, maxWidth: "100%", maxHeight: "90vh", overflowY: "auto", background: C.panel, border: `1px solid ${C.hair}`, borderRadius: 18, boxShadow: "0 18px 50px -18px rgba(23,24,26,0.35)", padding: "26px 28px", animation: "vscreenIn 220ms cubic-bezier(0.2,0,0,1) both" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Kicker>{title}</Kicker>
          <button type="button" onClick={onClose} style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", fontFamily: MONO, fontSize: 14, color: C.ink40 }}>✕</button>
        </div>
        {subtitle && <p style={{ margin: "6px 0 0", fontSize: 12.5, color: C.ink55 }}>{subtitle}</p>}
        {children}
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  background: C.bg,
  border: `1px solid #dcdce0`,
  borderRadius: 8,
  padding: "10px 12px",
  fontSize: 13,
  color: C.ink,
  fontFamily: "inherit",
  // NOTE: no inline `outline:"none"` — that inline rule beat the shell's
  // `.cv-verify-shell input/select:focus-visible` ring (verify-app KEYFRAMES),
  // leaving these machine-form fields with no visible keyboard focus (WCAG 2.4.7).
};

function Field({ label, children, span, error }: { label: string; children: React.ReactNode; span?: boolean; error?: string }) {
  return (
    <label style={{ display: "block", gridColumn: span ? "span 2" : undefined }}>
      <span style={{ display: "block", fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", color: C.ink45, marginBottom: 5 }}>{label}</span>
      {children}
      {error && <span role="alert" style={{ display: "block", marginTop: 5, fontFamily: MONO, fontSize: 10, lineHeight: 1.4, color: C.fail }}>{error}</span>}
    </label>
  );
}

const capNum = (cap: Record<string, unknown>, k: string): string => {
  const v = cap[k];
  return typeof v === "number" && Number.isFinite(v) ? String(v) : "";
};

function MachineFormModal({
  mode,
  machine,
  onClose,
  onSaved,
}: {
  mode: "add" | "edit";
  machine?: OwnedMachine;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const baseCap = (machine?.capabilities as Record<string, unknown>) || {};
  const [name, setName] = useState(machine?.name ?? "");
  const [process, setProcess] = useState(machine?.process ?? "cnc_3axis");
  const [count, setCount] = useState(machine?.count != null ? String(machine.count) : "1");
  const [rate, setRate] = useState(machine?.hourly_rate_usd != null ? String(machine.hourly_rate_usd) : "");
  const [maxKg, setMaxKg] = useState(machine?.max_workpiece_kg != null ? String(machine.max_workpiece_kg) : "");
  const [materials, setMaterials] = useState(machine?.materials?.join(", ") ?? "");
  const [notes, setNotes] = useState(machine?.notes ?? "");
  const [x, setX] = useState(capNum(baseCap, "x"));
  const [y, setY] = useState(capNum(baseCap, "y"));
  const [z, setZ] = useState(capNum(baseCap, "z"));
  const [swing, setSwing] = useState(capNum(baseCap, "swing_dia"));
  const [between, setBetween] = useState(capNum(baseCap, "between_centers"));
  const [busy, setBusy] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<MachineNumberErrors>({});
  const [saveError, setSaveError] = useState<string | null>(null);

  // Catalog prefill (add-mode only): the REAL GET /catalog editable templates.
  const [catalog, setCatalog] = useState<MachineCatalogTemplate[] | null>(null);
  useEffect(() => {
    if (mode !== "add") return;
    let live = true;
    fetchMachineCatalog().then(
      (c) => { if (live) setCatalog(c); },
      () => { if (live) setCatalog([]); }
    );
    return () => { live = false; };
  }, [mode]);

  const isTurning = process === "cnc_turning";
  const clearFieldError = (field: MachineNumberField) => {
    setFieldErrors((current) => {
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
    setSaveError(null);
  };

  const applyTemplate = (idx: number) => {
    const t = catalog?.[idx];
    if (!t) return;
    if (t.name) setName(t.name);
    if (t.process) setProcess(t.process);
    const cap = (t.capabilities as Record<string, unknown>) || {};
    setX(capNum(cap, "x"));
    setY(capNum(cap, "y"));
    setZ(capNum(cap, "z"));
    setSwing(capNum(cap, "swing_dia"));
    setBetween(capNum(cap, "between_centers"));
    setMaterials(t.materials?.join(", ") ?? "");
    setMaxKg(t.max_workpiece_kg != null ? String(t.max_workpiece_kg) : "");
    // A catalog template carries NO rate — the org declares its own. Notes are the
    // template's "edit before saving" reminder.
    setNotes(t.notes ?? "");
  };

  const submit = async () => {
    const parsed = parseMachineNumbers({ count, rate, maxKg, x, y, z, swing, between, isTurning });
    if (!parsed.ok) {
      setFieldErrors(parsed.errors);
      setSaveError("Correct the highlighted declarations. Nothing was saved.");
      return;
    }
    setFieldErrors({});
    setSaveError(null);
    setBusy(true);
    // Preserve non-envelope capability keys on edit; overwrite the ones we manage.
    const cap: Record<string, unknown> = { ...baseCap };
    delete cap.x; delete cap.y; delete cap.z; delete cap.swing_dia; delete cap.between_centers;
    Object.assign(cap, parsed.value.capabilities);
    const body: MachineInput = {
      name: name.trim() || null,
      process,
      count: parsed.value.count,
      hourly_rate_usd: parsed.value.rate,
      max_workpiece_kg: parsed.value.maxKg,
      materials: materials.trim() ? materials.split(",").map((s) => s.trim()).filter(Boolean) : null,
      capabilities: Object.keys(cap).length ? cap : null,
      notes: notes.trim() || null,
    };
    try {
      if (mode === "edit" && machine) {
        await updateMachine(machine.id, body);
        toast.success(`Updated ${body.name || procLabel(process)}`);
      } else {
        await createMachine(body);
        toast.success(`Declared ${body.name || procLabel(process)} — ● USER`);
      }
      await onSaved();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Save failed";
      setSaveError(`${message}. Your entries are still here; correct them and retry.`);
      toast.error(message);
      setBusy(false);
    }
  };

  return (
    <ModalShell
      title={mode === "edit" ? "EDIT MACHINE — THE DENOMINATOR OF EVERY VERDICT" : "DECLARE A MACHINE — THE DENOMINATOR OF EVERY VERDICT"}
      onClose={onClose}
    >
      <p style={{ margin: "8px 0 14px", fontFamily: MONO, fontSize: 10.5, color: C.user, display: "inline-flex", alignItems: "center", gap: 6 }}>
        <ProvDot p="USER" size={6} /> ● USER — a declared capability, never a measurement · bind an accounting export later to re-tag rates ● SHOP
      </p>

      {mode === "add" && catalog && catalog.length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <Field label="PREFILL FROM A CATALOG MACHINE (OPTIONAL — YOU EDIT BEFORE SAVING)">
            <select
              style={inputStyle}
              defaultValue=""
              onChange={(e) => { if (e.target.value !== "") applyTemplate(Number(e.target.value)); }}
            >
              <option value="">— start blank —</option>
              {catalog.map((t, i) => (
                <option key={`${t.name}-${i}`} value={i}>{t.name || procLabel(t.process)} · {procLabel(t.process)}</option>
              ))}
            </select>
          </Field>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label="NAME"><input style={inputStyle} value={name} onChange={(e) => setName(e.target.value)} placeholder="Haas VF-2" /></Field>
        <Field label="PROCESS">
          <select style={inputStyle} value={process} onChange={(e) => setProcess(e.target.value)}>
            {PROCESS_OPTIONS.map((p) => (
              <option key={p} value={p}>{procLabel(p)}</option>
            ))}
          </select>
        </Field>
        <Field label="COUNT" error={fieldErrors.count}><input style={inputStyle} value={count} aria-invalid={!!fieldErrors.count} onChange={(e) => { setCount(e.target.value); clearFieldError("count"); }} inputMode="numeric" /></Field>
        <Field label="HOURLY RATE (USD)" error={fieldErrors.rate}><input style={inputStyle} value={rate} aria-invalid={!!fieldErrors.rate} onChange={(e) => { setRate(e.target.value); clearFieldError("rate"); }} inputMode="decimal" placeholder="95" /></Field>
        {isTurning ? (
          <>
            <Field label="SWING Ø (mm)" error={fieldErrors.swing}><input style={inputStyle} value={swing} aria-invalid={!!fieldErrors.swing} onChange={(e) => { setSwing(e.target.value); clearFieldError("swing"); }} inputMode="decimal" /></Field>
            <Field label="BETWEEN CENTERS (mm)" error={fieldErrors.between}><input style={inputStyle} value={between} aria-invalid={!!fieldErrors.between} onChange={(e) => { setBetween(e.target.value); clearFieldError("between"); }} inputMode="decimal" /></Field>
          </>
        ) : (
          <div style={{ gridColumn: "span 2", display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
            <Field label="ENVELOPE X (mm)" error={fieldErrors.x}><input style={inputStyle} value={x} aria-invalid={!!fieldErrors.x} onChange={(e) => { setX(e.target.value); clearFieldError("x"); }} inputMode="decimal" /></Field>
            <Field label="Y (mm)" error={fieldErrors.y}><input style={inputStyle} value={y} aria-invalid={!!fieldErrors.y} onChange={(e) => { setY(e.target.value); clearFieldError("y"); }} inputMode="decimal" /></Field>
            <Field label="Z (mm)" error={fieldErrors.z}><input style={inputStyle} value={z} aria-invalid={!!fieldErrors.z} onChange={(e) => { setZ(e.target.value); clearFieldError("z"); }} inputMode="decimal" /></Field>
          </div>
        )}
        <Field label="MAX WORKPIECE (kg)" error={fieldErrors.maxKg}><input style={inputStyle} value={maxKg} aria-invalid={!!fieldErrors.maxKg} onChange={(e) => { setMaxKg(e.target.value); clearFieldError("maxKg"); }} inputMode="decimal" /></Field>
        <Field label="MATERIALS (comma-separated)">
          <input style={inputStyle} value={materials} onChange={(e) => setMaterials(e.target.value)} placeholder="6061, 316L, PP" />
          <span style={{ display: "block", marginTop: 5, fontFamily: MONO, fontSize: 10, lineHeight: 1.5, color: C.ink40 }}>
            a class (aluminum, steel, stainless, titanium, polymer), a registry name (e.g. 6061-T6 Aluminum, SS316L), or a shorthand (6061, 7075, 304, 316L, PP, 4130, 4140)
          </span>
        </Field>
        <Field label="NOTES (OPTIONAL)" span><input style={inputStyle} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="throughput note, fixturing, secondary ops…" /></Field>
      </div>

      {saveError && <p role="alert" data-testid="machine-save-error" style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, lineHeight: 1.5, color: C.fail }}>{saveError}</p>}

      <div style={{ marginTop: 18, display: "flex", alignItems: "center", gap: 10 }}>
        <GhostButton primary disabled={busy} onClick={submit}>{busy ? "Saving…" : mode === "edit" ? "Save changes" : "Declare machine"}</GhostButton>
        <GhostButton onClick={onClose}>Cancel</GhostButton>
      </div>
    </ModalShell>
  );
}
