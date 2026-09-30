"use client";

import { useEffect, useState } from "react";
import { C, MONO, procLabel, PROCESS_LABELS } from "@/lib/verify/tokens";
import {
  listMachines,
  createMachine,
  type OwnedMachine,
} from "@/lib/verify/machine-api";

const PROCESS_OPTIONS = Object.keys(PROCESS_LABELS);

export function HomeScreen({
  onPickFile,
  onDropFile,
  nav,
}: {
  onPickFile: () => void;
  onDropFile: (file: File) => void;
  onSample: () => void;
  onOpenGuide: () => void;
  nav: (s: string) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);

  // machine picker
  const [machinePickerOpen, setMachinePickerOpen] = useState(false);
  const [machines, setMachines] = useState<OwnedMachine[] | null>(null);
  const [selectedMachineId, setSelectedMachineId] = useState<string | null>(null);
  const [addingMachine, setAddingMachine] = useState(false);
  const [newProcess, setNewProcess] = useState(PROCESS_OPTIONS[0]);
  const [newName, setNewName] = useState("");
  const [newRate, setNewRate] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!machinePickerOpen || machines !== null) return;
    listMachines().then((p) => setMachines(p.machines)).catch(() => setMachines([]));
  }, [machinePickerOpen, machines]);

  async function handleAddMachine() {
    setSaving(true);
    try {
      const m = await createMachine({
        process: newProcess,
        name: newName.trim() || null,
        hourly_rate_usd: newRate ? parseFloat(newRate) : null,
      });
      setMachines((prev) => [...(prev ?? []), m]);
      setSelectedMachineId(m.id);
      setAddingMachine(false);
      setNewName("");
      setNewRate("");
    } finally {
      setSaving(false);
    }
  }

  const selectedMachine = machines?.find((m) => m.id === selectedMachineId);

  const fieldStyle = {
    width: "100%",
    boxSizing: "border-box" as const,
    height: 34,
    border: `1px solid ${C.hair}`,
    borderRadius: 8,
    background: C.bg,
    padding: "0 10px",
    fontFamily: "inherit",
    fontSize: 13,
    color: C.ink,
    outline: "none",
  };

  return (
    <main style={{ flex: 1, overflowY: "auto", padding: "36px 44px", background: C.bg }}>
      {/* Page header */}
      <div style={{ maxWidth: 760 }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 350, letterSpacing: "-0.02em", lineHeight: 1.25, color: C.ink }}>
          Drop a CAD file — get the decision, then the receipts.
        </h1>
        <p style={{ margin: "10px 0 0", fontSize: 13.5, lineHeight: 1.65, color: C.ink55, maxWidth: 680 }}>
          The manufacturing decision first — make by X, $Y/unit, Z days, switch to a mold above N — with the
          glass-box drivers, geometric routing, and DFM evidence one click away. The resident Inspector traces
          any number to its governed source.
        </p>
      </div>

      {/* Drop zone card */}
      <div style={{ marginTop: 28, maxWidth: 760, border: `1.5px dashed ${dragging ? C.measured : C.hair}`, borderRadius: 18, background: dragging ? "rgba(55,114,171,0.04)" : C.panel, transition: "border-color 120ms, background 120ms", overflow: "hidden" }}>

        {/* Drop target */}
        <button
          type="button"
          onClick={onPickFile}
          onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files?.[0]; if (f) onDropFile(f); }}
          style={{ width: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "44px 32px 36px", background: "transparent", border: "none", cursor: "pointer", fontFamily: "inherit", color: "inherit", textAlign: "center" }}
        >
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke={dragging ? C.measured : C.ink35} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ marginBottom: 14, transition: "stroke 120ms" }}>
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          <p style={{ margin: 0, fontSize: 14.5, fontWeight: 600, color: dragging ? C.measured : C.ink, transition: "color 120ms" }}>
            Drag and drop or click to upload
          </p>
          <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.035em", color: C.ink45, lineHeight: 1.7 }}>
            STL, STEP, STP, IGES or IGS<br />
            CAD is parsed and discarded in-process · zero egress
          </p>
          <span style={{ display: "inline-block", marginTop: 20, background: C.ink, color: "#fff", borderRadius: 999, padding: "8px 22px", fontSize: 12.5, fontWeight: 500, pointerEvents: "none" }}>
            Browse files
          </span>
        </button>

        {/* Options accordion */}
        <div style={{ borderTop: `1px solid ${C.hair}` }}>
          <button
            type="button"
            onClick={() => setOptionsOpen((o) => !o)}
            style={{ width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "11px 20px", background: "transparent", border: "none", cursor: "pointer", fontFamily: "inherit", color: "inherit", textAlign: "left" }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke={C.ink45} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ transform: optionsOpen ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 160ms", flexShrink: 0 }}>
              <polyline points="9 18 15 12 9 6" />
            </svg>
            <span style={{ fontFamily: MONO, fontSize: 11, color: C.ink55 }}>Options</span>
            <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink35, marginLeft: 4 }}>optional — sensible defaults applied</span>
          </button>

          {optionsOpen && (
            <div style={{ padding: "4px 20px 20px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px 24px" }}>
              {[
                { label: "Annual volume", placeholder: "1 000 units/yr", hint: "used for amortisation" },
                { label: "Target unit cost", placeholder: "e.g. $28.00", hint: "flags routes that miss it" },
                { label: "Lead time constraint", placeholder: "e.g. 10 days", hint: "filters viable routes" },
                { label: "Material preference", placeholder: "e.g. 6061-T6", hint: "overrides auto-selection" },
              ].map((f) => (
                <div key={f.label}>
                  <label style={{ display: "block", fontFamily: MONO, fontSize: 10, letterSpacing: "0.07em", color: C.ink45, marginBottom: 5 }}>
                    {f.label.toUpperCase()}
                  </label>
                  <input type="text" placeholder={f.placeholder} style={fieldStyle} />
                  <p style={{ margin: "4px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>{f.hint}</p>
                </div>
              ))}

              {/* Machine picker — full width */}
              <div style={{ gridColumn: "1 / -1" }}>
                <label style={{ display: "block", fontFamily: MONO, fontSize: 10, letterSpacing: "0.07em", color: C.ink45, marginBottom: 5 }}>
                  YOUR MACHINES
                </label>

                {/* Trigger row */}
                <button
                  type="button"
                  onClick={() => { setMachinePickerOpen((o) => !o); setAddingMachine(false); }}
                  style={{ width: "100%", height: 34, border: `1px solid ${C.hair}`, borderRadius: machinePickerOpen ? "8px 8px 0 0" : 8, background: C.bg, padding: "0 10px", fontFamily: MONO, fontSize: 11, color: selectedMachine ? C.ink : C.measured, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "space-between" }}
                >
                  <span>
                    {selectedMachine
                      ? `${selectedMachine.name || procLabel(selectedMachine.process)} · ${procLabel(selectedMachine.process)}`
                      : "Choose or add a machine"}
                  </span>
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ transform: machinePickerOpen ? "rotate(180deg)" : "none", transition: "transform 160ms" }}>
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </button>

                {/* Expanded picker */}
                {machinePickerOpen && (
                  <div style={{ border: `1px solid ${C.hair}`, borderTop: "none", borderRadius: "0 0 8px 8px", background: C.panel, overflow: "hidden" }}>

                    {/* Machine list */}
                    {machines === null ? (
                      <p style={{ margin: 0, padding: "10px 12px", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>Loading…</p>
                    ) : machines.length === 0 && !addingMachine ? (
                      <p style={{ margin: 0, padding: "10px 12px", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>No machines declared yet.</p>
                    ) : (
                      machines.map((m) => (
                        <button
                          key={m.id}
                          type="button"
                          onClick={() => { setSelectedMachineId(m.id === selectedMachineId ? null : m.id); setMachinePickerOpen(false); }}
                          style={{ width: "100%", display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", background: m.id === selectedMachineId ? "rgba(55,114,171,0.06)" : "transparent", border: "none", borderBottom: `1px solid ${C.hair}`, cursor: "pointer", fontFamily: "inherit", textAlign: "left" }}
                        >
                          <span style={{ flex: 1, fontSize: 12.5, color: C.ink }}>
                            {m.name || procLabel(m.process)}
                            <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink45, marginLeft: 8 }}>{procLabel(m.process)}</span>
                          </span>
                          {m.hourly_rate_usd != null && (
                            <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>${m.hourly_rate_usd}/hr</span>
                          )}
                          {m.id === selectedMachineId && (
                            <span style={{ fontFamily: MONO, fontSize: 10, color: C.measured }}>✓</span>
                          )}
                        </button>
                      ))
                    )}

                    {/* Add machine form */}
                    {addingMachine ? (
                      <div style={{ padding: "12px", display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 8, alignItems: "end", borderTop: machines && machines.length > 0 ? `1px solid ${C.hair}` : "none" }}>
                        <div>
                          <label style={{ display: "block", fontFamily: MONO, fontSize: 9.5, color: C.ink45, marginBottom: 4 }}>PROCESS</label>
                          <select
                            value={newProcess}
                            onChange={(e) => setNewProcess(e.target.value)}
                            style={{ ...fieldStyle, height: 32, fontSize: 12 }}
                          >
                            {PROCESS_OPTIONS.map((p) => (
                              <option key={p} value={p}>{procLabel(p)}</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label style={{ display: "block", fontFamily: MONO, fontSize: 9.5, color: C.ink45, marginBottom: 4 }}>NAME (optional)</label>
                          <input
                            type="text"
                            placeholder="e.g. Haas VF-2"
                            value={newName}
                            onChange={(e) => setNewName(e.target.value)}
                            style={{ ...fieldStyle, height: 32, fontSize: 12 }}
                          />
                        </div>
                        <div>
                          <label style={{ display: "block", fontFamily: MONO, fontSize: 9.5, color: C.ink45, marginBottom: 4 }}>$/HR</label>
                          <input
                            type="number"
                            placeholder="85"
                            value={newRate}
                            onChange={(e) => setNewRate(e.target.value)}
                            style={{ ...fieldStyle, height: 32, fontSize: 12, width: 72 }}
                          />
                        </div>
                        <div style={{ gridColumn: "1 / -1", display: "flex", gap: 8 }}>
                          <button
                            type="button"
                            onClick={() => void handleAddMachine()}
                            disabled={saving}
                            style={{ height: 30, background: C.ink, color: "#fff", border: "none", borderRadius: 6, padding: "0 14px", fontFamily: "inherit", fontSize: 12, fontWeight: 500, cursor: saving ? "default" : "pointer", opacity: saving ? 0.6 : 1 }}
                          >
                            {saving ? "Saving…" : "Save"}
                          </button>
                          <button
                            type="button"
                            onClick={() => setAddingMachine(false)}
                            style={{ height: 30, background: "transparent", color: C.ink55, border: `1px solid ${C.hair}`, borderRadius: 6, padding: "0 12px", fontFamily: "inherit", fontSize: 12, cursor: "pointer" }}
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setAddingMachine(true)}
                        style={{ width: "100%", padding: "8px 12px", background: "transparent", border: "none", borderTop: machines && machines.length > 0 ? `1px solid ${C.hair}` : "none", cursor: "pointer", fontFamily: MONO, fontSize: 10.5, color: C.measured, textAlign: "left" }}
                      >
                        + Add a machine
                      </button>
                    )}
                  </div>
                )}

                <p style={{ margin: "4px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>
                  declared machines set the marginal cost of in-house routes
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
