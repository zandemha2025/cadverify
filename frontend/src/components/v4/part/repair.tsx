"use client";

/**
 * O14: repair a part that isn't a closed solid, and say exactly how it ended.
 * A part whose file the organization keeps is repaired from that copy
 * (POST /parts/{hash}/repair): nothing is uploaded again, no check is used, and
 * the repaired copy is saved as a new part linked to this one. Without a kept
 * file, the file in this browser is repaired (POST /validate/repair).
 */
import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { API_BASE } from "@/lib/api-base";
import { isKeptJob, keptToastLine } from "./kept-job-model";
import { waitForKeptJob } from "./kept-job";
import type { RepairResult, StoredRepairResult } from "@/lib/api";
import { apiProblemDetail, apiRecoveryMessage } from "@/lib/api-recovery";
import { CAD_LIMIT } from "@/lib/upload-limit";
import { CAD_ACCEPT } from "../pending-file";
import { R } from "../routes";
import { dimsText, plural } from "./model";
import { openEdges } from "./cant-read";
import { SheetTop, type FigItem } from "./sheet-bits";
import type { CheckSession } from "./store";
import type { ViewerController } from "./viewer";
import { nextSteps, openingsNote, outcomeOf, repairHead, repairRefusal, signedPct, type NextStep } from "../fix/repair-outcome";
import { fixedFileUrl, loadServerOptions } from "../fix/server";
import "./part.css";

const PartViewer = dynamic(() => import("./viewer"), { ssr: false });

/** A repaired copy that is already a saved part (the kept-file repair). */
export interface SavedCopy {
  hash: string;
  filename: string;
}

/** What one repair request came back with (shared with the find-and-fix dialog). */
export type RepairOutcome =
  | { s: "error"; msg: string; limit?: boolean; notKept?: boolean }
  | { s: "failed"; r: RepairResult }
  | { s: "fixed"; r: RepairResult; file: File; url: string; saved: SavedCopy | null };

// worker: the stage, when the kept file is large enough to be repaired on ScaleCAD's worker.
type Out = { s: "ready" } | { s: "running"; worker?: string } | RepairOutcome;

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function refusal(res: Response): Promise<RepairOutcome> {
  const body = await res.json().catch(() => null);
  const fallback = apiProblemDetail(body) ?? apiRecoveryMessage({ status: res.status, payload: body, resource: "repair" });
  const r = repairRefusal(res.status, body, fallback);
  return { s: "error", msg: r.msg, limit: r.limit, notKept: res.status === 404 };
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
  if (!res.ok) {
    const out = await refusal(res);
    return out.s === "error" ? { ...out, notKept: false } : out;
  }
  const r = (await res.json().catch(() => null)) as RepairResult | null;
  if (!r) return { s: "error", msg: "The repair answered with nothing readable. Try again." };
  if (!r.repair_applied || !r.repaired_file_b64) return { s: "failed", r };
  const name = r.repair_verification?.download_filename ?? `${file.name.replace(/\.[^.]+$/, "")}-repaired.stl`;
  const bytes = b64ToBytes(r.repaired_file_b64);
  const fixed = new File([bytes.buffer as ArrayBuffer], name, { type: "model/stl" });
  return { s: "fixed", r, file: fixed, url: URL.createObjectURL(fixed), saved: null };
}

/**
 * POST /parts/{hash}/repair: the same repair on the organization's kept copy of
 * the file. No upload and no check; a repaired copy is saved as a new part.
 * `notKept` on the result: the file isn't kept, so the caller can fall back to
 * the file in this browser.
 */
export async function runStoredRepair(key: string, opts: { qty?: number[]; materialClass?: string | null; onWorker?: (stage: string) => void } = {}): Promise<RepairOutcome> {
  const q = new URLSearchParams();
  if (opts.qty?.length) q.set("qty", opts.qty.join(","));
  if (opts.materialClass) q.set("material_class", opts.materialClass);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/parts/${encodeURIComponent(key)}/repair${q.toString() ? `?${q}` : ""}`, { method: "POST" });
  } catch {
    return { s: "error", msg: "The repair couldn't reach the server. Try again." };
  }
  if (!res.ok) return refusal(res);
  let r = (await res.json().catch(() => null)) as StoredRepairResult | null;
  // A large kept file is repaired on ScaleCAD's worker: the answer is the job (202), followed to its end.
  if (res.status === 202 && isKeptJob(r)) {
    try {
      r = await waitForKeptJob<StoredRepairResult>(r, opts.onWorker);
    } catch (e) {
      return { s: "error", msg: e instanceof Error ? e.message : "The repair didn't finish on the worker. Nothing was charged." };
    }
  }
  if (!r) return { s: "error", msg: "The repair answered with nothing readable. Try again." };
  if (!r.repair_applied || !r.repaired) return { s: "failed", r };
  const name = r.repaired.filename;
  let blob: Blob | null = null;
  if (r.repaired_file_b64) blob = new Blob([b64ToBytes(r.repaired_file_b64).buffer as ArrayBuffer], { type: "model/stl" });
  else blob = await fetch(fixedFileUrl(r.repaired.mesh_hash), { cache: "no-store" }).then((x) => (x.ok ? x.blob() : null)).catch(() => null);
  const file = new File(blob ? [blob] : [], name, { type: "model/stl" });
  return { s: "fixed", r, file, url: blob ? URL.createObjectURL(file) : "", saved: { hash: r.repaired.mesh_hash, filename: name } };
}

/** The kept file first; the file in this browser when the organization doesn't keep it. */
export async function repairPart(key: string | null, file: File | null, opts: { qty?: number[]; materialClass?: string | null; onWorker?: (stage: string) => void } = {}): Promise<RepairOutcome> {
  if (key) {
    const out = await runStoredRepair(key, opts);
    if (!(out.s === "error" && out.notKept && file)) return out;
  }
  if (file) return runRepair(file);
  return { s: "error", msg: "This part's file isn't kept with the record, so ScaleCAD can't repair it from here. Choose the file to repair it.", notKept: true };
}

/** Why a repair didn't close the shell, in the engine's words. */
export function repairFailedReason(r: RepairResult): string {
  return r.summary ?? (r.repair_details as { reason?: string }).reason ?? r.repair_details.error ?? "Repair did not produce a watertight solid.";
}

/** Can the server sew this part's faces (GET /parts/{hash}/fixes offers heal_brep)? */
export function useCanHeal(key: string | null, ask: boolean): boolean {
  const [can, setCan] = React.useState(false);
  React.useEffect(() => {
    if (!key || !ask) return;
    let live = true;
    void loadServerOptions(key).then((o) => {
      if (live) setCan(!!o?.findings.some((f) => f.fix === "heal_brep" && f.can_fix));
    });
    return () => {
      live = false;
    };
  }, [key, ask]);
  return can;
}

function mm3(x: number | null | undefined): string {
  return x != null ? `${Math.round(x).toLocaleString("en-US")} mm³` : "—";
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
    const onWorker = (stage: string) => setOut((cur) => (cur.s === "running" ? { s: "running", worker: stage } : cur));
    setOut(await repairPart(session.key, session.file, { materialClass: session.materialClass, onWorker }));
  };

  const fixed = out.s === "fixed" ? out : null;
  const result = out.s === "fixed" || out.s === "failed" ? out.r : null;
  const kind = result ? outcomeOf(result) : null;
  const d = result?.repair_details;
  const pct = d?.volume_change_pct ?? null;
  const head = kind ? repairHead(kind, pct) : null;
  const opened = kind ? openingsNote(kind, d?.openings) : null;
  const brep = /\.(step|stp|iges|igs)$/i.test(session.file.name);
  const canHeal = useCanHeal(session.key, out.s === "failed" || kind === "closed_changed");
  const next: NextStep[] = kind ? nextSteps(kind, d?.openings, { brep, canHeal }) : [];
  const stored = result && "prices" in result ? (result as StoredRepairResult) : null;
  const cheapest = stored?.prices?.after?.find((x) => x.unit_cost_usd != null) ?? null;
  const rv = fixed?.r.repaired_analysis;
  const canMake = rv ? rv.process_scores.filter((s) => s.verdict === "pass" || s.verdict === "issues").length : null;
  const figs: FigItem[] = fixed
    ? [
        { k: "Volume change", v: pct != null ? signedPct(pct) : "unknown", s: kind === "repaired" ? "closing gaps only" : "compare with your design", tone: kind === "repaired" ? "ok" : "warn" },
        ...(canMake != null && rv ? [{ k: "Processes", v: `${canMake} of ${rv.process_scores.length}`, s: "was 0: not a solid", tone: "ok" as FigItem["tone"] }] : []),
        cheapest ? { k: `Cheapest at ${cheapest.qty.toLocaleString("en-US")}`, v: `$${cheapest.unit_cost_usd!.toFixed(2)}`, s: "the repaired copy · not a quote" } : { k: "Verdict", v: fixed.r.repair_verification?.repaired_verdict ?? "—", s: `was ${fixed.r.repair_verification?.original_verdict ?? "—"}` },
      ]
    : [
        { k: "Open edges", v: (d?.openings?.open_edges ?? edges)?.toLocaleString("en-US") ?? "—", s: "not a closed solid", tone: "bad" },
        { k: "Processes", v: `0 of ${v?.process_scores.length ?? 21}`, s: "need a closed solid" },
      ];
  const title = head ? head.title : "Not a closed solid";
  const meta = fixed ? (fixed.saved ? `Saved as a new part, linked to ${session.file.name} · no check used` : "Not saved yet · no check used") : `${session.file.name} · nothing priced`;
  const nextBtn = (n: NextStep) =>
    n.kind === "heal" && session.key ? (
      <Link className="btn sm ink" href={`${R.part(session.key)}?problem=open`}>
        {n.label}
      </Link>
    ) : n.kind === "cad" ? (
      <button className="btn sm" type="button" onClick={onBack}>
        {n.label}
      </button>
    ) : n.kind === "upload" ? (
      <button className="btn sm" type="button" onClick={() => input.current?.click()}>
        {n.label}
      </button>
    ) : null;
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
        {!fixed || !fixed.url ? (
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
                <b>Your file</b>open shell{d?.original_volume_mm3 != null ? ` · ${mm3(d.original_volume_mm3)} with its openings capped flat` : ""}
              </figcaption>
            </figure>
            <figure style={{ margin: 0, display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
              <div style={{ position: "relative", width: "100%", maxWidth: 400, aspectRatio: "1" }} role="img" aria-label="The repaired copy">
                <PartViewer url={fixed.url} kind="stl" highlight={null} xray={false} controllerRef={c2} onState={setV} />
              </div>
              <figcaption className="tag" style={{ position: "static", alignItems: "center", borderColor: kind === "closed_changed" ? "#E9C46A" : undefined }}>
                <b>Repaired copy</b>closed{d?.repaired_volume_mm3 != null ? ` · ${mm3(d.repaired_volume_mm3)}` : ""}
              </figcaption>
            </figure>
          </div>
        )}
      </section>
      <aside className="sheet" aria-label="What's wrong and what to do">
        <SheetTop title={title} meta={meta} figs={figs} />
        <div className="scroll" aria-live="polite">
          {head ? (
            <div className="note swap" role={kind === "not_repaired" || kind === "partly" ? "alert" : "status"} style={{ marginTop: 8, borderColor: head.tone === "c-bad" ? "#F5D5D0" : head.tone === "c-warn" ? "#E9C46A" : undefined }}>
              <b>
                <span className={`chip ${head.tone}`} style={{ marginRight: 6 }}>
                  <i />
                  {head.chip}
                </span>
              </b>
              <span>{result ? repairFailedReason(result) : ""}</span>
              {opened ? (
                <span style={{ color: "var(--ink2)", fontSize: 12.5 }}>
                  <b style={{ fontWeight: 600 }}>What was open:</b> {opened}
                </span>
              ) : null}
            </div>
          ) : (
            <div className="note" style={{ marginTop: 8 }}>
              <b>Not watertight</b>
              <span>{v?.universal_issues.find((i) => i.code === "NON_WATERTIGHT")?.message ?? "Every process needs a closed solid."}</span>
            </div>
          )}
          {out.s === "ready" || out.s === "running" || out.s === "error" ? (
            <div className="swap">
              <div className="gh">
                <span>Repair it here</span>
                <span>no check used</span>
              </div>
              <div className="note" style={{ marginTop: 2 }}>
                <span>Joins faces that touch, closes the gaps on a copy, then checks the copy the same way as an upload. Your file stays as it is; any change to the shape is reported.</span>
                <span>
                  <button className="btn ink sm" type="button" onClick={() => void run()} disabled={out.s === "running"}>
                    {out.s === "running" ? "Repairing a copy…" : out.s === "error" && !out.limit ? "Try again" : "Repair a copy"}
                  </button>
                </span>
                {out.s === "running" && out.worker ? (
                  <span role="status" style={{ color: "var(--ink3)", fontSize: 13 }}>
                    {`Repairing ${keptToastLine(out.worker)}. It goes on if you leave this page; the work bar shows it.`}
                  </span>
                ) : null}
                {out.s === "error" ? (
                  <span role="alert" style={{ color: "var(--bad)", fontSize: 13 }}>
                    {out.msg}
                    {out.limit ? (
                      <>
                        {" "}
                        <Link href={R.billing}>Plans</Link>
                      </>
                    ) : null}
                  </span>
                ) : null}
              </div>
            </div>
          ) : null}
          {fixed ? (
            <div className="swap">
              {kind === "closed_changed" && d?.volume_warning ? (
                <div className="note" style={{ marginTop: 10, borderColor: "#E9C46A" }}>
                  <b>The shape changed</b>
                  <span>{d.volume_warning}</span>
                </div>
              ) : null}
              <div className="gh">
                <span>Before and after</span>
                <span />
              </div>
              <div className="lines">
                {[
                  ["Closed solid", "no", rv?.geometry.is_watertight ? "yes" : "—"],
                  ...(d?.openings ? [["Open edges", d.openings.open_edges.toLocaleString("en-US"), "0"]] : []),
                  ["Faces", d?.original_faces?.toLocaleString("en-US") ?? "—", d?.repaired_faces?.toLocaleString("en-US") ?? "—"],
                  ["Volume", d?.original_volume_mm3 != null ? `${mm3(d.original_volume_mm3)} capped` : "—", `${mm3(d?.repaired_volume_mm3)}${pct != null ? ` · ${signedPct(pct)}` : ""}`],
                  ["Verdict", fixed.r.repair_verification?.original_verdict ?? "—", fixed.r.repair_verification?.repaired_verdict ?? "—"],
                  ["Repair", "", [d?.welded_edges ? `welded ${d.welded_edges.toLocaleString("en-US")} edges` : null, d?.tier ? `mesh repair, ${d.tier}` : "mesh repair", d?.duration_ms != null ? `${(d.duration_ms / 1000).toFixed(1)} s` : null].filter(Boolean).join(" · ")],
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
                  SHA-256 your file {fixed.r.repair_verification.original_sha256.slice(0, 8)}… · repaired copy {fixed.r.repair_verification.repaired_sha256.slice(0, 8)}…
                </p>
              ) : null}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", padding: "10px 12px 0" }}>
                {fixed.saved ? (
                  <Link className="btn ink sm" href={R.part(fixed.saved.hash)}>
                    Open the repaired copy
                  </Link>
                ) : (
                  <button className="btn ink sm" type="button" onClick={() => onPick(fixed.file)}>
                    Check the repaired file
                  </button>
                )}
                {fixed.url ? (
                  <a className="btn sm" href={fixed.url} download={fixed.file.name}>
                    Download the repaired STL
                  </a>
                ) : fixed.saved ? (
                  <a className="btn sm" href={fixedFileUrl(fixed.saved.hash)} download={fixed.saved.filename}>
                    Download the repaired STL
                  </a>
                ) : null}
              </div>
              <p style={{ margin: "6px 12px 0", color: "var(--ink3)", fontSize: 12.5 }}>
                {fixed.saved ? `${fixed.saved.filename} is in Parts, linked to your file. Opening it doesn’t use a check.` : "Checking it saves it as a new part, separate from this file · uses 1 check."}
              </p>
            </div>
          ) : null}
          {next.length ? (
            <>
              <div className="gh" style={{ marginTop: 10 }}>
                <span>{kind === "closed_changed" ? "To keep the design’s shape" : "What you can do next"}</span>
                <span />
              </div>
              <div className="lines">
                {next.map((n, i) => (
                  <div key={n.kind} className="ln" style={{ gridTemplateColumns: "minmax(0,1fr) auto", alignItems: "center" }}>
                    <span>
                      <b style={{ fontWeight: 600 }}>
                        {i + 1}. {n.label}
                      </b>
                      <small style={{ display: "block", color: "var(--ink3)" }}>{n.why}</small>
                    </span>
                    {nextBtn(n)}
                  </div>
                ))}
              </div>
            </>
          ) : null}
          {!kind ? (
            <>
              <div className="gh" style={{ marginTop: 10 }}>
                <span>Fix it in CAD</span>
                <span>
                  <button className="btn sm ghost" type="button" onClick={onBack} style={{ height: 24 }}>
                    Steps for your CAD tool
                  </button>
                </span>
              </div>
              <p style={{ margin: "0 12px", color: "var(--ink2)", fontSize: 13 }}>Heal or close the gap, then export the solid body, not surfaces.</p>
            </>
          ) : null}
          {!kind || next.some((n) => n.kind === "upload") ? (
            <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "10px 12px 0", flexWrap: "wrap" }}>
              {!kind ? (
                <button className="btn sm" type="button" onClick={() => input.current?.click()}>
                  Upload a fixed file
                </button>
              ) : null}
              <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{picked ? `${picked.name} · checking, uses 1 check` : `A fixed file: STEP, STL or IGES · ${CAD_LIMIT} · uses 1 check`}</span>
            </div>
          ) : null}
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
        </div>
      </aside>
    </main>
  );
}
