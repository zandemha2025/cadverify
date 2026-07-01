"use client";

/**
 * QuantityScrubber — THE signature interaction of the Living Instrument.
 *
 * A full-width SVG gauge: log quantity on x, $/unit on y, one graphite curve per
 * costed process. The cheapest-DFM-ready process at the held quantity is LIT in
 * Datum blue, and the draggable handle is a dot that rides directly ON that lit
 * curve — so the control you hold IS the cost the readout names. Drag (pointer)
 * or arrow-key the handle and the recommendation flips, the cost morphs, and the
 * crossovers light up — all client-side from lib/breakeven's fitted curves, zero
 * server roundtrip. The scrub is the motion; nothing else animates (curves draw
 * in once on mount, then hold).
 */

import * as React from "react";
import {
  type Breakeven,
  unitCostAt,
  recommendAt,
  posToQty,
} from "@/lib/breakeven";
import { procLabel } from "@/lib/status";

/* Twilight-context palette (this panel always lives under .cv-twilight). */
const LIT = "#3fa3e8"; // Datum live
const MUTED = "#46597d"; // graphite alternative curves
const GRID = "#1c2a42";
const AXIS = "#6f8099";
const WITNESS = "#8aa0bf"; // engine's authoritative crossover witness line

const PAD = { l: 52, r: 18, t: 26, b: 46 };
const HEIGHT = 252;

function fmtMoney(n: number): string {
  if (!Number.isFinite(n)) return "—";
  return `$${n.toLocaleString("en-US", {
    maximumFractionDigits: n < 10 ? 2 : n < 1000 ? 1 : 0,
  })}`;
}
function fmtQty(n: number): string {
  if (n >= 1000)
    return `${(n / 1000).toLocaleString("en-US", { maximumFractionDigits: n < 10000 ? 1 : 0 })}k`;
  return String(Math.round(n));
}

export function QuantityScrubber({
  breakeven,
  qty,
  pos,
  recommendedProcess,
  onPosChange,
  recosting = false,
}: {
  breakeven: Breakeven;
  qty: number;
  pos: number;
  recommendedProcess: string;
  onPosChange: (pos: number) => void;
  recosting?: boolean;
}) {
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const svgRef = React.useRef<SVGSVGElement>(null);
  const [w, setW] = React.useState(880);
  const [dragging, setDragging] = React.useState(false);
  const [drawn, setDrawn] = React.useState(false);

  // measure for crisp text + accurate pointer mapping
  React.useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const cw = entries[0]?.contentRect.width;
      if (cw) setW(Math.max(420, Math.round(cw)));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // curves draw in ONCE on mount (skipped under reduced motion)
  React.useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setDrawn(true);
      return;
    }
    const id = requestAnimationFrame(() => requestAnimationFrame(() => setDrawn(true)));
    return () => cancelAnimationFrame(id);
  }, []);

  const { curves, qtyMin, qtyMax, crossoverQty } = breakeven;
  const H = HEIGHT;
  const plotW = Math.max(1, w - PAD.l - PAD.r);
  const plotH = H - PAD.t - PAD.b;
  const logMin = Math.log(Math.max(1, qtyMin));
  const logMax = Math.log(Math.max(qtyMin + 1, qtyMax));

  const x = React.useCallback(
    (q: number) =>
      PAD.l + ((Math.log(Math.max(1, q)) - logMin) / (logMax - logMin)) * plotW,
    [logMin, logMax, plotW]
  );

  // dense log samples for smooth paths
  const dense = React.useMemo(() => {
    const n = 88;
    const out: number[] = [];
    for (let i = 0; i < n; i++)
      out.push(Math.exp(logMin + ((logMax - logMin) * i) / (n - 1)));
    return out;
  }, [logMin, logMax]);

  // y scale: focus on the decision-relevant band — the lower-cost envelope —
  // so the recommended cost always fits; pricier curves clip cleanly at the top.
  const yCap = React.useMemo(() => {
    let envMax = 0;
    for (const q of dense) {
      let env = Infinity;
      for (const c of curves) env = Math.min(env, unitCostAt(c, q));
      if (Number.isFinite(env)) envMax = Math.max(envMax, env);
    }
    if (envMax <= 0) {
      let v = 0;
      for (const c of curves) v = Math.max(v, c.variablePerUnit || 0);
      envMax = v || 1;
    }
    return envMax * 1.25;
  }, [dense, curves]);

  const y = React.useCallback(
    (u: number) => {
      const cl = Math.min(yCap, Math.max(0, u));
      return PAD.t + (1 - cl / yCap) * plotH;
    },
    [yCap, plotH]
  );

  const linePath = React.useCallback(
    (c: (typeof curves)[number]) =>
      dense
        .map((q, i) => `${i === 0 ? "M" : "L"}${x(q).toFixed(1)} ${y(unitCostAt(c, q)).toFixed(1)}`)
        .join(" "),
    [dense, x, y]
  );

  const litCurve =
    curves.find((c) => c.process === recommendedProcess) ?? curves[0] ?? null;
  const litArea = React.useMemo(() => {
    if (!litCurve) return "";
    const top = dense
      .map((q, i) => `${i === 0 ? "M" : "L"}${x(q).toFixed(1)} ${y(unitCostAt(litCurve, q)).toFixed(1)}`)
      .join(" ");
    return `${top} L${x(dense[dense.length - 1]).toFixed(1)} ${(PAD.t + plotH).toFixed(1)} L${x(
      dense[0]
    ).toFixed(1)} ${(PAD.t + plotH).toFixed(1)} Z`;
  }, [litCurve, dense, x, y, plotH]);

  // recommendation flips (DFM-aware) — the quantities where the lit curve hands off
  const flips = React.useMemo(() => {
    const out: { qty: number; process: string }[] = [];
    let prev = recommendAt(breakeven, dense[0])?.curve.process ?? null;
    for (let i = 1; i < dense.length; i++) {
      const p = recommendAt(breakeven, dense[i])?.curve.process ?? null;
      if (p && p !== prev) {
        out.push({ qty: Math.round(Math.sqrt(dense[i - 1] * dense[i])), process: p });
        prev = p;
      }
    }
    return out;
  }, [breakeven, dense]);

  const handleX = x(qty);
  const handleCost = litCurve ? unitCostAt(litCurve, qty) : NaN;
  const handleY = y(handleCost);

  // pointer → pos
  const posFromClientX = React.useCallback(
    (clientX: number) => {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return pos;
      const svgX = ((clientX - rect.left) / rect.width) * w; // rect maps 1:1 to viewBox px
      return Math.min(1, Math.max(0, (svgX - PAD.l) / plotW));
    },
    [w, plotW, pos]
  );

  const onPointerDown = (e: React.PointerEvent) => {
    (e.target as Element).setPointerCapture?.(e.pointerId);
    setDragging(true);
    onPosChange(posFromClientX(e.clientX));
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragging) return;
    onPosChange(posFromClientX(e.clientX));
  };
  const endDrag = (e: React.PointerEvent) => {
    setDragging(false);
    (e.target as Element).releasePointerCapture?.(e.pointerId);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    let next = pos;
    const fine = 0.015;
    const coarse = 0.08;
    switch (e.key) {
      case "ArrowLeft":
      case "ArrowDown":
        next = pos - fine;
        break;
      case "ArrowRight":
      case "ArrowUp":
        next = pos + fine;
        break;
      case "PageDown":
        next = pos - coarse;
        break;
      case "PageUp":
        next = pos + coarse;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = 1;
        break;
      default:
        return;
    }
    e.preventDefault();
    onPosChange(Math.min(1, Math.max(0, next)));
  };

  const xTicks = [1, 10, 100, 1000, 10000, 100000].filter(
    (t) => t >= qtyMin && t <= qtyMax
  );
  const yTicks = [0, 0.5, 1].map((f) => f * yCap);

  return (
    <div
      ref={wrapRef}
      className="select-none"
      style={{ opacity: recosting ? 0.72 : 1, transition: "opacity 180ms var(--ease-instrument)" }}
    >
      <svg
        ref={svgRef}
        viewBox={`0 0 ${w} ${H}`}
        width="100%"
        height={H}
        style={{ touchAction: "none", display: "block", cursor: dragging ? "grabbing" : "ew-resize" }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        role="presentation"
      >
        <defs>
          <linearGradient id="cv-env" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={LIT} stopOpacity="0.20" />
            <stop offset="100%" stopColor={LIT} stopOpacity="0" />
          </linearGradient>
          <clipPath id="cv-plot">
            <rect x={PAD.l} y={PAD.t - 6} width={plotW} height={plotH + 6} />
          </clipPath>
        </defs>

        {/* y gridlines + labels */}
        {yTicks.map((v, i) => (
          <g key={`y${i}`}>
            <line
              x1={PAD.l}
              x2={PAD.l + plotW}
              y1={y(v)}
              y2={y(v)}
              stroke={GRID}
              strokeWidth={1}
            />
            <text
              x={PAD.l - 8}
              y={y(v) + 3}
              textAnchor="end"
              fontSize={10}
              fill={AXIS}
              fontFamily="var(--font-mono)"
            >
              {fmtMoney(v)}
            </text>
          </g>
        ))}

        {/* x ticks + labels */}
        {xTicks.map((t) => (
          <g key={`x${t}`}>
            <line x1={x(t)} x2={x(t)} y1={PAD.t} y2={PAD.t + plotH} stroke={GRID} strokeWidth={1} />
            <text
              x={x(t)}
              y={PAD.t + plotH + 14}
              textAnchor="middle"
              fontSize={10}
              fill={AXIS}
              fontFamily="var(--font-mono)"
            >
              {fmtQty(t)}
            </text>
          </g>
        ))}

        {/* engine's authoritative crossover — a muted witness line */}
        {crossoverQty != null && crossoverQty >= qtyMin && crossoverQty <= qtyMax && (
          <g clipPath="url(#cv-plot)">
            <line
              x1={x(crossoverQty)}
              x2={x(crossoverQty)}
              y1={PAD.t}
              y2={PAD.t + plotH}
              stroke={WITNESS}
              strokeWidth={1}
              strokeDasharray="3 4"
              opacity={0.6}
            />
          </g>
        )}

        {/* lit envelope fill */}
        {litArea && (
          <path d={litArea} fill="url(#cv-env)" clipPath="url(#cv-plot)" opacity={drawn ? 1 : 0} style={{ transition: "opacity 500ms 200ms var(--ease-instrument)" }} />
        )}

        {/* alternative curves (graphite) */}
        <g clipPath="url(#cv-plot)">
          {curves
            .filter((c) => c.process !== recommendedProcess)
            .map((c) => (
              <path
                key={c.process}
                d={linePath(c)}
                fill="none"
                stroke={MUTED}
                strokeWidth={1.5}
                strokeLinecap="round"
                pathLength={1}
                strokeDasharray={1}
                strokeDashoffset={drawn ? 0 : 1}
                style={{ transition: "stroke-dashoffset 620ms var(--ease-instrument)" }}
              />
            ))}
          {/* the lit (recommended) curve — drawn last, on top */}
          {litCurve && (
            <path
              d={linePath(litCurve)}
              fill="none"
              stroke={LIT}
              strokeWidth={2.75}
              strokeLinecap="round"
              strokeLinejoin="round"
              pathLength={1}
              strokeDasharray={1}
              strokeDashoffset={drawn ? 0 : 1}
              style={{
                transition: "stroke-dashoffset 700ms var(--ease-instrument)",
                filter: "drop-shadow(0 0 6px rgba(63,163,232,0.45))",
              }}
            />
          )}
        </g>

        {/* recommendation-flip crossovers — lit Datum ticks + labels */}
        {flips.map((f, i) => (
          <g key={`f${i}`} clipPath="url(#cv-plot)">
            <line
              x1={x(f.qty)}
              x2={x(f.qty)}
              y1={PAD.t}
              y2={PAD.t + plotH}
              stroke={LIT}
              strokeWidth={1}
              strokeDasharray="2 3"
              opacity={0.55}
            />
            <text
              x={x(f.qty)}
              y={PAD.t - 8}
              textAnchor="middle"
              fontSize={9.5}
              fill={LIT}
              fontFamily="var(--font-mono)"
            >
              ⇡ {procLabel(f.process)}
            </text>
            <text
              x={x(f.qty)}
              y={PAD.t + 4}
              textAnchor="middle"
              fontSize={9}
              fill={WITNESS}
              fontFamily="var(--font-mono)"
            >
              {fmtQty(f.qty)}
            </text>
          </g>
        ))}

        {/* THE HANDLE — vertical datum + dot riding the lit curve */}
        <line
          x1={handleX}
          x2={handleX}
          y1={PAD.t - 6}
          y2={PAD.t + plotH}
          stroke={LIT}
          strokeWidth={1.5}
          opacity={0.9}
        />
        {/* cost tag at the dot */}
        {Number.isFinite(handleCost) && (
          <g transform={`translate(${Math.min(handleX, PAD.l + plotW - 64)}, ${Math.max(PAD.t + 6, handleY - 26)})`}>
            <rect
              x={2}
              y={-13}
              width={62}
              height={18}
              rx={3}
              fill="#0c1729"
              stroke={LIT}
              strokeOpacity={0.5}
            />
            <text x={33} y={0} textAnchor="middle" fontSize={11} fill={LIT} fontFamily="var(--font-mono)" fontWeight={600}>
              {fmtMoney(handleCost)}
            </text>
          </g>
        )}
        {/* the riding dot */}
        <circle cx={handleX} cy={handleY} r={9} fill={LIT} opacity={0.18} />
        <circle
          cx={handleX}
          cy={handleY}
          r={5}
          fill="#0b1220"
          stroke={LIT}
          strokeWidth={2.5}
          style={{ filter: "drop-shadow(0 0 5px rgba(63,163,232,0.6))" }}
        />

        {/* focusable handle target for keyboard control */}
        <rect
          x={handleX - 11}
          y={PAD.t - 6}
          width={22}
          height={plotH + 6}
          fill="transparent"
          tabIndex={0}
          role="slider"
          aria-label="Order quantity"
          aria-valuemin={qtyMin}
          aria-valuemax={qtyMax}
          aria-valuenow={qty}
          aria-valuetext={`${qty.toLocaleString()} units`}
          onKeyDown={onKeyDown}
          style={{ cursor: "ew-resize", outline: "none" }}
        />

        {/* qty pill — rides the handle on its own row below the axis labels */}
        <g transform={`translate(${Math.min(Math.max(handleX, PAD.l + 28), PAD.l + plotW - 28)}, ${PAD.t + plotH + 28})`}>
          <rect x={-27} y={-1} width={54} height={16} rx={3} fill={LIT} />
          <text x={0} y={11} textAnchor="middle" fontSize={10.5} fill="#07131f" fontFamily="var(--font-mono)" fontWeight={700}>
            {fmtQty(qty)}
          </text>
        </g>
      </svg>

      {/* under-rail: ends + a hint, mono evidence */}
      <div className="num mt-1 flex items-center justify-between text-[11px] text-[#6f8099]">
        <span>{qtyMin.toLocaleString()} unit</span>
        <span className="text-[#8fc8f2]">drag the dot — the recommendation flips live</span>
        <span>{posToQty(breakeven, 1).toLocaleString()} units</span>
      </div>
    </div>
  );
}
