"use client";

/**
 * Write controls for an org viewer: shown disabled with one line saying why,
 * never offered as if they would work (the server refuses them anyway). The
 * shell already knows the active org's role (`checkBlocked` is set only for a
 * viewer), so this reads it from there.
 */
import * as React from "react";
import { useShell } from "./shell";
import { viewerWriteLine } from "./viewer-access";

/** The viewer's line for `what`, or null when the person may change things. */
export function useReadOnly(what?: string): string | null {
  const { checkBlocked } = useShell();
  return checkBlocked ? viewerWriteLine(what) : null;
}

/** The one line under a group of disabled controls. */
export function ReadOnlyLine({ line, id, style }: { line: string | null; id?: string; style?: React.CSSProperties }) {
  if (!line) return null;
  return (
    <p id={id} className="nb-fine" role="note" style={{ margin: "6px 0 0", color: "var(--ink3)", fontSize: 12.5, ...style }}>
      {line}
    </p>
  );
}
