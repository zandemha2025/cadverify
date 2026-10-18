"use client";

/**
 * The turntable around the 3D stage (boards F1, F2, F4): a focusable button,
 * drag to turn it (momentum on release), Left/Right arrows turn it a step with
 * no animation, no zoom. "Drag to turn it" fades after the first turn. Overlays
 * (generating, failed, nothing to show) sit on top of the canvas.
 */
import * as React from "react";
import dynamic from "next/dynamic";
import { cx } from "../ui";
import type { StageController, StageLayer, StageMarker, StageState } from "./stage3d";

const Stage3D = dynamic(() => import("./stage3d"), { ssr: false });

export type { StageLayer, StageMarker, StageState };

export function Turntable({
  label,
  layers,
  markers,
  className,
  style,
  overlay,
  onState,
  hint = "Drag to turn it",
}: {
  label: string;
  layers: StageLayer[];
  markers?: StageMarker[];
  className?: string;
  style?: React.CSSProperties;
  overlay?: React.ReactNode;
  onState?: (s: StageState, detail?: string) => void;
  hint?: string | null;
}) {
  const controller: StageController = React.useRef<((radians: number) => void) | null>(null);
  const [drag, setDrag] = React.useState(false);
  const [turned, setTurned] = React.useState(false);
  const [state, setState] = React.useState<StageState>("loading");
  const report = React.useCallback(
    (s: StageState, detail?: string) => {
      setState(s);
      onState?.(s, detail);
    },
    [onState],
  );
  const has = layers.length > 0;
  const onKey = (e: React.KeyboardEvent) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step || !has) return;
    e.preventDefault();
    controller.current?.((step * Math.PI) / 18);
    setTurned(true);
  };
  return (
    <button
      type="button"
      className={cx("tt", drag && "drag", className)}
      style={style}
      aria-label={label}
      onPointerDown={(e) => {
        if (e.button) return;
        setDrag(true);
        setTurned(true);
      }}
      onPointerUp={() => setDrag(false)}
      onPointerCancel={() => setDrag(false)}
      onPointerLeave={() => setDrag(false)}
      onKeyDown={onKey}
    >
      {has ? <Stage3D layers={layers} markers={markers} controller={controller} onState={report} /> : null}
      {has && state === "loading" && !overlay ? (
        <span className="gen plain" aria-hidden="true">
          <span className="spin" />
        </span>
      ) : null}
      {has && state === "nowebgl" && !overlay ? (
        <span className="gen plain">
          <b>3D preview isn’t available in this browser</b>
          <span>The measured numbers are unaffected.</span>
        </span>
      ) : null}
      {overlay}
      {hint && has && state === "ready" ? <span className={cx("hint", turned && "gone")}>{hint}</span> : null}
    </button>
  );
}
