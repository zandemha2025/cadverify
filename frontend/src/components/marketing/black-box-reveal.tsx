"use client";

/**
 * BLACK-BOX → GLASS-BOX (identity signature 2) — the wedge as a literal reveal,
 * not a side-by-side. It starts as a solid OBSIDIAN casing: the incumbent
 * experience — a bare $14.14/unit over locked, unreadable driver rows ("trust
 * us"). On scroll (or the toggle) the opaque casing DISSOLVES into a cyanotype
 * x-ray of its interior: the identical $14.14 explodes into its provenance-
 * tagged driver stack with Σ = unit cost, over a faint blueprint grid. You watch
 * the black box become a glass box. Reduced motion → a clean cross-fade.
 *
 * The interior renders the REAL product components (DriverBreakdown,
 * ConfidenceInterval) against the engine's report — the hero IS the product.
 */

import * as React from "react";
import { Lock, EyeOff, ScanLine, Eye } from "lucide-react";
import { DriverBreakdown, ConfidenceInterval, ProvenanceLegend } from "@/components/glass-box";
import { ESTIMATE, PART } from "./data";

function LockedRow({ label, width }: { label: string; width: string }) {
  return (
    <div className="flex items-center gap-3 px-2 py-2.5">
      <Lock className="size-3.5 shrink-0 text-[#5a5e66]" aria-hidden />
      <span className="text-sm text-[#8b8f97]">{label}</span>
      <span
        className="ml-auto h-3 rounded-[2px] bg-[#2b2e34]"
        style={{ width, filter: "blur(0.5px)" }}
        aria-hidden
      />
    </div>
  );
}

export function BlackBoxReveal() {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);

  // Auto-reveal once when the device scrolls into view (a single orchestrated
  // moment). Reduced motion is honored by the global CSS transition override.
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            const t = setTimeout(() => setOpen(true), 420);
            io.disconnect();
            return () => clearTimeout(t);
          }
        }
      },
      { threshold: 0.55 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div className="mx-auto max-w-2xl">
      <div
        ref={ref}
        className="relative overflow-hidden rounded-[var(--radius-lg)] border border-border"
      >
        {/* ── INTERIOR · the glass box (the x-ray), under the casing ───────── */}
        <div className="relative bg-card">
          {/* faint cyanotype blueprint grid */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 opacity-[0.5] dark:opacity-[0.35]"
            style={{
              backgroundImage:
                "linear-gradient(to right, color-mix(in srgb, var(--cv-primary) 11%, transparent) 1px, transparent 1px), linear-gradient(to bottom, color-mix(in srgb, var(--cv-primary) 11%, transparent) 1px, transparent 1px)",
              backgroundSize: "26px 26px",
              maskImage:
                "radial-gradient(120% 100% at 50% 0%, #000 55%, transparent 100%)",
              WebkitMaskImage:
                "radial-gradient(120% 100% at 50% 0%, #000 55%, transparent 100%)",
            }}
          />
          <div className="relative flex items-center justify-between gap-2 border-b border-border bg-accent-subtle/60 px-4 py-3">
            <span className="cv-eyebrow">
              <ScanLine className="size-3.5 text-accent-text" aria-hidden />
              The glass box · CadVerify
            </span>
            <span className="num text-micro text-accent-text">
              {PART.process} · qty {PART.qty}
            </span>
          </div>
          <div className="relative space-y-4 p-5">
            <div className="flex items-baseline gap-2">
              <span className="cv-readout-hero text-[1.75rem] text-foreground">$14.14</span>
              <span className="num text-sm text-muted-foreground">
                /unit · Σ of the stack below
              </span>
            </div>
            <DriverBreakdown estimate={ESTIMATE} />
            <ConfidenceInterval confidence={ESTIMATE.confidence!} />
            <ProvenanceLegend />
          </div>
        </div>

        {/* ── CASING · the obsidian black box, dissolves away on reveal ────── */}
        <div
          aria-hidden={open}
          className="cv-obsidian absolute inset-0 flex flex-col transition-all duration-500 ease-[cubic-bezier(0.2,0,0,1)]"
          style={{
            opacity: open ? 0 : 1,
            transform: open ? "scale(1.015)" : "scale(1)",
            clipPath: open
              ? "inset(0 0 100% 0)"
              : "inset(0 0 0% 0)",
            pointerEvents: open ? "none" : "auto",
          }}
        >
          <div className="flex items-center justify-between gap-2 border-b border-[#23262c] px-4 py-3">
            <span className="inline-flex items-center gap-2 text-micro font-semibold uppercase tracking-[0.12em] text-[#8b8f97]">
              <EyeOff className="size-3.5" aria-hidden />
              The black box · their model
            </span>
            <span className="num text-micro text-[#6f737b]">est.</span>
          </div>
          <div className="flex flex-1 flex-col gap-4 p-5">
            <div>
              <p className="num text-micro uppercase tracking-[0.12em] text-[#6f737b]">
                Cost / unit
              </p>
              <p className="cv-readout-hero mt-1 text-[1.75rem] text-[#d3d6dc]">$14.14</p>
            </div>
            <div className="rounded-[var(--radius)] border border-[#23262c] bg-[#0d0e11]">
              <LockedRow label="machine rate" width="38%" />
              <LockedRow label="labor" width="52%" />
              <LockedRow label="material" width="30%" />
              <LockedRow label="margin & overhead" width="44%" />
            </div>
            <p className="mt-auto text-sm leading-relaxed text-[#8b8f97]">
              A price with nothing behind it — a marketplace ML quote, or a suite
              that buries the math in a bill-of-process. Either way the answer is
              the same: <span className="font-semibold text-[#cdd0d6]">trust us.</span>
            </p>
          </div>
        </div>

        {/* the toggle — drive the reveal by hand, too */}
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="absolute bottom-3 right-3 z-10 inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border border-border bg-card/90 px-2.5 py-1.5 text-xs font-medium text-foreground shadow-sm backdrop-blur transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {open ? (
            <>
              <EyeOff className="size-3.5" /> Seal the box
            </>
          ) : (
            <>
              <Eye className="size-3.5" /> Trace the number
            </>
          )}
        </button>
      </div>
      <p className="mt-3 text-center text-sm text-muted-foreground">
        Same <span className="num font-medium text-foreground">$14.14</span> — but
        every driver is measured off your geometry or bound to your shop, cited,
        and editable. Click any line to see exactly how it was built.
      </p>
    </div>
  );
}
