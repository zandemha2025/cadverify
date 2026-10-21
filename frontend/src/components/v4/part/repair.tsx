"use client";

/** O14: repair a part that isn't a closed solid, and say exactly what the repair changed. */
import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { API_BASE } from "@/lib/api-base";
import type { RepairResult } from "@/lib/api";
import { apiProblemDetail, apiRecoveryMessage } from "@/lib/api-recovery";
import { CAD_ACCEPT } from "../pending-file";
import { R } from "../routes";
import { dimsText, plural, trimNum } from "./model";
import { openEdges } from "./cant-read";
import { SheetTop, type FigItem } from "./sheet-bits";
import type { CheckSession } from "./store";
import type { ViewerController } from "./viewer";
import "./part.css";

const PartViewer = dynamic(() => import("./viewer"), { ssr: false });

/** What one repair request came back with (shared with the find-and-fix dialog). */
export type RepairOutcome =
  | { s: "error"; msg: string }
  | { s: "failed"; r: RepairResult }
  | { s: "fixed"; r: RepairResult; file: File; url: string };

type Out = { s: "ready" } | { s: "running" } | RepairOutcome;

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** POST /validate/repair on a copy of the file: on every plan; it doesn't use a check. */
export async function runRepair(file: File): Promise<RepairOutcome> {
  const form = new FormData();
  form.append("file", file);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/validate/repair`, { method: "POST", body: form });
  } catch {
    return { s: "error", msg: "The repair couldn't reach the server. Try again." };
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    return { s: "error", msg: apiProblemDetail(body) ?? apiRecoveryMessage({ status: res.status, payload: body, resource: "repair" }) };
  }
  const r = body as RepairResult;
  if (!r.repair_applied || !r.repaired_file_b64) return { s: "failed", r };
  const name = r.repair_verification?.download_filename ?? `${file.name.replace(/\.[^.]+$/, "")}-repaired.stl`;
  const bytes = b64ToBytes(r.repaired_file_b64);
  const fixed = new File([bytes.buffer as ArrayBuffer], name, { type: "model/stl" });
  return { s: "fixed", r, file: fixed, url: URL.createObjectURL(fixed) };
}

/** Why a repair didn't close the shell, in the engine's words. */
export function repairFailedReason(r: RepairResult): string {
  return (r.repair_details as { reason?: string }).reason ?? r.repair_details.error ?? "Repair did not produce a watertight solid.";
}

export function RepairView({ session, onPick, onBack }: { session: CheckSession; onPick: (f: File) => void; onBack: () => void }) {
  const [out, setOut] = React.useState<Out>({ s: "ready" });
  const [picked, setPicked] = React.useState<File | null>(null);
  const input = React.useRef<HTMLInputElement>(null);
  const c1 = React.useRef(null) as ViewerController;
  const c2 = React.useRef(null) as ViewerController;
  const [, setV] = React.useState("");
  const v = session.validation ?? session.result?.validation ?? null;
  const edges = openEdges(session);
  const dims = dimsText(v?.geometry.bounding_box_mm);
  const url = out.s === "fixed" ? out.url : null;
  React.useEffect(() => () => {
    if (url) URL.revokeObjectURL(url);
  }, [url]);

  const run = async () => {
    setOut({ s: "running" });
    setOut(await runRepair(session.file));
  };

  const fixed = out.s === "fixed" ? out : null;
  const d = fixed?.r.repair_details as (RepairResult["repair_details"] & { volume_change_pct?: number; original_volume_mm3?: number; repaired_volume_mm3?: number; volume_warning?: string | null; reason?: string }) | undefined;
  const pct = d?.volume_change_pct;
  const figs: FigItem[] = fixed
    ? [
        ...(pct != null ? [{ k: "Volume change", v: `${pct > 0 ? "+" : ""}${trimNum(pct, 1)}%`, s: d?.volume_warning ? "the shape changed" : "small", tone: (Math.abs(pct) >= 2 ? "warn" : undefined) as FigItem["tone"] }] : []),
        { k: "Verdict", v: fixed.r.repair_verification?.repaired_verdict ?? "—", s: `was ${fixed.r.repair_verification?.original_verdict ?? "—"}` },
      ]
    : [
        { k: "Open edges", v: edges != null ? edges.toLocaleString("en-US") : "—", s: "not a closed solid", tone: "bad" },
        { k: "Methods", v: `0 of ${v?.process_scores.length ?? 21}`, s: "need a closed solid" },
      ];
  const failedReason = out.s === "failed" ? repairFailedReason(out.r) : null;
  const rv = fixed?.r.repaired_analysis;
  return (
    <main className="world pv" aria-label="Repair">
      <section className="stage" aria-label="The file">
        <div className="floor" />
        <div className="hud">
          <Link href={R.parts} style={{ fontSize: 12.5, textDecoration: "none", marginBottom: 2 }}>
            ‹ Parts
          </Link>
          <h1 title={session.file.name}>{session.file.name}</h1>
          <span className="num">{[dims, "open shell", edges != null ? plural(edges, "open edge") : null, v ? `${v.geometry.faces.toLocaleString("en-US")} faces` : null].filter(Boolean).join(" · ")}</span>
          <span>Nothing is priced from a shape that isn&apos;t closed</span>
        </div>
        {!fixed ? (
          session.preview.url ? (
            <div className="obj swap" role="img" aria-label="Your file as read, with its open shell">
              <span className="shade" />
              <PartViewer url={session.preview.url} highlight={null} xray={false} controllerRef={c1} onState={setV} />
            </div>
          ) : null
        ) : (
          <div className="swap" style={{ position: "absolute", left: 40, right: 512, top: 150, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <figure style={{ margin: 0, display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
              <div style={{ position: "relative", width: "100%", maxWidth: 400, aspectRatio: "1" }} role="img" aria-label="Your file">
                {session.preview.url ? <PartViewer url={session.preview.url} highlight={null} xray={false} controllerRef={c1} onState={setV} /> : null}
              </div>
              <figcaption className="tag" style={{ position: "static", alignItems: "center" }}>
                <b>Your file</b>open shell{d?.original_volume_mm3 != null ? ` · ${Math.round(d.original_volume_mm3).toLocaleString("en-US")} mm³` : ""}
              </figcaption>
            </figure>
            <figure style={{ margin: 0, display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
              <div style={{ position: "relative", width: "100%", maxWidth: 400, aspectRatio: "1" }} role="img" aria-label="The repaired mesh">
                <PartViewer url={fixed.url} kind="stl" highlight={null} xray={false} controllerRef={c2} onState={setV} />
              </div>
              <figcaption className="tag" style={{ position: "static", alignItems: "center", borderColor: d?.volume_warning ? "#E9C46A" : undefined }}>
                <b>Repaired</b>closed{d?.repaired_volume_mm3 != null ? ` · ${Math.round(d.repaired_volume_mm3).toLocaleString("en-US")} mm³` : ""}
              </figcaption>
            </figure>
          </div>
        )}
      </section>
      <aside className="sheet" aria-label="What's wrong and what to do">
        <SheetTop title={fixed ? (d?.volume_warning ? "Repaired, with a change" : "Repaired") : "Not a closed solid"} meta={fixed ? "Watertight now · not saved" : `${session.file.name} · nothing priced`} figs={figs} />
        <div className="scroll">
          <div className="note" style={{ marginTop: 8 }}>
            <b>Not watertight</b>
            <span>{v?.universal_issues.find((i) => i.code === "NON_WATERTIGHT")?.message ?? "Every process needs a closed solid."}</span>
          </div>
          {out.s === "ready" || out.s === "running" || out.s === "error" ? (
            <div className="swap">
              <div className="gh">
                <span>
                  Repair it here <small style={{ fontWeight: 500, border: "1px solid var(--rule2)", borderRadius: 999, padding: "0 6px", marginLeft: 4 }}>No check used</small>
                </span>
                <span />
              </div>
              <div className="note" style={{ marginTop: 2 }}>
                <span>Tries to close the gaps, then checks the result the same way as an upload. Shows both side by side; changes to the shape are reported, never hidden.</span>
                <span>
                  <button className="btn ink sm" type="button" onClick={() => void run()} disabled={out.s === "running"}>
                    {out.s === "running" ? "Repairing…" : "Try repair"}
                  </button>
                </span>
                {out.s === "error" ? <span role="alert" style={{ color: "var(--bad)", fontSize: 13 }}>{out.msg}</span> : null}
              </div>
            </div>
          ) : null}
          {out.s === "failed" ? (
            <div className="note swap" role="alert" style={{ borderColor: "#F5D5D0" }}>
              <b>Repair didn&apos;t close it</b>
              <span>{failedReason}</span>
              <span className="kv" style={{ padding: 0 }}>
                <span>Method</span>
                <b>{out.r.repair_details.tier ? `mesh repair, ${out.r.repair_details.tier}` : "mesh repair"}</b>
                {out.r.repair_details.duration_ms != null ? (
                  <>
                    <span>Time</span>
                    <b className="num">{(out.r.repair_details.duration_ms / 1000).toFixed(1)} s</b>
                  </>
                ) : null}
                <span>Open edges after</span>
                <b className="num">still open</b>
              </span>
            </div>
          ) : null}
          {fixed ? (
            <div className="swap">
              <div className="note" style={{ marginTop: 10, borderColor: d?.volume_warning ? "#E9C46A" : undefined }}>
                <b>{d?.volume_warning ? "Closed, but it changed the part" : "Closed"}</b>
                <span>
                  {pct != null ? `The volume ${pct >= 0 ? "grew" : "shrank"} ${trimNum(Math.abs(pct), 1)}%. ` : ""}
                  {d?.volume_warning ?? "Compare the two before using the repaired file."}
                </span>
              </div>
              <div className="gh">
                <span>Before and after</span>
                <span />
              </div>
              <div className="lines">
                {[
                  ["Faces", d?.original_faces?.toLocaleString("en-US") ?? "—", d?.repaired_faces?.toLocaleString("en-US") ?? "—"],
                  ["Volume", d?.original_volume_mm3 != null ? `${Math.round(d.original_volume_mm3).toLocaleString("en-US")} mm³` : "—", d?.repaired_volume_mm3 != null ? `${Math.round(d.repaired_volume_mm3).toLocaleString("en-US")} mm³${pct != null ? ` · ${pct > 0 ? "+" : ""}${trimNum(pct, 1)}%` : ""}` : "—"],
                  ["Closed solid", "no", rv?.geometry.is_watertight ? "yes" : "—"],
                  ["Verdict", fixed.r.repair_verification?.original_verdict ?? "—", fixed.r.repair_verification?.repaired_verdict ?? "—"],
                  ["Repair", "", `${d?.tier ? `mesh repair, ${d.tier}` : "mesh repair"}${d?.duration_ms != null ? ` · ${(d.duration_ms / 1000).toFixed(1)} s` : ""}`],
                ].map(([k, a, b]) => (
                  <div key={k} className="ln" style={{ gridTemplateColumns: "minmax(0,1fr) auto auto" }}>
                    <span>{k}</span>
                    <span className="num" style={{ color: "var(--ink3)" }}>
                      {a}
                    </span>
                    <b className="num" style={{ minWidth: 96 }}>
                      {b}
                    </b>
                  </div>
                ))}
              </div>
              {fixed.r.repair_verification ? (
                <p className="mono" style={{ margin: "6px 12px 0", fontSize: 11.5, color: "var(--ink3)" }}>
                  SHA-256 original {fixed.r.repair_verification.original_sha256.slice(0, 8)}… · repaired {fixed.r.repair_verification.repaired_sha256.slice(0, 8)}…
                </p>
              ) : null}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", padding: "10px 12px 0" }}>
                <a className="btn sm" href={fixed.url} download={fixed.file.name}>
                  Download repaired STL
                </a>
                <button className="btn sm" type="button" onClick={() => onPick(fixed.file)}>
                  Check the repaired file
                </button>
              </div>
              <p style={{ margin: "6px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>Checking it saves it as a new part, separate from this file · uses 1 check.</p>
            </div>
          ) : null}
          <div className="gh" style={{ marginTop: 10 }}>
            <span>Fix it in CAD</span>
            <span>
              <button className="btn sm ghost" type="button" onClick={onBack} style={{ height: 24 }}>
                Steps for your CAD tool
              </button>
            </span>
          </div>
          <p style={{ margin: "0 12px", color: "var(--ink2)", fontSize: 13 }}>Heal or close the gap, then export the solid body, not surfaces.</p>
          <div className="gh" style={{ marginTop: 10 }}>
            <span>Upload a fixed file</span>
            <span />
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "0 12px", flexWrap: "wrap" }}>
            <button className="btn ink sm" type="button" onClick={() => input.current?.click()}>
              Choose file
            </button>
            <input
              ref={input}
              type="file"
              accept={CAD_ACCEPT}
              aria-label="Choose the fixed CAD file"
              tabIndex={-1}
              style={{ display: "none" }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) {
                  setPicked(f);
                  onPick(f);
                }
              }}
            />
            <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{picked ? `${picked.name} · checking, uses 1 check` : "STEP, STL or IGES · up to 200 MB · uses 1 check"}</span>
          </div>
        </div>
      </aside>
    </main>
  );
}
