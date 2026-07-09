"use client";

/**
 * ASSEMBLY CONTEXT PANEL — the right-hand surface when the upload is a real
 * multi-part assembly (>= 2 solids), in place of the single-part verdict walk.
 *
 * It is deliberately HONEST: P2 delivers the in-design part-in-context render +
 * part-of-interest selection only. The context-fed per-part verdict/cost/DFM is
 * P3 — so this panel shows the real product tree and the selected part's REAL
 * measured geometry, and states plainly that per-part analysis is coming, rather
 * than fabricating a single-part verdict over the wrong thing. Same light-
 * instrument idiom as VerifyScreen (Card / Kicker / mono evidence).
 */
import { useMemo, type ReactNode } from "react";
import { C, MONO } from "@/lib/verify/tokens";

/** Fixed-decimal formatter for measured geometry — "—" when absent. */
function fx(n: number | null | undefined, dp: number): string {
  return n != null && Number.isFinite(n) ? n.toFixed(dp) : "—";
}
import { Card, Kicker, ProvChip } from "./primitives";
import { looksLikeFastener, type AssemblyModel, type PartInstance } from "@/lib/verify/assembly";

export function AssemblyPanel({
  model,
  fileName,
  selectedId,
  onSelect,
}: {
  model: AssemblyModel;
  fileName: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const selected = useMemo(
    () => model.parts.find((p) => p.id === selectedId) ?? null,
    [model.parts, selectedId]
  );

  // Order for the picker: substantive parts (largest first), then hardware.
  const ordered = useMemo(() => {
    const byVol = (a: PartInstance, b: PartInstance) =>
      (b.world?.volume ?? 0) - (a.world?.volume ?? 0);
    const main = model.parts.filter((p) => !looksLikeFastener(p)).sort(byVol);
    const hw = model.parts.filter((p) => looksLikeFastener(p)).sort(byVol);
    return [...main, ...hw];
  }, [model.parts]);

  const uniqueDesigns = Object.keys(model.unique_designs ?? {}).length;

  return (
    <section
      style={{
        flex: 1,
        minWidth: 0,
        overflowY: "auto",
        background: C.bg,
        padding: "26px 30px 40px",
      }}
    >
      {/* Honest header — it is an ASSEMBLY, and what we do (and don't) claim. */}
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
        <div>
          <Kicker>ASSEMBLY CONTEXT</Kicker>
          <h2 style={{ margin: "6px 0 0", fontSize: 20, fontWeight: 400, letterSpacing: "-0.01em", color: C.ink }}>
            {fileName ?? "assembly"}
          </h2>
        </div>
        <span style={{ fontFamily: MONO, fontSize: 11, color: C.measured, whiteSpace: "nowrap" }}>
          ● {model.part_count} parts
        </span>
      </div>

      <p style={{ margin: "10px 0 0", fontSize: 13, lineHeight: 1.55, color: C.ink55 }}>
        Real STEP assembly — {model.part_count} solids, {uniqueDesigns} unique designs, in
        their baked world positions. Pick the part of interest to highlight it in context.
      </p>

      {/* The honest gate — no fabricated verdict for a multi-part upload. */}
      <div
        data-testid="assembly-analysis-gate"
        style={{
          margin: "16px 0 20px",
          border: `1px solid ${C.hair}`,
          borderLeft: `3px solid ${C.cond}`,
          background: "#fff",
          borderRadius: 10,
          padding: "12px 14px",
        }}
      >
        <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.1em", color: C.cond }}>
          PER-PART ANALYSIS — COMING
        </p>
        <p style={{ margin: "6px 0 0", fontSize: 12.5, lineHeight: 1.5, color: C.ink60 }}>
          The context-fed verdict, cost and DFM (service world from the part&apos;s role,
          real annual volume from the tree, clearance/interference against neighbours) is
          the next step. This view is the honest render + selection — it does not assert a
          single-part verdict over an assembly.
        </p>
      </div>

      {/* Part-of-interest picker — a tree/list of the real product tree. */}
      <Card>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
          <Kicker>PRODUCT TREE · PART OF INTEREST</Kicker>
          <ProvChip p="MEASURED" />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {ordered.map((p) => {
            const active = p.id === selectedId;
            const fastener = looksLikeFastener(p);
            return (
              <button
                key={p.id}
                type="button"
                data-testid="assembly-part-row"
                data-selected={active}
                onClick={() => onSelect(p.id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  width: "100%",
                  textAlign: "left",
                  border: active ? `1px solid ${C.user}` : `1px solid ${C.hair}`,
                  background: active ? "rgba(122,99,201,0.08)" : "#fff",
                  borderRadius: 9,
                  padding: "9px 11px",
                  cursor: "pointer",
                  fontFamily: "inherit",
                }}
              >
                <span
                  aria-hidden
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: fastener ? 2 : "50%",
                    background: active ? C.user : C.ink35,
                    flexShrink: 0,
                  }}
                />
                <span style={{ minWidth: 0, flex: 1 }}>
                  <span style={{ display: "block", fontSize: 13, color: C.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {p.name || p.occurrence || p.id}
                    {p.instance > 1 && (
                      <span style={{ color: C.ink40, fontFamily: MONO, fontSize: 11 }}> ·{p.instance}</span>
                    )}
                  </span>
                  <span style={{ display: "block", fontFamily: MONO, fontSize: 10, color: C.ink40, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {p.tree_path}
                  </span>
                </span>
                {fastener && (
                  <span style={{ fontFamily: MONO, fontSize: 9.5, color: C.ink40, flexShrink: 0 }}>hardware</span>
                )}
              </button>
            );
          })}
        </div>
      </Card>

      {/* The selected part's REAL measured geometry (no verdict). */}
      {selected && <SelectedPartCard part={selected} />}
    </section>
  );
}

function SelectedPartCard({ part }: { part: PartInstance }) {
  const gs = part.geometry_summary;
  const w = part.world;
  const dims = w?.bbox_size ?? gs?.bbox_dims ?? null;
  return (
    <div style={{ marginTop: 16 }}>
      <Card>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
          <Kicker color={C.user}>SELECTED PART</Kicker>
          <ProvChip p="MEASURED" />
        </div>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 400, color: C.ink }}>
          {part.name || part.occurrence || part.id}
        </h3>
        <p style={{ margin: "5px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45, overflowWrap: "anywhere" }}>
          {part.tree_path}
        </p>
        <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <Stat label="bbox (mm)" value={dims ? dims.map((n) => fx(n, 1)).join(" × ") : "—"} />
          <Stat label="volume (cm³)" value={w?.volume != null ? fx(w.volume / 1000, 2) : "—"} />
          <Stat label="B-rep faces" value={gs ? String(gs.num_boundary_faces) : "—"} />
          <Stat label="triangles" value={gs ? String(gs.num_triangles) : "—"} />
          <Stat
            label="centroid (mm)"
            value={w?.centroid ? w.centroid.map((n) => fx(n, 0)).join(", ") : "—"}
          />
          <Stat
            label="instance"
            value={`#${part.instance}`}
          />
        </div>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <p style={{ margin: 0, fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.08em", color: C.ink40 }}>
        {label.toUpperCase()}
      </p>
      <p style={{ margin: "3px 0 0", fontFamily: MONO, fontSize: 13, color: C.ink }}>{value}</p>
    </div>
  );
}
