"use client";
import dynamic from "next/dynamic";
import { useCallback, useRef, useState } from "react";
import { measureContextFit, type FitResult } from "@/lib/verify/context-fit";
const Viewer = dynamic(() => import("./context-fit-viewer"), { ssr: false });

type Role = "part" | "context";
export function ContextFitPanel() {
  const [files, setFiles] = useState<Record<Role, File | null>>({ part: null, context: null });
  const [result, setResult] = useState<FitResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seating, setSeating] = useState<"shared_frame"|"auto">("shared_frame");
  const [nudge, setNudge] = useState<[number,number,number]>([0,0,0]);
  const [hideContext, setHideContext] = useState(false);
  const [selectedIssue, setSelectedIssue] = useState<"collision"|"clearance"|null>(null);
  const runId = useRef(0);
  const clearStale = useCallback(() => { ++runId.current; setResult(null); setSelectedIssue(null); setError(null); }, []);
  const pick = (role: Role, file: File | null) => { clearStale(); setFiles(old => ({ ...old, [role]: file })); };
  const run = async () => {
    if (!files.part || !files.context) return;
    const id = ++runId.current; setRunning(true); setResult(null); setError(null);
    try { const next = await measureContextFit(files.part, files.context, seating, nudge); if (id === runId.current) { setResult(next); setSelectedIssue(null); } }
    catch (e) { if (id === runId.current) setError(e instanceof Error ? e.message : "Fit check failed"); }
    finally { if (id === runId.current) setRunning(false); }
  };
  const swap = () => { clearStale(); setFiles({ part: files.context, context: files.part }); };
  const nudged = nudge.some((value) => value !== 0);
  const seatingLine = result
    ? nudged
      ? result.seating.accepted && result.seating.method !== "shared_frame"
        ? "Seated automatically, then set by you."
        : "Position set by you."
      : result.seating.method === "shared_frame"
        ? "Seated using the files' shared CAD frame."
        : result.seating.accepted
          ? "Seated automatically - check the fit."
          : "We couldn't seat this with confidence. Shared frame retained - use nudge to adjust."
    : "Results withheld until this pair is checked.";
  return <section className="grid min-h-0 flex-1 gap-4 p-4 lg:grid-cols-[minmax(0,3fr)_minmax(320px,2fr)]" data-testid="context-fit-panel">
    <div className="flex min-h-[360px] flex-col overflow-hidden rounded-xl border bg-card">
      <div className="flex flex-wrap items-center gap-2 border-b p-3 text-xs"><b>Solid: your part</b><span>Ghost: assembly</span><button onClick={() => setHideContext(v=>!v)}>{hideContext?"Show assembly":"Hide assembly"}</button></div>
      <div className="relative min-h-[300px] flex-1">{files.part && files.context ? <Viewer part={files.part} context={files.context} result={result} hideContext={hideContext} selectedIssue={selectedIssue}/> : <div className="grid h-full place-items-center text-sm text-muted-foreground">Add both files to see them in context.</div>}
        {result && selectedIssue && <div data-testid="context-fit-docked-callout" className="absolute left-2 right-2 top-2 z-20 rounded border bg-card/95 p-3 text-xs shadow-lg backdrop-blur-sm sm:left-auto sm:w-72">
          {selectedIssue === "collision" ? <><b>◆ Collision</b><p>{result.collision.intersects ? `${result.collision.volume_mm3.toFixed(3)} mm³ measured overlap. · MEASURED` : "No measured overlap. · MEASURED"}</p><p>{result.collision.intersects ? "Move the part or change the overlapping geometry, then check this pair again." : "No collision action is needed for this position."}</p></> : <><b>△ Closest measured gap</b><p>{result.collision.intersects ? "0.000 mm - the parts overlap. · MEASURED" : `${result.clearance.closest_sampled_gap_mm.toFixed(3)} mm · MEASURED`}</p><p>{result.collision.intersects ? "Resolve the overlap before judging clearance." : "Compare this measured gap with your declared assembly requirement."}</p></>}
        </div>}
      </div>
      <p className="border-t px-3 py-2 text-xs">{seatingLine}</p>
    </div>
    <div className="min-h-0 space-y-3 overflow-y-auto">
      {(["part","context"] as Role[]).map(role => <label key={role} className="block rounded-xl border bg-card p-3"><b>{role === "part" ? "Your part" : "The assembly it fits into"}</b><input className="mt-2 block w-full text-xs" type="file" accept=".stl,.obj,.3mf,.step,.stp,.iges,.igs" onChange={e=>pick(role,e.target.files?.[0]??null)}/><span className="mt-1 block break-all text-xs text-muted-foreground">{files[role]?.name ?? "No file selected"}</span>{files[role] && <span className="mt-1 block text-[11px] text-muted-foreground">{files[role]!.name.split(".").pop()?.toUpperCase()} · face count measured after upload</span>}</label>)}
      <button className="min-h-11 rounded border px-3" onClick={swap}>Switch part and context</button>
      <div className="rounded-xl border bg-card p-3"><label className="text-xs">Seating <select value={seating} onChange={e=>{clearStale();setSeating(e.target.value as typeof seating)}}><option value="shared_frame">Shared CAD frame</option><option value="auto">Automatic, verify fit</option></select></label><div className="mt-2 grid grid-cols-3 gap-2">{nudge.map((v,i)=><label key={i} className="text-[11px] text-muted-foreground">{`${"XYZ"[i]} nudge (mm)`}<input className="mt-1 w-full text-foreground" aria-label={`${"XYZ"[i]} nudge mm`} type="number" step="0.1" value={v} onChange={e=>{const next=[...nudge] as [number,number,number];next[i]=Number(e.target.value);clearStale();setNudge(next)}}/></label>)}</div></div>
      <button className="min-h-11 w-full rounded bg-foreground px-4 text-background disabled:opacity-50" disabled={!files.part||!files.context||running} onClick={run}>{running?"Measuring this pair…":"Check fit in context"}</button>
      {error && <p role="alert" className="rounded border border-red-300 p-3 text-sm text-red-800">{error}</p>}
      {result && <div className="space-y-2" data-testid="context-fit-results">
        {!result.seating.accepted && <div role="status" className="rounded border border-amber-300 bg-amber-50 p-3 text-sm"><b>Seating uncertain</b><p>We couldn't seat this with confidence. Preview the shared-frame position or set the position with XYZ nudge.</p></div>}
        <p className="text-xs text-muted-foreground">2 measured checks. Tap one to see where.</p>
        <button type="button" className={`w-full rounded-xl border bg-card p-3 text-left ${selectedIssue === "collision" ? "ring-2 ring-red-500" : ""}`} onClick={() => setSelectedIssue(selectedIssue === "collision" ? null : "collision")}><b>◆ Collision</b><p>{result.collision.intersects ? `${result.collision.volume_mm3.toFixed(3)} mm³ measured overlap. · MEASURED` : "No measured overlap."}</p>{result.collision.intersects && <p className="text-xs">Move the part or change the overlapping geometry, then check this pair again.</p>}{result.collision.region?.render_geometry.available === false && <p className="text-xs text-muted-foreground">Intersection shell unavailable; centroid anchor only. No substitute volume rendered.</p>}</button>
        <button type="button" className={`w-full rounded-xl border bg-card p-3 text-left ${selectedIssue === "clearance" ? "ring-2 ring-amber-500" : ""}`} onClick={() => setSelectedIssue(selectedIssue === "clearance" ? null : "clearance")}><b>△ Closest measured gap</b><p>{result.collision.intersects ? "0.000 mm - the parts overlap." : `${result.clearance.closest_sampled_gap_mm.toFixed(3)} mm · MEASURED`}</p><p className="text-xs">{result.collision.intersects ? "Resolve the overlap before judging clearance." : "Compare this measured gap with your declared assembly requirement."}</p><p className="text-xs text-muted-foreground">Sampled on submitted tessellation. Not an analytic tolerance result.</p></button>
        <p className="text-xs text-muted-foreground">Pair measured in {result.timing_ms.pair_total.toFixed(1)} ms. · MEASURED</p>
        <div className="rounded border bg-muted/40 p-2 text-[11px] text-muted-foreground"><b>Provenance</b>{result.limits.map((limit) => <p key={limit}>{limit}</p>)}</div>
      </div>}
    </div>
  </section>;
}
