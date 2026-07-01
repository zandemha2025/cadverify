"use client";

/**
 * InstrumentControls — the recalibration knobs that change the WHOLE decision
 * live. The shop dial binds a shop's real rates (SHOP provenance); the material /
 * region / labor-rate knobs re-cost the part (labor rate threads the real
 * overrides API → USER re-tag). Every turn is a real, debounced server re-cost;
 * the readout keeps its value and shimmers, then settles to the new number.
 */

import * as React from "react";
import { Minus, Plus, RotateCcw, Factory } from "lucide-react";
import type { ShopProfileInfo } from "@/lib/api";

const MATERIALS = ["polymer", "aluminum", "steel", "stainless", "titanium"];
const REGIONS = ["auto", "US", "EU", "MX", "CN", "IN", "SA"];

function Chip({
  active,
  onClick,
  children,
  disabled,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={active}
      className={[
        "num shrink-0 rounded-sm border px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3fa3e8] disabled:opacity-50",
        active
          ? "border-[#3fa3e8] bg-[#12365a] text-[#bfe0fb]"
          : "border-[#233149] bg-[#0f1b2e] text-[#9fb0c8] hover:border-[#33446a] hover:text-[#eaeff7]",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

function KnobRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <span className="cv-eyebrow">{label}</span>
      <div className="flex flex-wrap items-center gap-1.5">{children}</div>
    </div>
  );
}

export function InstrumentControls({
  shops,
  activeShopId,
  onSelectShop,
  materialClass,
  onMaterial,
  region,
  onRegion,
  laborRate,
  laborDefault,
  onLaborRate,
  recosting,
}: {
  shops: ShopProfileInfo[];
  activeShopId: string | null;
  onSelectShop: (id: string | null) => void;
  materialClass: string;
  onMaterial: (v: string) => void;
  region: string;
  onRegion: (v: string) => void;
  laborRate: number | null;
  laborDefault: number | null;
  onLaborRate: (v: number | null) => void;
  recosting: boolean;
}) {
  const labor = laborRate ?? laborDefault ?? 40;
  const overridden = laborRate != null;
  const step = (delta: number) =>
    onLaborRate(Math.min(500, Math.max(1, Math.round((labor + delta) / 1) * 1)));

  return (
    <div className="space-y-4 rounded-[var(--radius)] border border-[#233149] bg-[#0d1828]/80 p-4">
      <div className="flex items-center justify-between">
        <span className="cv-eyebrow">Recalibrate</span>
        <span
          className="num text-[10px] uppercase tracking-wide text-[#3fa3e8]"
          style={{ opacity: recosting ? 1 : 0, transition: "opacity 150ms" }}
        >
          recalibrating…
        </span>
      </div>

      {/* shop dial */}
      <KnobRow label="Shop calibration">
        <Chip active={activeShopId == null} onClick={() => onSelectShop(null)} disabled={recosting}>
          <span className="inline-flex items-center gap-1">
            <Factory className="size-3 opacity-70" /> Generic
          </span>
        </Chip>
        {shops.map((s) => (
          <Chip
            key={s.id}
            active={activeShopId === s.id}
            onClick={() => onSelectShop(s.id)}
            disabled={recosting}
          >
            {s.name}
            <span className="ml-1 opacity-60">· {s.region}</span>
          </Chip>
        ))}
        {shops.length === 0 && (
          <span className="text-[11px] text-[#6f8099]">no bound shops — generic rates</span>
        )}
      </KnobRow>

      <div className="grid gap-4 sm:grid-cols-2">
        <KnobRow label="Material class">
          {MATERIALS.map((m) => (
            <Chip key={m} active={materialClass === m} onClick={() => onMaterial(m)} disabled={recosting}>
              {m}
            </Chip>
          ))}
        </KnobRow>

        <KnobRow label="Region">
          {REGIONS.map((r) => (
            <Chip key={r} active={region === r} onClick={() => onRegion(r)} disabled={recosting}>
              {r}
            </Chip>
          ))}
        </KnobRow>
      </div>

      {/* labor-rate knob → overrides API (USER) */}
      <KnobRow label="Labor rate">
        <div className="inline-flex items-center gap-1 rounded-sm border border-[#233149] bg-[#0f1b2e] p-0.5">
          <button
            type="button"
            onClick={() => step(-5)}
            disabled={recosting}
            aria-label="Lower labor rate"
            className="rounded-sm p-1.5 text-[#9fb0c8] hover:bg-[#15314c] hover:text-[#eaeff7] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3fa3e8] disabled:opacity-50"
          >
            <Minus className="size-3.5" />
          </button>
          <span className="num w-20 text-center text-sm font-semibold text-[#eaeff7]">
            ${labor}/hr
          </span>
          <button
            type="button"
            onClick={() => step(5)}
            disabled={recosting}
            aria-label="Raise labor rate"
            className="rounded-sm p-1.5 text-[#9fb0c8] hover:bg-[#15314c] hover:text-[#eaeff7] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3fa3e8] disabled:opacity-50"
          >
            <Plus className="size-3.5" />
          </button>
        </div>
        <span
          className="num rounded-xs border px-1.5 py-0.5 text-[10px] font-medium"
          style={
            overridden
              ? { color: "#a99bf0", borderColor: "#3a2f66", background: "#1c1733" }
              : { color: "#8a93a3", borderColor: "#344461", background: "#18243a" }
          }
        >
          {overridden ? "USER override" : "default rate"}
        </span>
        {overridden && (
          <button
            type="button"
            onClick={() => onLaborRate(null)}
            disabled={recosting}
            className="inline-flex items-center gap-1 text-[11px] text-[#9fb0c8] hover:text-[#eaeff7] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3fa3e8] disabled:opacity-50"
          >
            <RotateCcw className="size-3" /> reset
          </button>
        )}
      </KnobRow>
    </div>
  );
}
