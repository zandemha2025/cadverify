"use client";

/**
 * Can't read this file (board X4): the right-hand sheet that says what is wrong
 * with a file the check can't use and how to fix it in CAD. The host draws the
 * stage (the open shell, or `<NothingToDraw />` when there are no surfaces).
 *
 * `<CantReadSheet>` props:
 * - `fileName`  the file as dropped.
 * - `problem`   "open" (not watertight) | "nosurface" (no faces after meshing) |
 *               "geometry" (mesher refused a surface) | "unreadable" (contents
 *               don't parse) | "unsupported" (format we can't read).
 * - `head`, `quote`  the red quote box: a short finding and its detail. Use
 *               `cantReadCopy(reason)` to get both from the server's message.
 * - `meta`      facts after the file name ("945 open edges", "Top face missing").
 * - `onPick`    "Choose file" (upload another).
 * - `onRepair`  optional; shows "Repair here" for open shells (any plan, no check used).
 * - `onRetry`   optional; shows "Try again" when the check never reached the engine.
 *
 * Also: `CadToolSteps` (the per-tool export path picker) and `NothingToDraw`.
 */
import * as React from "react";
import { analysisFailureCopy } from "@/lib/verify/failure-copy";
import { cx } from "../ui";
import "./moments.css";

export type CantReadProblem = "open" | "nosurface" | "geometry" | "unreadable" | "unsupported";

const CAD_TOOLS: [string, string, string][] = [
  ["sw", "SOLIDWORKS", "File › Save As, then choose STEP AP214 (*.step)."],
  ["fusion", "Fusion", "File › Export, then choose STEP (*.step)."],
  ["onshape", "Onshape", "Right-click the part › Export, then choose STEP."],
  ["inventor", "Inventor", "File › Export › CAD Format, then choose STEP."],
  ["creo", "Creo", "File › Save As › Save a Copy, then choose STEP."],
  ["nx", "NX", "File › Export › STEP."],
];

const FIX: Record<CantReadProblem, string> = {
  open: "Repair or Heal the gap, then export the solid body, not surfaces.",
  nosurface: "Re-export as a solid body. Wireframe and sketch exports can’t be checked.",
  geometry: "Re-export the part as a clean solid body, then upload it again.",
  unreadable: "Re-export the original part as a clean STEP, STL or IGES file, then upload that export.",
  unsupported: "Export the part as STEP, STL or IGES from your CAD tool, then upload that file.",
};

/** The quote box and problem kind for a server refusal or failure reason. */
export function cantReadCopy(reason: string | null | undefined): { problem: CantReadProblem; head: string; quote: string } {
  const value = reason?.trim() ?? "";
  if (/no surface triangles|no faces|wire ?frame|unmeshable/i.test(value)) {
    return { problem: "nosurface", head: "Can’t mesh", quote: "No surface triangles after meshing." };
  }
  const copy = analysisFailureCopy(value);
  if (copy.kind === "unsupported") return { problem: "unsupported", head: copy.title.replace(/\.$/, ""), quote: copy.explanation };
  if (copy.kind === "geometry") return { problem: "geometry", head: "Can’t mesh", quote: copy.explanation };
  return { problem: "unreadable", head: copy.kind === "unreadable" ? copy.title.replace(/\.$/, "") : "Can’t read this file", quote: copy.kind === "unreadable" ? copy.explanation : value || "The file couldn’t be read." };
}

export function CadToolSteps() {
  const [tool, setTool] = React.useState("sw");
  const t = CAD_TOOLS.find((x) => x[0] === tool) ?? CAD_TOOLS[0];
  return (
    <>
      <div className="tools" role="group" aria-label="Your CAD tool">
        <span className="seg">
          {CAD_TOOLS.map(([k, label]) => (
            <button key={k} type="button" className={cx(tool === k && "on")} aria-pressed={tool === k} onClick={() => setTool(k)}>
              {label}
            </button>
          ))}
        </span>
      </div>
      <div className="path" aria-live="polite">
        {t[1]}: {t[2]}
      </div>
    </>
  );
}

export function CantReadSheet({
  fileName,
  problem,
  head,
  quote,
  meta = [],
  onPick,
  onRepair,
  onRetry,
}: {
  fileName: string;
  problem: CantReadProblem;
  head: string;
  quote: string;
  meta?: string[];
  onPick: () => void;
  onRepair?: () => void;
  onRetry?: () => void;
}) {
  return (
    <aside className="sheet mo-x4" aria-label="What's wrong and how to fix it">
      <div className="top">
        <h1 className="ptitle">Can&apos;t read this file</h1>
        <p className="pmeta" style={{ marginTop: 6 }}>
          {[fileName, ...meta].filter(Boolean).map((m, i) => (
            <span key={i} style={{ overflowWrap: "anywhere" }}>
              {m}
            </span>
          ))}
        </p>
      </div>
      <div className="scroll">
        <div className="quote" role="alert">
          <b>{head}</b>
          <span>{quote}</span>
        </div>
        <div className="step">
          <b>Fix in CAD</b>
          <p>{FIX[problem]}</p>
          <CadToolSteps />
        </div>
        {onRetry ? (
          <>
            <div className="sep" />
            <div className="step">
              <b>Try again</b>
              <p>The check didn&apos;t reach the engine. The file doesn&apos;t need re-exporting.</p>
              <span>
                <button className="btn ink sm" type="button" onClick={onRetry}>
                  Retry check
                </button>
              </span>
            </div>
          </>
        ) : null}
        {problem === "open" && onRepair ? (
          <>
            <div className="sep" />
            <div className="step">
              <b>
                Repair here <small style={{ color: "var(--ink3)", fontWeight: 500 }}>No check used</small>
              </b>
              <p>Closes gaps and shows the result beside the original. Reports if it can&apos;t.</p>
              <span>
                <button className="btn sm" type="button" onClick={onRepair}>
                  Request repair
                </button>
              </span>
            </div>
          </>
        ) : null}
        <div className="sep" />
        <div className="step">
          <b>Upload another file</b>
          <p>STEP, STL or IGES · up to 200 MB</p>
          <span>
            <button className="btn ink sm" type="button" onClick={onPick}>
              Choose file
            </button>
          </span>
        </div>
      </div>
    </aside>
  );
}

/** The stage placeholder when there is nothing to draw (no surfaces, or a format we can't read). */
export function NothingToDraw({ title = "No surfaces", text = "Edges and curves only" }: { title?: string; text?: string }) {
  return (
    <div className="mo-nothing swap">
      <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true">
        <path d="M8 28 20 8l12 20H8Z" stroke="currentColor" strokeWidth="1.6" strokeDasharray="3 3" strokeLinejoin="round" />
      </svg>
      <b>{title}</b>
      <span>{text}</span>
    </div>
  );
}
