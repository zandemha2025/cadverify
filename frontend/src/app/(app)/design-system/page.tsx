"use client";

/**
 * Design-system showcase — the 2026 glass-box language, rendered against the
 * cost-truth engine's REAL report (object.stl · Midwest Precision CNC). Every
 * surface below is a working component from src/components/glass-box, not a
 * mockup. Toggle the theme (top-right) and the role lens to see light/dark and
 * the role-aware defaults. This page is also the build proof.
 */

import * as React from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import type { Breakeven } from "@/lib/breakeven";
import type { CostAssumption } from "@/lib/api";
import {
  ProvenanceLegend,
  ProvenanceChip,
  NumberReadout,
  ConfidenceInterval,
  ConfidenceChip,
  DriverBreakdown,
  AssumptionGrid,
  ProcessComparison,
  RoutingCard,
  DfmMatrix,
  CalibrationBar,
  RoleLens,
  type RoleId,
  roleById,
  DecisionHeadline,
  RedesignBanner,
  CrossoverChart,
} from "@/components/glass-box";
import {
  ESTIMATE,
  ASSUMPTIONS,
  ROUTING,
  FEASIBILITY,
  BLOCKERS,
  COMPARE_ROWS,
  SHOP_RATES,
  DEFAULT_RATES,
} from "./fixture";

// make-vs-buy curves fitted from the engine's own reported unit costs.
const BREAKEVEN: Breakeven = {
  curves: [
    { process: "mjf", material: "PP", fixedAmort: 37.27, variablePerUnit: 10.41, dfmReady: true, leadLow: 5.6, leadHigh: 10.4, points: [{ qty: 10, unit: 14.14 }, { qty: 1000, unit: 10.45 }] },
    { process: "injection_molding", material: "PP", fixedAmort: 7800, variablePerUnit: 6.45, dfmReady: false, leadLow: 25, leadHigh: 40, points: [{ qty: 10, unit: 786.45 }, { qty: 1000, unit: 14.25 }] },
    { process: "cnc_turning", material: "6061-T6", fixedAmort: 35.35, variablePerUnit: 26.88, dfmReady: true, leadLow: 7, leadHigh: 12, points: [{ qty: 10, unit: 30.42 }, { qty: 1000, unit: 26.92 }] },
  ],
  qtyMin: 1,
  qtyMax: 10000,
  crossoverQty: 1962,
  makeNowProcess: "mjf",
  toolingProcess: "injection_molding",
};

function Section({
  n,
  title,
  blurb,
  children,
}: {
  n: string;
  title: string;
  blurb: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4 border-t border-border pt-8">
      <div className="flex items-baseline gap-3">
        <span className="num text-micro font-semibold text-accent-text">{n}</span>
        <div>
          <h2 className="text-xl font-semibold text-foreground">{title}</h2>
          <p className="mt-0.5 max-w-2xl text-sm text-muted-foreground">{blurb}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

const SWATCHES: { label: string; cls: string; note: string }[] = [
  { label: "canvas", cls: "bg-canvas", note: "app bg" },
  { label: "card", cls: "bg-card", note: "surface" },
  { label: "muted", cls: "bg-muted", note: "inset" },
  { label: "primary", cls: "bg-primary", note: "steel-blue accent" },
  { label: "prov-shop", cls: "bg-prov-shop", note: "calibration teal" },
  { label: "pass", cls: "bg-pass", note: "pass" },
  { label: "warn", cls: "bg-warn", note: "advisory" },
  { label: "fail", cls: "bg-fail", note: "required" },
];

const TYPE_ROWS: { cls: string; label: string; sample: string }[] = [
  { cls: "readout text-readout font-semibold text-foreground", label: "readout / 40 mono", sample: "$14.14" },
  { cls: "text-display font-semibold text-foreground", label: "display / 28 sans", sample: "The decision, not the dollar" },
  { cls: "text-base text-foreground", label: "body / 16 sans", sample: "Every number carries its lineage." },
  { cls: "num text-sm text-foreground", label: "data / 14 mono", sample: "0.0682 hr × $30/hr ÷ 0.8" },
  { cls: "text-micro text-muted-foreground", label: "micro / 11", sample: "provenance source string" },
];

export default function DesignSystemPage() {
  const [role, setRole] = React.useState<RoleId>("cost");
  const [assumptions, setAssumptions] = React.useState<CostAssumption[]>(ASSUMPTIONS);
  const active = roleById(role);

  const overrideAssumption = (name: string, value: number) => {
    setAssumptions((prev) =>
      prev.map((a) =>
        a.name === name
          ? { ...a, value, provenance: "USER", source: "Overridden in this session" }
          : a
      )
    );
    toast.success(`Override applied — ${name} re-tagged USER, report re-runs`);
  };

  return (
    <div className="mx-auto max-w-5xl space-y-8 pb-16">
      {/* ── Masthead ─────────────────────────────────────────────── */}
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <span className="cv-eyebrow">CadVerify · design language 2026</span>
          <h1 className="mt-1.5 text-display-xl font-semibold leading-tight text-foreground">
            The glass box is the hero.
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            A number is never naked: it carries its lineage (MEASURED · SHOP · USER · DEFAULT) and its
            confidence band. These are working components, rendered against the cost-truth engine&apos;s
            real output.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <RoleLens value={role} onChange={setRole} />
          <ThemeToggle />
        </div>
      </header>

      <Card className="flex flex-wrap items-center gap-x-6 gap-y-2 p-4">
        <span className="cv-eyebrow">Active lens</span>
        <span className="text-sm text-foreground">
          <span className="font-semibold">{active.label}</span> · {active.verb} · lands on{" "}
          <span className="font-medium text-accent-text">{active.lands}</span> · density{" "}
          <span className="num">{active.density}</span> · glass box{" "}
          {active.disclosed ? "open" : "collapsed"} by default
        </span>
      </Card>

      {/* ── 01 Foundations ───────────────────────────────────────── */}
      <Section n="01" title="Foundations" blurb="Slate foundation, one steel-blue accent, calibration teal for SHOP, strict semantic status. Two type voices: a humanist sans for the answer, a tabular mono for the evidence.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Card className="p-4">
            <span className="cv-eyebrow">Color</span>
            <div className="mt-3 grid grid-cols-4 gap-3">
              {SWATCHES.map((s) => (
                <div key={s.label} className="space-y-1">
                  <div className={cn("h-10 rounded-[var(--radius)] border border-border", s.cls)} />
                  <p className="num text-micro text-foreground">{s.label}</p>
                  <p className="text-micro text-muted-foreground">{s.note}</p>
                </div>
              ))}
            </div>
          </Card>
          <Card className="p-4">
            <span className="cv-eyebrow">Type · two voices</span>
            <div className="mt-3 space-y-3">
              {TYPE_ROWS.map((t) => (
                <div key={t.label} className="flex items-baseline justify-between gap-4">
                  <span className={cn("truncate", t.cls)}>{t.sample}</span>
                  <span className="shrink-0 text-micro text-muted-foreground">{t.label}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
        <Card className="p-4">
          <span className="cv-eyebrow">Provenance · the atom — filled = grounded, hollow = a guess</span>
          <ProvenanceLegend className="mt-3" />
        </Card>
      </Section>

      {/* ── 02 The number, never naked ───────────────────────────── */}
      <Section n="02" title="The number, never naked" blurb="The hero metric is an instrument readout with its confidence band beneath. The band is hatched while assumption-based and goes solid only when validated on real parts — we never print a fabricated ±X%.">
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-5">
            <NumberReadout
              label="Cost / unit · MJF (PP)"
              value="$14.14"
              accent
              confidence={ESTIMATE.confidence}
            />
          </Card>
          <Card className="space-y-4 p-5">
            <ConfidenceInterval confidence={ESTIMATE.confidence!} />
            <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
              <ConfidenceChip confidence={ESTIMATE.confidence!} />
              <ProvenanceChip provenance="SHOP" />
              <ProvenanceChip provenance="DEFAULT" />
              <ProvenanceChip provenance="MEASURED" withLabel={false} />
              <ProvenanceChip provenance="USER" />
            </div>
          </Card>
        </div>
      </Section>

      {/* ── 03 Glass box ─────────────────────────────────────────── */}
      <Section n="03" title="Glass box · the open model" blurb="Every driver provenance-tagged and sourced; the Σ line-items = unit-cost check shown. Click any driver to drill inline to its verbatim source and override it. Every assumption is editable — overriding re-tags it USER.">
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="space-y-3 p-5">
            <span className="cv-eyebrow">Cost drivers · MJF @ qty 10</span>
            <DriverBreakdown
              estimate={ESTIMATE}
              onOverride={(d) => toast.success(`Override ${d.name} — re-tags USER, re-runs`)}
            />
          </Card>
          <Card className="space-y-3 p-5">
            <span className="cv-eyebrow">Assumptions · every one editable</span>
            <AssumptionGrid assumptions={assumptions} onOverride={overrideAssumption} />
          </Card>
        </div>
      </Section>

      {/* ── 04 The decision ──────────────────────────────────────── */}
      <Section n="04" title="The decision, not the dollar" blurb="Make-vs-buy + the quantity crossover is the hero — the slider live-flips the recommended process at the crossover. When the tooling route currently fails DFM, the honesty banner says so.">
        <Card className="overflow-hidden">
          <DecisionHeadline
            title="Make by MJF (PP)"
            dfmReady
            sentence="MJF wins below ~1,962 units; tool up with injection molding above it."
          />
          <div className="space-y-4 p-5">
            <div className="grid grid-cols-3 gap-4">
              <NumberReadout label="Cost / unit" value="$14.14" size="md" accent />
              <NumberReadout label="Lead time" value="5.6–10.4" unit="days" size="md" />
              <NumberReadout label="Crossover" value="1,962" unit="units" size="md" />
            </div>
            <CrossoverChart breakeven={BREAKEVEN} qty={500} recommendedProcess="mjf" />
            <RedesignBanner
              process="Injection molding"
              blocker="1 sidewall < 1.0° draft"
              onSeeRouting={() => toast("Jump to Routing & DFM")}
            />
          </div>
        </Card>
      </Section>

      {/* ── 05 Compare ───────────────────────────────────────────── */}
      <Section n="05" title="Compare · the decision board" blurb="The Sourcing surface: process × shop, every cell banded, the divergent driver surfaced as the negotiation lever. Same part, two calibrations — the per-shop pillar made literal.">
        <ProcessComparison
          shopA="Midwest Precision CNC"
          shopB="Shenzhen Contract Mfg"
          qty={1000}
          rows={COMPARE_ROWS}
          onDrill={(p, s) => toast(`Open glass box · ${p} · shop ${s.toUpperCase()}`)}
          lever={
            <>
              <span className="num font-medium">labor_rate $52/hr</span> (Midwest) vs{" "}
              <span className="num font-medium">$14/hr</span> (Shenzhen) — &quot;your setup implies ½
              our expected rate for this machine class.&quot;
            </>
          }
        />
      </Section>

      {/* ── 06 Routing & DFM ─────────────────────────────────────── */}
      <Section n="06" title="Routing & DFM · is it made the right way" blurb="The geometric routing card foregrounds the engine's reasoning paragraph over the measured drivers that decided it; the DFM matrix is actionable — each blocker links to geometry.">
        <div className="space-y-4">
          <RoutingCard routing={ROUTING} />
          <DfmMatrix
            feasibility={FEASIBILITY}
            blockers={BLOCKERS}
            costPick="mjf"
            onHighlight={(p) => toast(`Highlight ${p} blocker on the 3D part`)}
          />
        </div>
      </Section>

      {/* ── 07 Calibration ───────────────────────────────────────── */}
      <Section n="07" title="Calibration · your numbers become yours" blurb="Per-shop calibration as an always-on fact about the view. Expand to see which rates are bound (SHOP) and which are still generic (DEFAULT) — the gaps are visible. The not-calibrated state turns the gap into the call to action.">
        <Card className="flex flex-wrap items-center gap-4 p-5">
          <CalibrationBar
            shopName="Midwest Precision CNC"
            source="Shop accounting export 2026-Q2 (loaded rates + negotiated resin lots)"
            note="19 rates bound to this shop, tagged SHOP. Everything else stays DEFAULT — the gaps are visible, not hidden."
            shopRates={SHOP_RATES}
            defaultRates={DEFAULT_RATES}
            onSwap={() => toast("Swap shop → re-cost")}
            onOpenProfile={() => toast("Open shop profile JSON")}
            onNewCalibration={() => toast("New calibration")}
          />
          <CalibrationBar shopName={null} onSwap={() => toast("Choose a shop")} />
        </Card>
      </Section>
    </div>
  );
}
