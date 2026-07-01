"use client";

/**
 * The ghost part — the instrument's idle centerpiece. Not a dashed dropzone
 * box: a faint engineering drawing of a machined flange (bore, bolt circle,
 * dimension callouts) rendered in Datum blueprint strokes, waiting for a real
 * part to take its place. When a file is dragged over the workspace it lights
 * up and a measurement sweep runs across it — the tool "coming alive." Purely
 * decorative (aria-hidden); the real intake affordance is the surface itself.
 */

import * as React from "react";

export function GhostPart({ active = false }: { active?: boolean }) {
  const stroke = active ? "#5cb4f0" : "#2f5f8f";
  const dim = active ? "#7fb8e6" : "#33557a";
  const glow = active ? 0.6 : 0.28;

  return (
    <svg
      viewBox="0 0 360 300"
      className="h-full w-full"
      fill="none"
      aria-hidden
      style={{ transition: "opacity 400ms var(--ease-instrument)", opacity: active ? 1 : 0.85 }}
    >
      <defs>
        <radialGradient id="gp-bloom" cx="50%" cy="46%" r="55%">
          <stop offset="0%" stopColor="#3fa3e8" stopOpacity={glow * 0.5} />
          <stop offset="100%" stopColor="#3fa3e8" stopOpacity="0" />
        </radialGradient>
      </defs>

      <rect x="0" y="0" width="360" height="300" fill="url(#gp-bloom)" />

      {/* dimension callout — overall width */}
      <g stroke={dim} strokeWidth="1">
        <path d="M96 44v-18M264 44v-18" />
        <path d="M96 32h168" strokeDasharray="0" />
        <path d="M96 32l7 -3.5v7z" fill={dim} stroke="none" />
        <path d="M264 32l-7 -3.5v7z" fill={dim} stroke="none" />
      </g>
      <text x="180" y="24" textAnchor="middle" fontSize="11" fill={dim} fontFamily="var(--font-mono)">
        Ø —
      </text>

      {/* dimension callout — height (left) */}
      <g stroke={dim} strokeWidth="1">
        <path d="M64 74h-18M64 226h-18" />
        <path d="M52 74v152" />
        <path d="M52 74l-3.5 7h7z" fill={dim} stroke="none" />
        <path d="M52 226l-3.5 -7h7z" fill={dim} stroke="none" />
      </g>

      {/* the flange body */}
      <rect
        x="96"
        y="74"
        width="168"
        height="152"
        rx="14"
        stroke={stroke}
        strokeWidth="1.6"
        style={{ transition: "stroke 400ms var(--ease-instrument)" }}
      />
      {/* inner relief */}
      <rect x="112" y="90" width="136" height="120" rx="8" stroke={stroke} strokeWidth="1" strokeOpacity="0.5" />

      {/* central bore + counterbore */}
      <circle cx="180" cy="150" r="34" stroke={stroke} strokeWidth="1.6" />
      <circle cx="180" cy="150" r="22" stroke={stroke} strokeWidth="1" strokeOpacity="0.6" />

      {/* bolt circle — four mounting holes on a datum circle */}
      <circle cx="180" cy="150" r="58" stroke={dim} strokeWidth="0.75" strokeDasharray="3 4" strokeOpacity="0.7" />
      {[
        [180 - 41, 150 - 41],
        [180 + 41, 150 - 41],
        [180 - 41, 150 + 41],
        [180 + 41, 150 + 41],
      ].map(([cx, cy], i) => (
        <circle key={i} cx={cx} cy={cy} r="7" stroke={stroke} strokeWidth="1.2" />
      ))}

      {/* center lines (datum) */}
      <g stroke={dim} strokeWidth="0.75" strokeOpacity="0.55">
        <path d="M180 60v180" strokeDasharray="8 4 2 4" />
        <path d="M84 150h192" strokeDasharray="8 4 2 4" />
      </g>

      {/* measurement sweep when a file is dragged over */}
      {active && (
        <g>
          <line x1="96" y1="150" x2="264" y2="150" stroke="#3fa3e8" strokeWidth="1.5" opacity="0.9">
            <animate attributeName="y1" values="80;220;80" dur="2.4s" repeatCount="indefinite" />
            <animate attributeName="y2" values="80;220;80" dur="2.4s" repeatCount="indefinite" />
          </line>
        </g>
      )}
    </svg>
  );
}
