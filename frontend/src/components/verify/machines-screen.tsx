"use client";

/**
 * YOUR MACHINES — real CRUD against /api/v1/machine-inventory (list / create /
 * get / delete + CSV import). Every declared machine is ● USER (a capability
 * assertion, never a measurement). Absent inventory → the honest "declare your
 * floor" empty state, byte-identical to the feature unused.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { C, MONO, USD, procLabel, PROCESS_LABELS } from "@/lib/verify/tokens";
import {
  listMachines,
  createMachine,
  deleteMachine,
  importMachinesCsv,
  envelopeSummary,
  type OwnedMachine,
  type MachineInput,
} from "@/lib/verify/machine-api";
import { Kicker, ProvDot, GhostButton, EmptyState, Spinner } from "./primitives";

const PROCESS_OPTIONS = Object.keys(PROCESS_LABELS);

export function MachinesScreen() {
  const [machines, setMachines] = useState<OwnedMachine[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [selected, setSelected] = useState<OwnedMachine | null>(null);
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
        setSelected(null);
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
        toast.success(`Imported ${summary.imported} · skipped ${summary.skipped}`);
        if (summary.errors.length) {
          toast.message(`${summary.errors.length} row error(s)`, {
            description: summary.errors.slice(0, 3).map((e) => `line ${e.line}: ${e.reason}`).join(" · "),
          });
        }
        await refresh();
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Import failed");
      }
    },
    [refresh]
  );

  return (
    <main style={{ animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both", flex: 1, overflowY: "auto", padding: "30px 34px", background: C.bg }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 300, letterSpacing: "-0.015em" }}>Your machines</h1>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <GhostButton primary onClick={() => setShowAdd(true)}>Add machine</GhostButton>
          <GhostButton onClick={() => csvRef.current?.click()}>Import CSV</GhostButton>
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
        </div>
      </div>
      <p style={{ margin: "8px 0 0", maxWidth: 620, fontSize: 14, lineHeight: 1.6, color: C.ink55 }}>
        Every verdict is computed against this inventory — envelope, materials, rate, throughput. Owned means marginal
        cost; missing means an acquisition consideration, stated as one.
      </p>

      {error && (
        <p style={{ margin: "14px 0 0", fontFamily: MONO, fontSize: 11, color: C.fail }}>couldn&apos;t load inventory — {error}</p>
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
              <GhostButton primary onClick={() => setShowAdd(true)}>Add your first machine</GhostButton>
              <GhostButton onClick={() => csvRef.current?.click()}>Import machines.csv</GhostButton>
            </div>
          </EmptyState>
        </div>
      ) : (
        <div style={{ marginTop: 26, display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(310px, 1fr))", gap: 16 }}>
          {machines.map((m) => (
            <MachineCard key={m.id} m={m} onOpen={() => setSelected(m)} />
          ))}
        </div>
      )}

      {showAdd && <AddMachineModal onClose={() => setShowAdd(false)} onCreated={async () => { setShowAdd(false); await refresh(); }} />}
      {selected && <MachineDetailModal m={selected} onClose={() => setSelected(null)} onDelete={() => onDelete(selected)} />}
    </main>
  );
}

function MachineCard({ m, onOpen }: { m: OwnedMachine; onOpen: () => void }) {
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
        <p style={{ margin: 0, fontSize: 16, fontWeight: 500 }}>{m.name || procLabel(m.process)}</p>
        <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 5, fontFamily: MONO, fontSize: 10, color: C.user }}>
          <ProvDot p="USER" size={6} /> USER
        </span>
      </div>
      <p style={{ margin: "4px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink45 }}>{procLabel(m.process)}{m.count && m.count > 1 ? ` · ×${m.count}` : ""}</p>
      <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 7, fontFamily: MONO, fontSize: 11.5 }}>
        <Row k="envelope" v={envelopeSummary(m) ?? "—"} />
        <Row k="materials" v={(m.materials && m.materials.length ? m.materials.join(", ") : "—")} />
        <Row k="rate" v={m.hourly_rate_usd != null ? `${USD(m.hourly_rate_usd)}/hr` : "—"} vColor={m.hourly_rate_usd != null ? C.user : C.ink40} />
        <Row k="max workpiece" v={m.max_workpiece_kg != null ? `${m.max_workpiece_kg} kg` : "—"} />
      </div>
    </button>
  );
}

function Row({ k, v, vColor = C.ink }: { k: string; v: string; vColor?: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
      <span style={{ color: C.ink45 }}>{k}</span>
      <span style={{ color: vColor, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "60%" }}>{v}</span>
    </div>
  );
}

function ModalShell({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div
      style={{ position: "fixed", inset: 0, zIndex: 60, background: "rgba(23,24,26,0.35)", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ width: 520, maxWidth: "100%", maxHeight: "90vh", overflowY: "auto", background: C.panel, border: `1px solid ${C.hair}`, borderRadius: 18, boxShadow: "0 18px 50px -18px rgba(23,24,26,0.35)", padding: 24, animation: "vscreenIn 220ms cubic-bezier(0.2,0,0,1) both" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <p style={{ margin: 0, fontSize: 18, fontWeight: 500 }}>{title}</p>
          <button type="button" onClick={onClose} style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", fontFamily: MONO, fontSize: 14, color: C.ink40 }}>✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  background: C.bg,
  border: `1px solid ${C.hair}`,
  borderRadius: 8,
  padding: "8px 12px",
  fontSize: 13,
  color: C.ink,
  fontFamily: "inherit",
  outline: "none",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "block" }}>
      <span style={{ display: "block", fontFamily: MONO, fontSize: 10, letterSpacing: "0.06em", color: C.ink45, marginBottom: 5 }}>{label}</span>
      {children}
    </label>
  );
}

function AddMachineModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void | Promise<void> }) {
  const [name, setName] = useState("");
  const [process, setProcess] = useState("cnc_3axis");
  const [count, setCount] = useState("1");
  const [rate, setRate] = useState("");
  const [maxKg, setMaxKg] = useState("");
  const [materials, setMaterials] = useState("");
  const [x, setX] = useState("");
  const [y, setY] = useState("");
  const [z, setZ] = useState("");
  const [swing, setSwing] = useState("");
  const [between, setBetween] = useState("");
  const [busy, setBusy] = useState(false);

  const isTurning = process === "cnc_turning";

  const submit = async () => {
    setBusy(true);
    const num = (s: string): number | undefined => {
      const n = parseFloat(s);
      return Number.isFinite(n) ? n : undefined;
    };
    const cap: Record<string, number> = {};
    if (isTurning) {
      if (num(swing) != null) cap.swing_dia = num(swing)!;
      if (num(between) != null) cap.between_centers = num(between)!;
    } else {
      if (num(x) != null) cap.x = num(x)!;
      if (num(y) != null) cap.y = num(y)!;
      if (num(z) != null) cap.z = num(z)!;
    }
    const body: MachineInput = {
      name: name.trim() || null,
      process,
      count: num(count) ?? 1,
      hourly_rate_usd: num(rate) ?? null,
      max_workpiece_kg: num(maxKg) ?? null,
      materials: materials.trim() ? materials.split(",").map((s) => s.trim()).filter(Boolean) : null,
      capabilities: Object.keys(cap).length ? cap : null,
    };
    try {
      await createMachine(body);
      toast.success(`Declared ${body.name || procLabel(process)} — ● USER`);
      await onCreated();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Create failed");
      setBusy(false);
    }
  };

  return (
    <ModalShell title="Add a machine — declare the denominator" onClose={onClose}>
      <p style={{ margin: "6px 0 16px", fontFamily: MONO, fontSize: 10.5, color: C.ink45, display: "inline-flex", alignItems: "center", gap: 6 }}>
        <ProvDot p="USER" size={6} /> a declared capability is a USER assertion, never a measurement of the machine
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <Field label="NAME"><input style={inputStyle} value={name} onChange={(e) => setName(e.target.value)} placeholder="Haas VF-2" /></Field>
        <Field label="PROCESS">
          <select style={inputStyle} value={process} onChange={(e) => setProcess(e.target.value)}>
            {PROCESS_OPTIONS.map((p) => (
              <option key={p} value={p}>{procLabel(p)}</option>
            ))}
          </select>
        </Field>
        <Field label="COUNT"><input style={inputStyle} value={count} onChange={(e) => setCount(e.target.value)} inputMode="numeric" /></Field>
        <Field label="HOURLY RATE (USD)"><input style={inputStyle} value={rate} onChange={(e) => setRate(e.target.value)} inputMode="decimal" placeholder="95" /></Field>
        {isTurning ? (
          <>
            <Field label="SWING Ø (mm)"><input style={inputStyle} value={swing} onChange={(e) => setSwing(e.target.value)} inputMode="decimal" /></Field>
            <Field label="BETWEEN CENTERS (mm)"><input style={inputStyle} value={between} onChange={(e) => setBetween(e.target.value)} inputMode="decimal" /></Field>
          </>
        ) : (
          <>
            <Field label="ENVELOPE X (mm)"><input style={inputStyle} value={x} onChange={(e) => setX(e.target.value)} inputMode="decimal" /></Field>
            <Field label="ENVELOPE Y (mm)"><input style={inputStyle} value={y} onChange={(e) => setY(e.target.value)} inputMode="decimal" /></Field>
            <Field label="ENVELOPE Z (mm)"><input style={inputStyle} value={z} onChange={(e) => setZ(e.target.value)} inputMode="decimal" /></Field>
          </>
        )}
        <Field label="MAX WORKPIECE (kg)"><input style={inputStyle} value={maxKg} onChange={(e) => setMaxKg(e.target.value)} inputMode="decimal" /></Field>
      </div>
      <div style={{ marginTop: 12 }}>
        <Field label="MATERIALS (comma-separated)"><input style={inputStyle} value={materials} onChange={(e) => setMaterials(e.target.value)} placeholder="6061, 316L, PP" /></Field>
      </div>
      <div style={{ marginTop: 18, display: "flex", justifyContent: "flex-end", gap: 10 }}>
        <GhostButton onClick={onClose}>Cancel</GhostButton>
        <GhostButton primary disabled={busy} onClick={submit}>{busy ? "Saving…" : "Declare machine"}</GhostButton>
      </div>
    </ModalShell>
  );
}

function MachineDetailModal({ m, onClose, onDelete }: { m: OwnedMachine; onClose: () => void; onDelete: () => void }) {
  return (
    <ModalShell title={m.name || procLabel(m.process)} onClose={onClose}>
      <p style={{ margin: "4px 0 14px", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>{procLabel(m.process)}</p>
      <Kicker>SPEC — THE DENOMINATOR · ● USER</Kicker>
      <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 9, fontFamily: MONO, fontSize: 12 }}>
        <Row k="envelope" v={envelopeSummary(m) ?? "undeclared"} />
        <Row k="materials" v={m.materials && m.materials.length ? m.materials.join(", ") : "undeclared"} />
        <Row k="rate" v={m.hourly_rate_usd != null ? `${USD(m.hourly_rate_usd)}/hr` : "undeclared"} vColor={C.user} />
        <Row k="max workpiece" v={m.max_workpiece_kg != null ? `${m.max_workpiece_kg} kg` : "undeclared"} />
        <Row k="count" v={String(m.count ?? 1)} />
        <Row k="capital fraction" v={m.capital_frac != null ? String(m.capital_frac) : "undeclared"} />
      </div>
      {m.notes && <p style={{ margin: "12px 0 0", fontSize: 12.5, color: C.ink55 }}>{m.notes}</p>}
      <div style={{ marginTop: 18, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink40 }}>id {m.id.slice(0, 10)}…</span>
        <GhostButton onClick={onDelete} style={{ borderColor: "rgba(194,69,58,0.4)", color: C.fail }}>Delete machine</GhostButton>
      </div>
    </ModalShell>
  );
}
