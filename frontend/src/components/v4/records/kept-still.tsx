"use client";

/**
 * A saved part's own picture where a record is shown beside another (Compare):
 * the kept preview the part page shows (this browser's copy, else the file the
 * organization kept, tessellated on the server; no check used), turnable. The
 * neutral glyph only when there is no kept preview.
 */
import * as React from "react";
import dynamic from "next/dynamic";
import { loadPartMesh } from "../part/api";
import { urlSlot } from "../part/mesh-url";
import type { ViewerController } from "../part/viewer";
import { Glyph } from "./common";

const PartViewer = dynamic(() => import("../part/viewer"), { ssr: false });

export function KeptStill({ meshHash, filename, label }: { meshHash: string; filename: string; label: string }) {
  const [url, setUrl] = React.useState<string | null | undefined>(undefined);
  const [state, setState] = React.useState<string>("loading");
  const controller = React.useRef(null) as ViewerController;
  React.useEffect(() => {
    let live = true;
    const slot = urlSlot();
    setUrl(undefined);
    loadPartMesh(meshHash, filename).then(
      (r) => {
        if (!live) return;
        setUrl(r.mesh ? slot.set(r.mesh.blob) : null);
      },
      () => live && setUrl(null),
    );
    return () => {
      live = false;
      slot.clear();
    };
  }, [meshHash, filename]);
  const shown = url && state !== "failed" && state !== "nowebgl";
  return (
    <span className="still kept" role="img" aria-label={label}>
      <span className="shade" />
      {shown ? <PartViewer url={url} kind="glb" highlight={null} xray={false} controllerRef={controller} onState={setState} /> : <Glyph size={84} />}
      {url === undefined || (shown && state === "loading") ? <span className="still-note">Loading its 3D view…</span> : null}
    </span>
  );
}
