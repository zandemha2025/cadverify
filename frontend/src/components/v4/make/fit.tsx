"use client";

/**
 * Fit in context (board F2): your part and the assembly it goes into, seated in
 * their shared CAD frame or automatically, nudged in X/Y/Z, then measured on the
 * server: the exact collision volume and the closest sampled gap, with the
 * assembly as a see-through ghost and the measured overlap drawn in 3D.
 *
 * Access comes first. GET /validate/fit/capability answers from the plan, role
 * and server setting before any file is read: other plans see the pilot gate
 * (board X5), a server with the setting off says so, and the two preview meshes
 * (each a check for free plans) are fetched only once the tool can run.
 */
import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/ui/auth-provider";
import { canMutateWorkspace } from "@/lib/role-capabilities";
import { API_BASE } from "@/lib/api-base";
import { measureContextFit, type FitResult, type FitUnits } from "@/lib/verify/context-fit";
import { fetchPreviewMesh, type PreviewMesh } from "@/lib/verify/preview-mesh";
import { R } from "../routes";
import { Chip, Content, KV, Sheet, cx } from "../ui";
import { LOCK, MakeHead, MakeWorld, PILOT_INCLUDES, PilotPlanCard, errorText, isPaidAccessError, usePlan } from "./head";
import { Turntable, type StageLayer, type StageMarker, type StageState } from "./turntable";
import {
  FIT_ACCEPT,
  bandText,
  callout,
  canPaintFaces,
  figures,
  fileSub,
  goHint,
  isFitFile,
  needsUnits,
  nudgeInvalid,
  nudgeValues,
  resolveAccess,
  seatMeta,
  seatingLine,
  translation,
  type CapabilityAnswer,
  type FitCapability,
  type FitView,
  type Nudge,
  type Seating,
} from "./fit-model";

type Role = "part" | "context";
type Pv = { url: string; decimated: boolean; faces: number | null; revoke: () => void };

async function getCapability(signal: AbortSignal): Promise<CapabilityAnswer> {
  const res = await fetch(`${API_BASE}/validate/fit/capability`, { cache: "no-store", signal });
  if (res.status === 404) return { kind: "missing" };
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const d = (body?.detail ?? body) as { message?: string } | string | null;
    const message = typeof d === "string" ? d : d?.message;
    return { kind: "error", message: message || `The availability check didn’t finish (${res.status}).` };
  }
  return { kind: "ok", cap: body as FitCapability };
}

export function FitScreen() {
  const { user } = useAuth();
  const canMutate = canMutateWorkspace(user?.role);
  const plan = usePlan();
  const [answer, setAnswer] = React.useState<CapabilityAnswer>({ kind: "loading" });
  const [capTry, setCapTry] = React.useState(0);
  React.useEffect(() => {
    const ctl = new AbortController();
    setAnswer({ kind: "loading" });
    getCapability(ctl.signal)
      .then(setAnswer)
      .catch((e) => {
        if (!ctl.signal.aborted) setAnswer({ kind: "error", message: errorText(e, "The availability check didn’t finish.") });
      });
    return () => ctl.abort();
  }, [capTry]);
  const [gated, setGated] = React.useState(false);
  const access = gated ? "gate" : resolveAccess(answer, plan, canMutate);

  if (access === "gate") return <FitPilotGate />;
  return <FitTool access={access} retryCapability={() => setCapTry((n) => n + 1)} capError={answer.kind === "error" ? answer.message : null} onGate={() => setGated(true)} />;
}

function FitTool({
  access,
  retryCapability,
  capError,
  onGate,
}: {
  access: "loading" | "off" | "viewer" | "on" | "error";
  retryCapability: () => void;
  capError: string | null;
  onGate: () => void;
}) {
  const usable = access === "on";
  const [files, setFiles] = React.useState<Record<Role, File | null>>({ part: null, context: null });
  const [units, setUnits] = React.useState<FitUnits>({ part: "mm", context: "mm" });
  const [seating, setSeating] = React.useState<Seating>("shared_frame");
  const [nudge, setNudge] = React.useState<Nudge>(["0", "0", "0"]);
  const [result, setResult] = React.useState<FitResult | null>(null);
  const [changed, setChanged] = React.useState(false);
  const [running, setRunning] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [view, setView] = React.useState<FitView>("col");
  const [hide, setHide] = React.useState(false);
  const [pv, setPv] = React.useState<{ part: Pv; context: Pv } | null>(null);
  const [pvErr, setPvErr] = React.useState<string | null>(null);
  const [pvTry, setPvTry] = React.useState(0);
  const [stage, setStage] = React.useState<StageState>("loading");
  const run = React.useRef(0);

  const bad = nudgeInvalid(nudge);
  const nudgeBad = bad.some(Boolean);
  const both = !!files.part && !!files.context;
  const supported = both && isFitFile(files.part!.name) && isFitFile(files.context!.name);

  const clear = () => {
    ++run.current;
    setRunning(false);
    if (result) setChanged(true);
    setResult(null);
    setErr(null);
  };

  // Previews only once the tool can run, both files are in and their kinds are supported.
  React.useEffect(() => {
    setPv(null);
    setPvErr(null);
    if (!usable || !supported) return;
    let live = true;
    const owned: Pv[] = [];
    const load = async (file: File, u: "mm" | "inch"): Promise<Pv | null> => {
      const p: PreviewMesh | null = await fetchPreviewMesh(file, { units: u });
      if (!p) return null;
      const v = { url: p.url, decimated: p.decimated, faces: p.originalFaces, revoke: p.revoke };
      if (!live) v.revoke();
      else owned.push(v);
      return v;
    };
    Promise.all([load(files.part!, units.part), load(files.context!, units.context)])
      .then(([a, b]) => {
        if (!live) return;
        if (a && b) setPv({ part: a, context: b });
        else setPvErr("Preview unavailable");
      })
      .catch((e) => live && setPvErr(errorText(e, "Preview unavailable")));
    return () => {
      live = false;
      owned.forEach((v) => v.revoke());
    };
  }, [usable, supported, files.part, files.context, units.part, units.context, pvTry]);

  const pick = (role: Role, file: File | null) => {
    clear();
    setFiles((f) => ({ ...f, [role]: file }));
    setUnits((u) => ({ ...u, [role]: "mm" }));
  };
  const swap = () => {
    clear();
    setFiles((f) => ({ part: f.context, context: f.part }));
    setUnits((u) => ({ part: u.context, context: u.part }));
  };

  const check = async () => {
    if (!usable || !both || nudgeBad || running) return;
    const id = ++run.current;
    setRunning(true);
    setErr(null);
    setResult(null);
    try {
      const r = await measureContextFit(files.part!, files.context!, seating, nudgeValues(nudge), units);
      if (id !== run.current) return;
      setResult(r);
      setChanged(false);
      setView(r.collision.intersects ? "col" : "gap");
    } catch (e) {
      if (id !== run.current) return;
      if (isPaidAccessError(e)) onGate();
      setErr(errorText(e, "The fit check didn’t finish."));
    } finally {
      if (id === run.current) setRunning(false);
    }
  };

  /* ---------- stage layers ---------- */
  const paint = canPaintFaces(pv?.part ?? null);
  const layers: StageLayer[] = [];
  const markers: StageMarker[] = [];
  if (pv && usable) {
    const tz = result?.clearance.tight_zone;
    layers.push({
      key: "part",
      source: { kind: "glb-url", url: pv.part.url },
      look: "solid",
      paint: result && view === "gap" && paint && tz && tz.part_a_faces.length ? { faces: tz.part_a_faces, color: "#2E6BE6" } : null,
    });
    if (!hide)
      layers.push({
        key: "context",
        source: { kind: "glb-url", url: pv.context.url },
        look: "ghost",
        // Before a check the ghost follows the shared frame plus your nudge, the same transform the server applies.
        matrix: result ? result.seating.transform : seating === "shared_frame" && !nudgeBad ? translation(nudgeValues(nudge)) : null,
      });
    const region = result?.collision.region;
    if (result && view === "col" && result.collision.intersects && region) {
      const g = region.render_geometry;
      if (g.available && g.data) layers.push({ key: "overlap", source: { kind: "glb-b64", data: g.data }, look: "overlap", frame: false });
      else markers.push({ key: "overlap-c", at: region.region_center, color: "#D92D20" });
    }
    if (result && view === "gap" && tz?.region_center) markers.push({ key: "gap-c", at: tz.region_center, color: "#2E6BE6" });
  }
  const frameKey = pv ? `${pv.part.url}|${hide ? "" : pv.context.url}|${result ? JSON.stringify(result.seating.transform) : "pre"}` : "none";

  const fg = figures(result);
  const co = result ? callout(result, view, paint) : null;
  const partName = files.part?.name ?? null;
  const ctxName = files.context?.name ?? null;
  const objLabel = `Your part solid${hide ? "" : ", the assembly see-through"}${result ? (view === "col" ? ", the measured overlap in red" : ", the closest-gap zone in blue") : ""}. Drag, or use the arrow keys, to turn it.`;

  let overlay: React.ReactNode = null;
  if (usable && !both)
    overlay = (
      <span className="gen plain">
        <b>Add your part and the assembly it goes into</b>
        <span>STL, OBJ, 3MF, STEP or IGES. Both are previewed once added.</span>
      </span>
    );
  else if (usable && both && !supported)
    overlay = (
      <span className="gen plain">
        <b>Choose STL, OBJ, 3MF, STEP or IGES files</b>
        <span>The pair preview needs two supported files.</span>
      </span>
    );
  else if (pvErr || stage === "failed")
    overlay = (
      <span className="gen wait">
        <b>Couldn’t load the two previews</b>
        <span>{pvErr && /check|allowance|limit/i.test(pvErr) ? pvErr : "Measured results are unaffected."}</span>
      </span>
    );
  else if (usable && both && !pv)
    overlay = (
      <span className="gen plain">
        <span className="spin" aria-hidden="true" />
        <span>Preparing the submitted geometry…</span>
      </span>
    );

  return (
    <MakeWorld label="Fit in context">
      <MakeHead
        title="Fit in context"
        meta={[partName && ctxName ? `${partName} in ${ctxName}` : "Your part in its assembly", seatMeta(seating), "Pilot plan"]}
        tools={
          <button className="btn sm" type="button" aria-pressed={hide} onClick={() => setHide((h) => !h)} disabled={!usable}>
            {hide ? "Show assembly" : "Hide assembly"}
          </button>
        }
      />

      <div className="fstage">
        {access === "loading" ? (
          <div className="panel" role="status" style={{ flex: 1, display: "grid", placeItems: "center" }}>
            <span className="spin" aria-hidden="true" />
            <span className="sr">Checking Fit in context availability</span>
          </div>
        ) : access === "error" ? (
          <div className="panel">
            <div className="empty">
              <b>Availability check didn’t finish</b>
              <span>Nothing was uploaded. {capError}</span>
              <button className="btn sm" type="button" onClick={retryCapability}>
                Try again
              </button>
            </div>
          </div>
        ) : access === "off" ? (
          <div className="panel">
            <div className="offc">
              <Chip tone="unk">Not available on this server</Chip>
              <b>Fit in context is switched off on this server</b>
              <span>An administrator turns it on in the server settings. Until then nothing can be measured here.</span>
              <Link className="btn ink" href={R.check}>
                Check a part
              </Link>
              <small>No file has been uploaded or previewed.</small>
            </div>
          </div>
        ) : access === "viewer" ? (
          <div className="panel">
            <div className="offc">
              <Chip tone="unk">Read only for your role</Chip>
              <b>Analysts and admins check fit</b>
              <span>Ask one to run the pair, or for a role that can.</span>
            </div>
          </div>
        ) : (
          <>
            <Turntable className="fobj" label={objLabel} layers={layers} markers={markers} overlay={overlay} onState={setStage} frameKey={frameKey} />
            {pvErr || stage === "failed" ? (
              <div className="vsel">
                <button className="btn sm" type="button" onClick={() => setPvTry((n) => n + 1)}>
                  Retry preview
                </button>
              </div>
            ) : null}
            {result ? (
              <div className="vsel">
                <span className="seg" role="group" aria-label="Show on the part">
                  <button type="button" className={cx(view === "col" && "on")} aria-pressed={view === "col"} onClick={() => setView("col")}>
                    ◆ Collision
                  </button>
                  <button type="button" className={cx(view === "gap" && "on")} aria-pressed={view === "gap"} onClick={() => setView("gap")}>
                    △ Closest gap
                  </button>
                </span>
              </div>
            ) : null}
            <div className="legend">
              {result ? (
                <span>
                  <i style={{ background: view === "col" ? "#D92D20" : "#2E6BE6" }} />
                  {view === "col" ? "Overlap, measured" : `Within ${bandText(result)} mm, closest gap`}
                </span>
              ) : null}
              <span>
                <i style={{ background: "#B9BDC4" }} />
                Your part
              </span>
              {!hide ? (
                <span>
                  <i style={{ background: "rgba(154,163,174,.35)", boxShadow: "inset 0 0 0 1px #9AA3AE" }} />
                  The assembly, see-through
                </span>
              ) : null}
            </div>
            <p className="seatl">{seatingLine(result)}</p>
            {co ? (
              <div className="callout" role="status">
                <b>{co.title}</b>
                <span className="num">{co.value}</span>
                <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>{co.next}</span>
              </div>
            ) : null}
          </>
        )}
      </div>

      <Sheet label="Fit check">
        <div className="top">
          <h2 className="stitle" style={{ overflowWrap: "anywhere" }}>
            {partName ?? "Your part"}
          </h2>
          <p className="smeta">{files.part ? `Your part · ${fileSub(files.part, pv?.part.faces ?? null)}` : "Your part and the assembly it goes into"}</p>
          <div className="figs" aria-live="polite">
            <div className="fig">
              <span>Overlap volume</span>
              <b className={cx("num", fg.overlap && "bad")}>{fg.volume}</b>
              <small>mm³</small>
            </div>
            <div className="fig">
              <span>Closest gap</span>
              <b className="num">{fg.gap}</b>
              <small>mm</small>
            </div>
            <div className="fig">
              <span>Seating</span>
              <b className={cx("num", fg.seating !== "—" && "t")}>{fg.seating}</b>
            </div>
          </div>
        </div>
        <div className="scroll">
          <fieldset disabled={!usable}>
            <legend className="sr">Pair and placement</legend>
            <div className="gh">
              <span>Files</span>
              <span>STL, OBJ, 3MF, STEP, IGES</span>
            </div>
            <FileCard role="part" title="Your part" file={files.part} faces={pv?.part.faces ?? null} units={units.part} onPick={(f) => pick("part", f)} onUnits={(u) => { clear(); setUnits((x) => ({ ...x, part: u })); }} />
            <div className="swp">
              <button className="btn sm" type="button" onClick={swap}>
                Switch part and context ⇅
              </button>
            </div>
            <FileCard role="context" title="The assembly it fits into" file={files.context} faces={pv?.context.faces ?? null} units={units.context} onPick={(f) => pick("context", f)} onUnits={(u) => { clear(); setUnits((x) => ({ ...x, context: u })); }} />
            <div className="gh">
              <span>Seating</span>
              <span>mm</span>
            </div>
            <div className="seat">
              <label className="field">
                <span className="sr">Seating</span>
                <select aria-label="Seating" value={seating} onChange={(e) => { clear(); setSeating(e.target.value as Seating); }}>
                  <option value="shared_frame">Shared CAD frame</option>
                  <option value="auto">Automatic, verify fit</option>
                </select>
              </label>
            </div>
            <div className="nudge">
              {(["X", "Y", "Z"] as const).map((axis, i) => (
                <label className="field" key={axis}>
                  Nudge {axis}
                  <input
                    type="text"
                    inputMode="decimal"
                    value={nudge[i]}
                    aria-label={`${axis} nudge mm`}
                    aria-invalid={bad[i]}
                    onChange={(e) => {
                      clear();
                      const next = [...nudge] as Nudge;
                      next[i] = e.target.value;
                      setNudge(next);
                    }}
                  />
                </label>
              ))}
            </div>
            {nudgeBad ? (
              <p className="err" role="alert">
                Enter a finite number for each offset before checking fit.
              </p>
            ) : null}
            <div style={{ display: "flex", gap: 8, padding: "10px 12px", flexWrap: "wrap", alignItems: "center" }}>
              <button className="btn ink" type="button" aria-disabled={!both || nudgeBad || running} onClick={() => void check()}>
                {running ? "Measuring this pair…" : "Check fit in context"}
              </button>
              <span className="fine" style={{ margin: 0 }}>
                {usable ? goHint({ measured: !!result, running, hasFiles: both, nudgeBad, changed }) : access === "off" ? "Off on this server" : access === "viewer" ? "Read only for your role" : ""}
              </span>
            </div>
          </fieldset>
          {err ? (
            <div className="errx" role="alert">
              <b>The fit check didn’t finish</b>
              <span>{err}</span>
            </div>
          ) : null}
          {result ? <FitResults result={result} view={view} setView={setView} painted={paint} /> : (
            <div className="empty" style={{ padding: 24 }}>
              <b>Results withheld</b>
              <span>{running ? "Measuring the overlap and the closest gap." : usable ? "Check the pair to measure it with these settings." : "Nothing is measured until Fit in context is available."}</span>
            </div>
          )}
        </div>
      </Sheet>
    </MakeWorld>
  );
}

function FileCard({
  role,
  title,
  file,
  faces,
  units,
  onPick,
  onUnits,
}: {
  role: Role;
  title: string;
  file: File | null;
  faces: number | null;
  units: "mm" | "inch";
  onPick: (f: File | null) => void;
  onUnits: (u: "mm" | "inch") => void;
}) {
  return (
    <div className="fc">
      <span style={{ minWidth: 0 }}>
        <small>{title}</small>
        <b>{file?.name ?? "No file yet"}</b>
        <small>{file ? fileSub(file, faces) : "Choose a file"}</small>
      </span>
      <label className="btn sm pick">
        Choose
        <input
          type="file"
          accept={FIT_ACCEPT}
          aria-label={title}
          onChange={(e) => {
            onPick(e.target.files?.[0] ?? null);
            e.target.value = "";
          }}
        />
      </label>
      {file && needsUnits(file.name) ? (
        <label className="field">
          Source units
          <select aria-label={role === "part" ? "Your part source units" : "Assembly source units"} value={units} onChange={(e) => onUnits(e.target.value as "mm" | "inch")}>
            <option value="mm">Millimeters (mm)</option>
            <option value="inch">Inches (in)</option>
          </select>
        </label>
      ) : file ? (
        <small className="span">Units read from the CAD file</small>
      ) : null}
    </div>
  );
}

function FitResults({ result, view, setView, painted }: { result: FitResult; view: FitView; setView: (v: FitView) => void; painted: boolean }) {
  const overlap = result.collision.intersects;
  const tz = result.clearance.tight_zone;
  return (
    <div className="swap">
      {!result.seating.accepted ? (
        <div className="note" role="status">
          <b>Seating uncertain</b>
          <span>Couldn’t seat this with confidence. The shared-frame position was kept; set the position with the XYZ nudge.</span>
        </div>
      ) : null}
      <div className="gh">
        <span>2 measured checks</span>
        <span>Tap one to see where</span>
      </div>
      <div className="chk2">
        <button type="button" className={cx("ck", view === "col" && "on")} aria-pressed={view === "col"} onClick={() => setView("col")}>
          <span className="h">◆ Collision</span>
          <b className={cx("num", overlap && "bad")}>{figures(result).volume} mm³</b>
          {overlap ? "Overlap measured" : "No measured overlap"}
        </button>
        <button type="button" className={cx("ck", view === "gap" && "on")} aria-pressed={view === "gap"} onClick={() => setView("gap")}>
          <span className="h">△ Closest measured gap</span>
          <b className="num">{figures(result).gap} mm</b>
          {painted && tz.part_a_faces.length ? `Within ${bandText(result)} mm, shown in blue` : "Sampled on the submitted triangles"}
        </button>
      </div>
      <div className="gh">
        <span>Finding</span>
        <span />
      </div>
      <p style={{ margin: "0 12px 10px", color: "var(--ink2)", fontSize: 13.5 }}>
        {overlap
          ? "Move the part or change the overlapping geometry, then check this pair again."
          : "No measured overlap. Compare the closest gap with your assembly’s clearance requirement."}
      </p>
      <div className="gh">
        <span>Method</span>
        <span>Measured</span>
      </div>
      <KV
        rows={[
          ["Overlap", "Exact mesh intersection"],
          ["Clearance", "Sampled, both directions"],
          ["Tolerance band", `${bandText(result)} mm`],
          ["Pair measured in", `${Math.round(result.timing_ms.pair_total).toLocaleString("en-US")} ms`],
        ]}
      />
      {result.limits.map((l) => (
        <p key={l} className="fine" style={{ margin: "2px 12px 0" }}>
          {l}
        </p>
      ))}
      <div style={{ height: 12 }} />
    </div>
  );
}

const GATE_FEATURES = [
  { title: "Collisions", text: "Overlap shown in red, with its volume", tone: "#FBE7E4" },
  { title: "Closest gap", text: "Smallest clearance to the assembly", tone: "#E8EEFB" },
  { title: "Seating", text: "Shared CAD frame or automatic, then nudge in X, Y, Z", tone: "#ECEEF1" },
];

/** Board X5: what Fit in context does, locked, and how to get the pilot plan. No file is read. */
function FitPilotGate() {
  return (
    <MakeWorld label="Fit in context">
      <MakeHead title="Fit in context" meta={[<b key="p">Pilot plan</b>, "Your plan: single-part checks"]} />
      <Content>
        <div className="slot">
          <span className="lab">Part + assembly</span>
          <span className="lock">{LOCK}Pilot</span>
          <svg width="260" height="190" viewBox="0 0 260 190" fill="none" aria-hidden="true">
            <path d="M30 120 130 70l100 50-100 50z" fill="rgba(154,163,174,.18)" stroke="#9AA3AE" strokeWidth="1.5" strokeDasharray="4 4" />
            <path d="M30 120v-24l100-50 100 50v24" stroke="#9AA3AE" strokeWidth="1.5" strokeDasharray="4 4" />
            <path d="M100 92 140 72l40 20-40 20z" fill="#D3D7DD" stroke="#5F656E" strokeWidth="1.5" />
            <path d="M100 92v34l40 20v-34zM180 92v34l-40 20" fill="#C3C8CF" stroke="#5F656E" strokeWidth="1.5" />
            <path d="M128 118l12 6 12-6-12-6z" fill="#D92D20" opacity=".85" />
          </svg>
        </div>
        <div className="three">
          {GATE_FEATURES.map((f) => (
            <div key={f.title} className="panel">
              <i style={{ background: f.tone }} aria-hidden="true" />
              <b>{f.title}</b>
              <span>{f.text}</span>
            </div>
          ))}
        </div>
        <p className="pmeta">
          <span>Inputs: part + assembly</span>
          <span>STEP, STL, OBJ, 3MF, IGES</span>
        </p>
      </Content>
      <Sheet label="Get access" style={{ bottom: "auto" }}>
        <PilotPlanCard includes={PILOT_INCLUDES} />
      </Sheet>
    </MakeWorld>
  );
}
