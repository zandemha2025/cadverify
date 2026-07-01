"use client";

import Link from "next/link";
import * as React from "react";
import * as Slider from "@radix-ui/react-slider";
import { ShieldCheck, Server, FileSearch, Sigma, ArrowRight } from "lucide-react";
import {
  PublicHeader,
  PublicNavLink,
  PublicFooter,
  PrimaryCta,
} from "@/components/ui/public-chrome";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  ConfidenceInterval,
  ProcessComparison,
  CalibrationBar,
  RoutingCard,
  DfmMatrix,
  CrossoverChart,
} from "@/components/glass-box";
import { DecisionPlate } from "@/components/marketing/decision-plate";
import { BlackBoxReveal } from "@/components/marketing/black-box-reveal";
import { Eyebrow } from "@/components/marketing/datum";
import {
  ESTIMATE,
  ROUTING,
  FEASIBILITY,
  BLOCKERS,
  BREAKEVEN,
  COMPARE_ROWS,
  SHOP_RATES,
  DEFAULT_RATES,
} from "@/components/marketing/data";
import { posToQty, qtyToPos, unitCostAt } from "@/lib/breakeven";

/* ============================================================================
   CadVerify marketing homepage (sole owner of "/").
   Identity: "a finance-grade instrument panel with a machine-shop soul."

   COMPOSITION: warm machinist-paper LIGHT is the dominant canvas; blueprint-
   twilight is punctuation — the hero plate, ONE candid dark band, the close.
   The page is a curated light↔dark rhythm (`.cv-paper` / `.cv-twilight` lock
   the palette per section), not a document that inverts with the OS theme.
   Every number is the engine's REAL report; no fabricated price or accuracy.
   ========================================================================== */

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <PublicHeader>
        <PublicNavLink href="/method">How it works</PublicNavLink>
        <PublicNavLink href="/docs">Docs</PublicNavLink>
      </PublicHeader>

      <main className="flex-1">
        {/* ── §1 HERO — the one-time blueprint-twilight field (dark instrument) ─ */}
        <section className="cv-twilight cv-hero-field cv-on-dark border-b border-[#1a2742]">
          <div className="mx-auto grid max-w-screen-xl items-center gap-12 px-6 py-24 lg:grid-cols-[1fr_minmax(0,29rem)] lg:gap-16 lg:px-8 lg:py-32">
            <div>
              <Eyebrow>Should-cost you can open</Eyebrow>
              <h1 className="cv-display mt-6 text-[clamp(2.6rem,6.4vw,3.9rem)] leading-[1.01] text-[#f3f7fc]">
                Know what the part
                <br />
                should cost.{" "}
                <span className="text-[#6fbcef]">And&nbsp;why.</span>
              </h1>
              <p className="mt-6 max-w-lg text-pretty text-lg leading-relaxed text-[#b7c7df]">
                Drop in a CAD file and get the manufacturing decision — which
                process to make it by, and the quantity where you tool up — with
                every cost driver measured, sourced, and editable. Incumbents hand
                you a number and ask for trust. We hand you the receipts.
              </p>
              <div className="mt-9 flex flex-wrap items-center gap-3">
                <PrimaryCta size="lg" />
                <Link
                  href="/method"
                  className="inline-flex h-11 items-center gap-2 rounded-[var(--radius-sm)] border px-5 text-sm font-medium text-[#dce7f5] transition-colors hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3fa3e8]"
                  style={{ borderColor: "#2c456b" }}
                >
                  See how the number is built
                  <ArrowRight className="size-4" />
                </Link>
              </div>
              <div className="mt-12 flex items-center gap-2.5 border-t border-[#1c2a44] pt-5">
                <span
                  aria-hidden
                  className="h-3 w-[2px] rounded-[1px] bg-[#3fa3e8]"
                />
                <p className="num text-micro uppercase tracking-[0.16em] text-[#8aa2c2]">
                  Built for manufacturing · automotive · aerospace cost teams
                </p>
              </div>
            </div>

            <div className="w-full lg:justify-self-end">
              <DecisionPlate />
            </div>
          </div>
        </section>

        {/* ── §2 THE NUMBER, TRACED — black-box → glass-box reveal (on paper) ──
            A dramatic dark→light dissolve: the obsidian box opens into a bright
            cyanotype glass box. Centered, generous, one device. ────────────── */}
        <section className="cv-paper border-b border-border bg-canvas py-24 lg:py-32">
          <div className="mx-auto max-w-screen-xl px-6 lg:px-8">
            <SectionHeading
              align="center"
              eyebrow="The number, traced"
              title="Watch the black box become a glass box."
              blurb="The incumbent hands you a price over locked rows. The identical $14.14, traced, opens into its provenance-tagged driver stack — summing, visibly, to the unit cost. Same number; one of them shows its work."
            />
            <div className="mt-14">
              <BlackBoxReveal />
            </div>
          </div>
        </section>

        {/* ── §3 WHY INCUMBENTS HIDE IT — the comparison, de-densified ───────── */}
        <section className="cv-paper border-b border-border bg-card py-24 lg:py-28">
          <div className="mx-auto max-w-screen-xl px-6 lg:px-8">
            <SectionHeading
              eyebrow="Why we're different"
              title="Both incumbents hide the model. For opposite reasons."
              blurb="A marketplace hides its price because it is selling its own capacity. A cost suite buries the math in a bill-of-process only a trained cost engineer can read. We expose the thing they both bury."
            />
            <div className="mt-12">
              <IncumbentCompare />
            </div>
          </div>
        </section>

        {/* ── §4 PER-SHOP CALIBRATION — asymmetric: story left, board right ──── */}
        <section className="cv-paper border-b border-border bg-canvas py-24 lg:py-28">
          <div className="mx-auto grid max-w-screen-xl gap-12 px-6 lg:grid-cols-[0.85fr_1fr] lg:items-center lg:gap-16 lg:px-8">
            <div>
              <SectionHeading
                eyebrow="Per-shop calibration"
                title="Your numbers become yours."
                blurb="Bind a shop's real labor, machine and material rates and the whole model re-costs to their reality — every bound rate tagged SHOP and sourced, every gap left as a visible DEFAULT."
              />
              <div className="mt-8">
                <CalibrationBar
                  shopName="Midwest Precision CNC"
                  source="Shop accounting export 2026-Q2 (loaded rates + negotiated resin lots)"
                  note="19 rates bound to this shop, tagged SHOP. Everything else stays DEFAULT — the gaps are visible, not hidden."
                  shopRates={SHOP_RATES}
                  defaultRates={DEFAULT_RATES}
                />
                <p className="mt-4 max-w-md text-sm leading-relaxed text-muted-foreground">
                  The same part, two shops. Negotiate from the driver that
                  diverges — not the total.
                </p>
              </div>
            </div>
            <ProcessComparison
              shopA="Midwest Precision CNC"
              shopB="Shenzhen Contract Mfg"
              qty={1000}
              rows={CALIBRATION_ROWS}
              lever={
                <>
                  <span className="num font-medium">labor_rate $52/hr</span>{" "}
                  (Midwest) vs <span className="num font-medium">$14/hr</span>{" "}
                  (Shenzhen).
                </>
              }
            />
          </div>
        </section>

        {/* ── §5 MAKE-VS-BUY CROSSOVER — the live dial, on a warm sunken panel ─ */}
        <section className="cv-paper border-b border-border bg-card-raised py-24 lg:py-28">
          <div className="mx-auto max-w-screen-xl px-6 lg:px-8">
            <SectionHeading
              align="center"
              eyebrow="Where the decision changes"
              title="Turn the quantity dial. Watch the recommendation flip."
              blurb="The hero output isn't a price — it's a choice, and the quantity where it changes. Drag quantity and the recommended process flips at the crossover. Above it, the tooling route is shown as 'if redesigned,' never a current quote."
            />
            <div className="mx-auto mt-12 max-w-3xl">
              <CrossoverExplorer />
            </div>
          </div>
        </section>

        {/* ── §6 HONEST BY CONSTRUCTION — the candid DARK band (twilight) ────── */}
        <section className="cv-twilight cv-on-dark border-b border-[#1a2742] bg-canvas py-24 lg:py-32">
          <div className="mx-auto grid max-w-screen-xl gap-14 px-6 lg:grid-cols-[1.05fr_0.95fr] lg:items-center lg:px-8">
            <div>
              <Eyebrow>The honest part</Eyebrow>
              <h2 className="cv-display mt-5 text-balance text-[clamp(2rem,3.6vw,2.65rem)] leading-[1.05] text-foreground">
                We won&apos;t quote an accuracy we haven&apos;t earned.
              </h2>
              <div className="mt-6 space-y-4 text-base leading-relaxed text-muted-foreground">
                <p>
                  Anyone can print &ldquo;±5% accurate&rdquo; on a slide. We
                  don&apos;t. Until we&apos;ve costed your real parts against your
                  invoices, every estimate ships labeled{" "}
                  <span className="font-medium text-foreground">
                    assumption-based, not yet validated
                  </span>{" "}
                  — a band from the assumptions it leaned on, with{" "}
                  <span className="num text-foreground">n=0</span> ground-truth
                  samples stated plainly, not a measured error rate.
                </p>
                <p>
                  Run your parts through it, send back the real costs, and the
                  band flips from hatched to solid:{" "}
                  <span className="font-medium text-foreground">
                    validated on N of your parts.
                  </span>{" "}
                  That&apos;s the only place a validated number appears — measured
                  on your held-out parts, never ours.
                </p>
              </div>
              <Button asChild variant="link" size="md" className="mt-7 px-0 text-[#6fbcef]">
                <Link href="/method">
                  See how the number is built
                  <ArrowRight className="size-4" />
                </Link>
              </Button>
            </div>
            <Card className="cv-bezel p-6 lg:p-7">
              <Eyebrow>Confidence · rendered verbatim</Eyebrow>
              <div className="mt-5">
                <ConfidenceInterval confidence={ESTIMATE.confidence!} />
              </div>
              <p className="mt-6 border-t border-border pt-4 text-sm text-muted-foreground">
                The band is{" "}
                <span className="font-medium text-foreground">hatched</span> while
                it&apos;s assumption-based — it literally looks provisional. It
                goes solid only when real residuals back it.
              </p>
            </Card>
          </div>
        </section>

        {/* ── §7 ROUTED BY GEOMETRY + DFM (on paper) ─────────────────────────── */}
        <section className="cv-paper border-b border-border bg-canvas py-24 lg:py-28">
          <div className="mx-auto max-w-screen-xl px-6 lg:px-8">
            <SectionHeading
              eyebrow="Routed by geometry, said out loud"
              title="It decides how the part is made — and shows its reasoning."
              blurb="Before costing, the engine routes the part from its shape and tells you why. DFM is named and actionable: each blocker states the measured value against the threshold, so a redesign call rests on the geometry."
            />
            <div className="mt-12 grid gap-5 lg:grid-cols-2">
              <RoutingCard routing={ROUTING} />
              <DfmMatrix feasibility={FEASIBILITY} blockers={BLOCKERS} costPick="mjf" />
            </div>
          </div>
        </section>

        {/* ── §8 BUILT FOR REGULATED HARDWARE — trust + the facts we'll defend ─ */}
        <section className="cv-paper border-b border-border bg-card-raised py-24 lg:py-28">
          <div className="mx-auto max-w-screen-xl px-6 lg:px-8">
            <SectionHeading
              eyebrow="Built for regulated hardware"
              title="Credible to the people who have to defend it."
              blurb="For an aerospace, automotive or defense program, where the model runs and what leaves your network matter as much as the answer."
            />
            <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              <TrustItem
                icon={Server}
                title="Your IP stays put"
                desc="CAD is parsed in-process and discarded. The geometry never leaves your environment — zero network egress on the local path."
              />
              <TrustItem
                icon={ShieldCheck}
                title="On the ITAR / AS9100 path"
                desc="Runs inside a controlled environment, so an export-controlled program can cost parts without sending them to a marketplace."
              />
              <TrustItem
                icon={FileSearch}
                title="Every number is auditable"
                desc="Each driver carries its provenance and a source string. A cost engineer can trace the answer to its inputs and defend it in review."
              />
              <TrustItem
                icon={Sigma}
                title="The arithmetic is shown"
                desc="Line items sum visibly to the unit cost. No naked totals, no black-box rollups — the math is on screen, not in a footnote."
              />
            </div>

            {/* the only numbers we'll stand behind — quiet mono facts, not a
                second monumental stamp */}
            <div className="mt-12">
              <Eyebrow>The only numbers we&apos;ll stand behind</Eyebrow>
              <div className="mt-5 grid gap-px overflow-hidden rounded-[var(--radius-lg)] border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
                <StandBehind
                  value="21"
                  label="process families"
                  caption="routed & costed — additive, CNC, molding, casting, sheet"
                />
                <StandBehind
                  value="4"
                  label="provenance marks"
                  caption="MEASURED · SHOP · USER · DEFAULT on every driver"
                />
                <StandBehind
                  value="Σ"
                  label="totals reconcile"
                  caption="line items sum to the unit cost — no naked rollups"
                />
                <StandBehind
                  value="0"
                  label="faked accuracy"
                  caption="never a ±% we haven't measured on real parts"
                />
              </div>
            </div>
          </div>
        </section>

        {/* ── §9 CLOSING CTA — twilight, confident, no repeated atmosphere ───── */}
        <section className="cv-twilight cv-on-dark bg-canvas">
          <div className="mx-auto max-w-screen-xl px-6 py-28 lg:px-8 lg:py-32">
            <div className="mx-auto max-w-2xl text-center">
              <Eyebrow className="justify-center">Bring your hardest part</Eyebrow>
              <h2 className="cv-display mt-6 text-balance text-[clamp(2.1rem,4.2vw,3rem)] leading-[1.03] text-foreground">
                Calibrate it to your shop. See where we&apos;re still guessing.
              </h2>
              <p className="mx-auto mt-6 max-w-xl text-pretty text-lg leading-relaxed text-muted-foreground">
                We&apos;ll cost a part you choose against your real rates, show
                every driver, and tell you — honestly — which ones are still
                generic defaults. Then we validate on your held-out parts.
              </p>
              <div className="mt-10 flex flex-wrap justify-center gap-3">
                <PrimaryCta size="lg" />
                <Link
                  href="/method"
                  className="inline-flex h-11 items-center gap-2 rounded-[var(--radius-sm)] border px-5 text-sm font-medium text-[#dce7f5] transition-colors hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3fa3e8]"
                  style={{ borderColor: "#2c456b" }}
                >
                  How it works
                </Link>
              </div>
            </div>
          </div>
        </section>
      </main>

      <PublicFooter />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
   Section + content building blocks (marketing-local).
   ───────────────────────────────────────────────────────────────────────── */

function SectionHeading({
  eyebrow,
  title,
  blurb,
  align = "left",
}: {
  eyebrow: string;
  title: string;
  blurb: string;
  align?: "left" | "center";
}) {
  const centered = align === "center";
  return (
    <div
      className={
        centered ? "mx-auto max-w-2xl text-center" : "max-w-2xl"
      }
    >
      <Eyebrow className={centered ? "justify-center" : undefined}>
        {eyebrow}
      </Eyebrow>
      <h2 className="cv-display mt-4 text-balance text-[clamp(1.8rem,3.3vw,2.5rem)] leading-[1.07] text-foreground">
        {title}
      </h2>
      <p
        className={
          centered
            ? "mx-auto mt-5 max-w-xl text-pretty text-base leading-relaxed text-muted-foreground"
            : "mt-5 text-pretty text-base leading-relaxed text-muted-foreground"
        }
      >
        {blurb}
      </p>
    </div>
  );
}

/** Calibration board — 3 illustrative processes (de-densified from the full
 *  five), so the section reads as a decision, not a spreadsheet dump. */
const CALIBRATION_ROWS = COMPARE_ROWS.filter((r) =>
  ["mjf", "cnc_turning", "injection_molding"].includes(r.process)
);

/* ── §5 the live make-vs-buy crossover dial ─────────────────────────────── */
function CrossoverExplorer() {
  const b = BREAKEVEN;
  const [qty, setQty] = React.useState(500);
  const crossover = b.crossoverQty ?? 1962;
  const belowCrossover = qty <= crossover;
  // Recommended curve: make-now below the crossover; the tooling route above —
  // honestly conditional ("if redesigned"), since IM currently fails DFM.
  const recProcess = belowCrossover ? b.makeNowProcess : b.toolingProcess ?? b.makeNowProcess;
  const makeCurve = b.curves.find((c) => c.process === b.makeNowProcess)!;
  const toolCurve = b.curves.find((c) => c.process === b.toolingProcess);
  const makeUnit = unitCostAt(makeCurve, qty);
  const toolUnit = toolCurve ? unitCostAt(toolCurve, qty) : null;

  return (
    <Card className="cv-bezel overflow-hidden">
      {/* the verdict header — flips at the crossover */}
      <div className="border-b border-accent-subtle-border bg-accent-subtle/70 px-5 py-4">
        <Eyebrow>Recommended at qty {qty.toLocaleString()}</Eyebrow>
        <div className="mt-2.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 className="cv-display text-2xl text-foreground">
            {belowCrossover ? "Make by MJF (PP)" : "Tool up: Injection Molding"}
          </h3>
          {!belowCrossover && (
            <span className="num rounded-[var(--radius-xs)] border border-warn-border bg-warn-bg px-1.5 py-0.5 text-micro font-medium text-warn">
              if redesigned · 1 sidewall &lt; 1.0° draft
            </span>
          )}
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          {belowCrossover ? (
            <>
              MJF wins below{" "}
              <span className="num text-foreground">
                ~{crossover.toLocaleString()}
              </span>{" "}
              units. Tooling&apos;s fixed cost hasn&apos;t paid off yet at this
              volume.
            </>
          ) : (
            <>
              Above{" "}
              <span className="num text-foreground">
                ~{crossover.toLocaleString()}
              </span>{" "}
              units the molding tool amortizes and wins — but the part fails draft
              today, so this is a redesign target, not a quote.
            </>
          )}
        </p>
      </div>

      <div className="space-y-6 p-5 lg:p-6">
        {/* live unit-cost readouts per route */}
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius)] border border-border bg-border">
          <RouteReadout
            label="MJF (PP) · make now"
            value={makeUnit}
            active={belowCrossover}
          />
          <RouteReadout
            label="Injection molding · tooled"
            value={toolUnit}
            active={!belowCrossover}
            conditional
          />
        </div>

        {/* the dial */}
        <div>
          <div className="mb-2.5 flex items-center justify-between">
            <span className="num text-micro uppercase tracking-[0.14em] text-muted-foreground">
              Quantity
            </span>
            <span className="num text-sm font-semibold text-accent-text">
              {qty.toLocaleString()} units
            </span>
          </div>
          <Slider.Root
            className="relative flex h-6 w-full touch-none select-none items-center"
            value={[qtyToPos(b, qty) * 1000]}
            min={0}
            max={1000}
            step={1}
            onValueChange={([pos]) => setQty(posToQty(b, pos / 1000))}
            aria-label="Quantity"
          >
            <Slider.Track className="relative h-1.5 w-full grow rounded-full bg-band-track">
              <Slider.Range className="absolute h-full rounded-full bg-primary" />
            </Slider.Track>
            <Slider.Thumb className="block size-5 rounded-full border-2 border-primary bg-card shadow-sm transition-transform hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
          </Slider.Root>
          <div className="num mt-2 flex justify-between text-micro text-subtle-foreground">
            <span>1</span>
            <span>crossover ≈ {crossover.toLocaleString()}</span>
            <span>10k</span>
          </div>
        </div>

        <CrossoverChart breakeven={b} qty={qty} recommendedProcess={recProcess} />
      </div>
    </Card>
  );
}

function RouteReadout({
  label,
  value,
  active,
  conditional = false,
}: {
  label: string;
  value: number | null;
  active: boolean;
  conditional?: boolean;
}) {
  return (
    <div className={active ? "bg-accent-subtle/50 px-4 py-3.5" : "bg-card px-4 py-3.5"}>
      <p className="num text-micro uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-1.5 flex items-baseline gap-1">
        <span
          className={`readout text-2xl font-semibold leading-none ${
            active ? "text-accent-text" : "text-foreground/70"
          }`}
        >
          {value == null
            ? "—"
            : `$${value.toLocaleString("en-US", {
                maximumFractionDigits: value < 100 ? 2 : 0,
              })}`}
        </span>
        <span className="num text-xs text-muted-foreground">/unit</span>
      </p>
      {conditional && (
        <p className="num mt-0.5 text-micro text-warn">⚠ if redesigned</p>
      )}
    </div>
  );
}

/** A quiet "stand-behind" fact: mono value (not the Archivo monument) so the
 *  hero plate keeps the only monumental number on the page. */
function StandBehind({
  value,
  label,
  caption,
}: {
  value: string;
  label: string;
  caption: string;
}) {
  return (
    <div className="bg-card px-5 py-6">
      <p className="num text-3xl font-semibold leading-none text-accent-text">
        {value}
      </p>
      <p className="mt-3 text-sm font-semibold text-foreground">{label}</p>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
        {caption}
      </p>
    </div>
  );
}

/** The skeptic's comparison — fewer rows, more air, a clear hierarchy: the
 *  dimension reads as a label, the incumbents stay muted, CadVerify is the lit
 *  column. Elegant, not a spreadsheet. */
const COMPARE_DIMENSIONS: {
  dim: string;
  marketplace: string;
  suite: string;
  cadverify: string;
}[] = [
  {
    dim: "The number",
    marketplace: "An ML price, unauditable by design",
    suite: "Physics-based, buried in a bill-of-process",
    cadverify: "Every driver visible, sourced, summing to the unit cost",
  },
  {
    dim: "The hero output",
    marketplace: "A price and a lead time",
    suite: "A cost spreadsheet",
    cadverify: "The decision — make-vs-buy and the quantity crossover",
  },
  {
    dim: "DFM feedback",
    marketplace: "A badge, then chat an expert (~2 days)",
    suite: "Deep checks on an expert-only surface",
    cadverify: "Named and actionable: the failing threshold and the value that passes",
  },
  {
    dim: "How it earns trust",
    marketplace: "Asserted",
    suite: "Asserted, then gated behind a role",
    cadverify: "Demonstrated — validated on your parts, never a fabricated %",
  },
];

function IncumbentCompare() {
  return (
    <div className="overflow-x-auto rounded-[var(--radius-lg)] border border-border bg-card shadow-sm">
      <div className="min-w-[46rem]">
        {/* header band */}
        <div className="grid grid-cols-[1.1fr_1fr_1fr_1.25fr] border-b border-border-strong">
          <div aria-hidden />
          <ColHead title="Instant-quote marketplace" sub="Xometry · Protolabs" />
          <ColHead title="Cost-engineering suite" sub="aPriori · Teamcenter" />
          <div className="border-l border-accent-subtle-border bg-accent-subtle/50 px-5 py-5">
            <span className="cv-display block text-lg leading-none text-accent-text">
              CadVerify
            </span>
            <span className="num mt-1.5 block text-micro text-muted-foreground">
              the glass box
            </span>
          </div>
        </div>
        {/* rows */}
        {COMPARE_DIMENSIONS.map((r, i) => (
          <div
            key={r.dim}
            className={`grid grid-cols-[1.1fr_1fr_1fr_1.25fr] ${
              i < COMPARE_DIMENSIONS.length - 1 ? "border-b border-border" : ""
            }`}
          >
            <div className="px-5 py-6">
              <span className="text-sm font-semibold text-foreground">{r.dim}</span>
            </div>
            <div className="px-5 py-6 text-sm leading-relaxed text-muted-foreground">
              {r.marketplace}
            </div>
            <div className="px-5 py-6 text-sm leading-relaxed text-muted-foreground">
              {r.suite}
            </div>
            <div className="border-l border-accent-subtle-border bg-accent-subtle/30 px-5 py-6 text-sm font-medium leading-relaxed text-foreground">
              {r.cadverify}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ColHead({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="px-5 py-5">
      <span className="block text-sm font-semibold text-foreground">{title}</span>
      <span className="num mt-1.5 block text-micro text-muted-foreground">{sub}</span>
    </div>
  );
}

function TrustItem({
  icon: Icon,
  title,
  desc,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  desc: string;
}) {
  return (
    <Card className="p-5">
      <span className="inline-flex size-9 items-center justify-center rounded-[var(--radius)] bg-accent-subtle text-accent-text">
        <Icon className="size-[18px]" />
      </span>
      <h3 className="mt-4 text-sm font-semibold text-foreground">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{desc}</p>
    </Card>
  );
}
