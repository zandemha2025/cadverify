"use client";

import Link from "next/link";
import * as React from "react";
import { ShieldCheck, Server, FileSearch, ArrowRight } from "lucide-react";
import {
  PublicHeader,
  PublicNavLink,
  PublicFooter,
  PrimaryCta,
} from "@/components/ui/public-chrome";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  ProvenanceLegend,
  ProvenanceChip,
  RoutingCard,
  DfmMatrix,
  DriverBreakdown,
  ConfidenceInterval,
  CalibrationBar,
} from "@/components/glass-box";
import { DecisionPlate } from "@/components/marketing/decision-plate";
import { Eyebrow } from "@/components/marketing/datum";
import {
  ESTIMATE,
  ROUTING,
  FEASIBILITY,
  BLOCKERS,
  SHOP_RATES,
  DEFAULT_RATES,
} from "@/components/marketing/data";

/* ============================================================================
   /method — how the number is built, shown with the real product components.
   The page IS a working demonstration of the pipeline, not a description of it.
   Five stages, each one openable; every panel renders the engine's real report.
   ========================================================================== */

export default function MethodPage() {
  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <PublicHeader>
        <PublicNavLink href="/method">How it works</PublicNavLink>
        <PublicNavLink href="/docs">Docs</PublicNavLink>
      </PublicHeader>

      <main className="flex-1">
        {/* ── Intro ──────────────────────────────────────────────── */}
        <section className="border-b border-border bg-card">
          <div className="mx-auto max-w-3xl px-4 pb-14 pt-16 lg:px-8 lg:pt-20">
            <Eyebrow index="//">How it works</Eyebrow>
            <h1 className="cv-display mt-5 text-balance text-[clamp(2.25rem,5vw,3.25rem)] leading-[1.02] text-foreground">
              One file in. The whole model out.
            </h1>
            <p className="mt-6 max-w-2xl text-pretty text-lg leading-relaxed text-muted-foreground">
              A CAD file goes through five stages, and you can open every one. The
              panels below are the real product components — the same ones in the
              app — rendering the cost-truth engine&apos;s own report for one part,
              calibrated to a real shop and captured from the engine. Real output,
              not screenshots or mockups.
            </p>
          </div>
        </section>

        {/* ── The pipeline ───────────────────────────────────────── */}
        <section className="mx-auto max-w-3xl space-y-14 px-4 py-16 lg:px-8">
          <Stage
            n="01"
            title="Measure the geometry"
            blurb="We read the part itself — volume, bounding box, wall thickness, whether it's watertight. These are MEASURED facts off your CAD, the ground everything else stands on. The mesh is parsed in-process and discarded."
          >
            <Card className="cv-bezel p-5">
              <div className="flex flex-wrap items-center gap-2">
                <GeomFact label="volume" value="4.63 cm³" />
                <GeomFact label="bbox" value="21.2 × 21.4 × 21.5 mm" />
                <GeomFact label="wall" value="6.17 mm" />
                <GeomFact label="watertight" value="yes" />
              </div>
              <p className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                tagged <ProvenanceChip provenance="MEASURED" size="xs" /> — read
                directly from the geometry you uploaded.
              </p>
            </Card>
          </Stage>

          <Stage
            n="02"
            title="Route it, and say why"
            blurb="Before costing, the engine decides how the part should be made from its shape — and shows the reasoning, not just a verdict. The DFM check is named and actionable: each blocker states the measured value against the threshold and points at the offending faces."
          >
            <div className="space-y-4">
              <RoutingCard routing={ROUTING} />
              <DfmMatrix feasibility={FEASIBILITY} blockers={BLOCKERS} costPick="mjf" />
            </div>
          </Stage>

          <Stage
            n="03"
            title="Open the cost"
            blurb="Every driver is on the table, provenance-tagged and sourced, and the line items sum visibly to the unit cost — no naked totals. Click any driver to drill to its verbatim source. Anything generic is flagged DEFAULT so you can see exactly where the model is guessing."
          >
            <Card className="cv-bezel space-y-4 p-5">
              <DriverBreakdown estimate={ESTIMATE} />
              <ConfidenceInterval confidence={ESTIMATE.confidence!} />
            </Card>
          </Stage>

          <Stage
            n="04"
            title="Calibrate it to your shop"
            blurb="Bind a shop's real rates and the model re-costs to their reality. Each bound rate is tagged SHOP and sourced; every rate that isn't bound stays a visible DEFAULT. Your numbers become yours, and the gaps stay honest."
          >
            <Card className="cv-bezel flex flex-wrap items-center gap-3 p-5">
              <CalibrationBar
                shopName="Midwest Precision CNC"
                source="Shop accounting export 2026-Q2 (loaded rates + negotiated resin lots)"
                note="19 rates bound to this shop, tagged SHOP. Everything else stays DEFAULT — the gaps are visible, not hidden."
                shopRates={SHOP_RATES}
                defaultRates={DEFAULT_RATES}
              />
              <CalibrationBar shopName={null} />
            </Card>
          </Stage>

          <Stage
            n="05"
            title="Make the decision"
            blurb="The output is a choice — make by which process, and the quantity where you should tool up instead — with confidence bands, not a fake-exact price. This is the Decision Plate: cost, lead time, the honest band, and the crossover, on one machined faceplate."
          >
            <DecisionPlate animate={false} />
          </Stage>
        </section>

        {/* ── The honesty rail ───────────────────────────────────── */}
        <section className="border-y border-border bg-card py-16 lg:py-20">
          <div className="mx-auto max-w-3xl px-4 lg:px-8">
            <Eyebrow>Reading the receipts</Eyebrow>
            <h2 className="cv-display mt-4 text-balance text-[clamp(1.75rem,3.2vw,2.25rem)] leading-[1.08] text-foreground">
              Two marks tell you everything: where a number came from, and whether
              we&apos;ve earned it.
            </h2>
            <div className="mt-6 space-y-3 text-base leading-relaxed text-muted-foreground">
              <p>
                <span className="font-medium text-foreground">Provenance</span> is
                the fill of the dot. Filled means grounded — measured off your
                geometry, bound to your shop, or overridden by you. A hollow ring
                means a generic DEFAULT: we&apos;re guessing, and we&apos;re
                telling you so.
              </p>
              <p>
                <span className="font-medium text-foreground">Confidence</span> is
                the texture of the band. Hatched means assumption-based and not yet
                validated. It goes solid — and reads &ldquo;validated on N of your
                parts&rdquo; — only after real costs on your held-out parts back it.
                We never print an accuracy figure we haven&apos;t measured on real
                data.
              </p>
            </div>
            <Card className="cv-bezel mt-6 p-5">
              <Eyebrow>Provenance · the four marks</Eyebrow>
              <ProvenanceLegend className="mt-3" />
            </Card>
          </div>
        </section>

        {/* ── Security posture ───────────────────────────────────── */}
        <section className="mx-auto max-w-3xl px-4 py-16 lg:px-8 lg:py-20">
          <Eyebrow>Where it runs</Eyebrow>
          <h2 className="cv-display mt-4 text-balance text-[clamp(1.75rem,3.2vw,2.25rem)] leading-[1.08] text-foreground">
            Built for CAD-as-IP and export-controlled programs.
          </h2>
          <div className="mt-6 space-y-4">
            <PostureRow
              icon={Server}
              title="Geometry never leaves your environment"
              desc="On the local path, CAD is parsed in-process and discarded. There is no upload to a marketplace, no part library trained on your designs."
            />
            <PostureRow
              icon={ShieldCheck}
              title="Designed for the ITAR / AS9100 path"
              desc="Made to run inside a controlled environment so an aerospace or defense program can use it without exporting technical data."
            />
            <PostureRow
              icon={FileSearch}
              title="Every answer is traceable"
              desc="Provenance tags and source strings on every driver mean a cost or quality engineer can reconstruct and defend the number in a review."
            />
          </div>
        </section>

        {/* ── CTA ────────────────────────────────────────────────── */}
        <section className="bg-[#0b1220] cv-on-dark">
          <div className="mx-auto max-w-2xl px-4 py-24 text-center lg:px-8">
            <Eyebrow className="justify-center">See it on your part</Eyebrow>
            <h2 className="cv-display mt-5 text-balance text-[clamp(1.9rem,4vw,2.75rem)] leading-[1.04] text-[#f3f7fc]">
              See it on a part you choose.
            </h2>
            <p className="mx-auto mt-5 max-w-xl text-pretty text-lg leading-relaxed text-[#b7c7df]">
              Create an account to run your own part, or bring a real part and
              calibrate it to your shop.
            </p>
            <div className="mt-9 flex flex-wrap justify-center gap-3">
              <PrimaryCta size="lg" />
              <Button asChild variant="secondary" size="lg" className="!border-[#2c456b] !bg-white/5 !text-[#dce7f5] hover:!bg-white/10">
                <Link href="/login">
                  Log in
                  <ArrowRight className="size-4" />
                </Link>
              </Button>
            </div>
          </div>
        </section>
      </main>

      <PublicFooter />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
   Building blocks (marketing-local).
   ───────────────────────────────────────────────────────────────────────── */

function Stage({
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
    <div className="grid gap-5 lg:grid-cols-[7rem_1fr] lg:gap-8">
      <div className="lg:text-right">
        <span className="cv-readout-hero text-[2.75rem] leading-none text-primary/25">
          {n}
        </span>
      </div>
      <div className="space-y-5">
        <div>
          <h2 className="cv-display text-2xl text-foreground">{title}</h2>
          <p className="mt-2.5 text-pretty text-base leading-relaxed text-muted-foreground">
            {blurb}
          </p>
        </div>
        {children}
      </div>
    </div>
  );
}

function GeomFact({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-sm border border-prov-measured-border bg-prov-measured-bg px-2 py-1 text-xs">
      <span className="size-2 rounded-full bg-prov-measured" aria-hidden />
      <span className="text-foreground">{label}</span>
      <span className="num font-medium text-prov-measured">{value}</span>
    </span>
  );
}

function PostureRow({
  icon: Icon,
  title,
  desc,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  desc: string;
}) {
  return (
    <Card className="flex items-start gap-4 p-5">
      <span className="inline-flex size-9 shrink-0 items-center justify-center rounded-[var(--radius)] bg-accent-subtle text-accent-text">
        <Icon className="size-[18px]" />
      </span>
      <div>
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{desc}</p>
      </div>
    </Card>
  );
}
