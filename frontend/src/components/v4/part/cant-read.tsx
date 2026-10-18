"use client";

/** X4: a file the check can't use, with the fix in CAD and the next step. */
import * as React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { CAD_ACCEPT } from "../pending-file";
import { R } from "../routes";
import type { CheckSession } from "./store";
import { dimsText, plural } from "./model";
import type { ViewerController } from "./viewer";
import { CantReadSheet } from "./blocked";
import "./part.css";

const PartViewer = dynamic(() => import("./viewer"), { ssr: false });

/** "945 open edges" from the engine's own watertight finding. */
export function openEdges(s: CheckSession): number | null {
  const v = s.validation ?? s.result?.validation ?? null;
  const issue = v?.universal_issues.find((i) => i.code === "NON_WATERTIGHT");
  const m = issue?.message.match(/has (\d[\d,]*) boundary edges/);
  return m ? Number(m[1].replace(/,/g, "")) : null;
}

export function CantReadView({
  session,
  onPick,
  onRepair,
  onRetry,
  overlay,
}: {
  session: CheckSession;
  onPick: (f: File) => void;
  onRepair?: () => void;
  onRetry?: () => void;
  overlay?: React.ReactNode;
}) {
  const input = React.useRef<HTMLInputElement>(null);
  const controller = React.useRef(null) as ViewerController;
  const [vstate, setVstate] = React.useState<string>("loading");
  const f = session.failure;
  const open = session.status === "stopped";
  const v = session.validation ?? session.result?.validation ?? null;
  const edges = openEdges(session);
  const dims = dimsText(v?.geometry.bounding_box_mm);
  const problem = open ? "open" : f?.kind === "unreadable" ? f.problem : "unreadable";
  const head = open ? "Not watertight" : f?.kind === "unreadable" ? f.title : "Can’t read this file";
  const quote = open
    ? `Every process needs a closed solid.${edges != null ? ` This one has ${plural(edges, "open edge")}.` : ""} Common causes: missing faces, T-junctions, separate shells.`
    : f?.kind === "unreadable"
      ? f.detail
      : "The file couldn’t be read.";
  const meta = open ? [edges != null ? plural(edges, "open edge") : "Open shell", dims ?? ""].filter(Boolean) : [problem === "unsupported" ? "Format not supported" : "Nothing checked"];
  const fileMeta = open ? [dims, "open shell", v ? `${v.geometry.faces.toLocaleString("en-US")} faces` : null].filter(Boolean).join(" · ") : `${(session.file.name.split(".").pop() ?? "").toUpperCase()} · not checked`;
  return (
    <main className="world pv" aria-label="The file you dropped">
      <section className="stage" aria-label="The file you dropped">
        <div className="hud">
          <Link href={R.parts} style={{ fontSize: 12.5, textDecoration: "none", marginBottom: 2 }}>
            ‹ Parts
          </Link>
          <h1 title={session.file.name}>{session.file.name}</h1>
          <span className="num">{fileMeta}</span>
          {open ? <span>Nothing is priced from a shape that isn&apos;t closed</span> : null}
        </div>
        {open && session.preview.url && vstate !== "failed" && vstate !== "nowebgl" ? (
          <>
            <div className="obj swap" role="img" aria-label="The part as read from the file, with its open shell">
              <span className="shade" />
              <PartViewer url={session.preview.url} highlight={null} xray={false} controllerRef={controller} onState={setVstate} />
            </div>
            {edges != null ? (
              <span className="legend">
                <i />
                {plural(edges, "open edge")} · not a closed solid
              </span>
            ) : null}
          </>
        ) : (
          <div className="nothing swap">
            <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true">
              <path d="M8 28 20 8l12 20H8Z" stroke="currentColor" strokeWidth="1.6" strokeDasharray="3 3" strokeLinejoin="round" />
            </svg>
            <b>{open ? "No 3D view" : problem === "unsupported" ? "Not a format we read" : "No surfaces we could use"}</b>
            <span>{open ? "The measured shape is still described on the right." : "Nothing was checked; no record was made."}</span>
          </div>
        )}
      </section>
      <CantReadSheet fileName={session.file.name} problem={problem} head={head} quote={quote} meta={meta} onRepair={onRepair} onPick={() => input.current?.click()} onRetry={onRetry} />
      <input
        ref={input}
        type="file"
        accept={CAD_ACCEPT}
        aria-label="Choose a CAD file to check"
        tabIndex={-1}
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) onPick(file);
        }}
      />
      {overlay}
    </main>
  );
}
