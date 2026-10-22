"use client";

/**
 * Home's drop target (board P1 "Start"): one CAD file goes to the check page;
 * several files go to a new catalog run, already picked; anything else is
 * named and refused.
 * Drag-over shows "Drop to check it". The file is handed over in memory only.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { R } from "../routes";
import { FileTrustLine } from "../trust/file-line";
import { overCadLimit, overCadLimitText } from "@/lib/upload-limit";
import { CAD_ACCEPT, setPendingFile } from "../pending-file";
import { cx } from "../ui";
import { useHandOffBatch } from "../many/catalog-entry";

const OK = /\.(step|stp|stl|iges|igs)$/i;

type Dropped = { kind: "ok"; name: string } | { kind: "bad"; name: string } | { kind: "big"; size: number } | { kind: "many"; files: File[] };

export function refusal(name: string): string {
  const dot = name.lastIndexOf(".");
  const ext = dot > 0 && dot < name.length - 1 ? name.slice(dot + 1) : "";
  return ext ? `Can't read ${ext} files. Use STEP, STL or IGES.` : `Can't read ${name}. Use STEP, STL or IGES.`;
}

export function DropZone() {
  const router = useRouter();
  const [drag, setDrag] = React.useState(false);
  const [drop, setDrop] = React.useState<Dropped | null>(null);
  const handOff = useHandOffBatch();

  const take = (files: FileList | null | undefined) => {
    setDrag(false);
    if (!files || !files.length) return;
    if (files.length > 1) {
      setDrop({ kind: "many", files: Array.from(files) });
      return;
    }
    const f = files[0];
    if (!OK.test(f.name)) {
      setDrop({ kind: "bad", name: f.name });
      return;
    }
    if (overCadLimit(f.size)) {
      setDrop({ kind: "big", size: f.size });
      return;
    }
    setDrop({ kind: "ok", name: f.name });
    setPendingFile(f);
    router.push(R.check);
  };

  const over = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    if (!drag) setDrag(true);
  };

  const title = drag ? "Drop to check it" : drop?.kind === "ok" ? drop.name : "Drop a part to check it";
  const msg = !drop ? null : drop.kind === "ok" ? "Checking now" : drop.kind === "many" ? `${drop.files.length} files dropped. Check them together as a batch.` : drop.kind === "big" ? `${overCadLimitText(drop.size)}.` : refusal(drop.name);

  return (
    <div
      className={cx("h-drop", drag && "over")}
      onDragEnter={over}
      onDragOver={over}
      onDragLeave={(e) => {
        const next = e.relatedTarget as Node | null;
        if (next && e.currentTarget.contains(next)) return;
        setDrag(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        take(e.dataTransfer?.files);
      }}
      data-testid="home-drop"
    >
      <b>{title}</b>
      <span>STEP, STL or IGES · one file</span>
      <FileTrustLine />
      {msg ? (
        <span className={drop?.kind === "ok" ? "h-ok" : "h-msg"} role="status">
          {msg}
        </span>
      ) : null}
      <span className="h-acts">
        <label className="btn sm ink h-file">
          Choose file
          <input
            type="file"
            accept={CAD_ACCEPT}
            aria-label="Choose a CAD file to check"
            onChange={(e) => {
              const files = e.target.files;
              take(files);
              e.target.value = "";
            }}
          />
        </label>
        {drop?.kind === "ok" ? (
          <Link className="btn sm" href={R.check}>
            Open
          </Link>
        ) : null}
        {drop?.kind === "many" ? (
          <button className="btn sm" type="button" onClick={() => handOff(drop.files)}>
            Check {drop.files.length} as a batch
          </button>
        ) : null}
      </span>
    </div>
  );
}
