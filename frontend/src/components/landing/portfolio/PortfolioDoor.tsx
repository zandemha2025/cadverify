"use client";

/**
 * PortfolioDoor — Door C's landing (D5 FE-5): the MRO / portfolio owner's
 * EXCEPTION-FIRST triage queue over the parts they actually have (their real
 * saved should-cost decisions). Not a full grid — the engine triages before it
 * is asked (D1 persona 3): three ranked exception queues lead, each drills to a
 * cohort, each cohort row opens that part's saved decision (the FE-2 part hero).
 *
 *   DFM-required · Running on guesses · Crossover-fragile
 *
 * Every queue count, every pulse KPI and every savings figure is computed (pure,
 * `lib/portfolio`) over the HYDRATED parts — real engine fields, no fabricated
 * portfolio-scale number. The savings pipeline is HONEST-THIN: portfolio-scale
 * rolled-up $ is W3 (not built) and stated plainly; what's shown is the real
 * per-part redesign delta where the engine offers a cheaper alternative.
 *
 * This surface only ever mounts under `NEXT_PUBLIC_STAGE_UI` (via LandingRouter),
 * so flag-off never ships it.
 */

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  LayoutDashboard,
  ShieldAlert,
  HelpCircle,
  Scale,
  TrendingDown,
  Info,
  Layers,
  ArrowRight,
  CheckCircle2,
  type LucideIcon,
} from "lucide-react";
import { TONE, procLabel } from "@/lib/status";
import {
  formatPct,
  formatUsd0,
  type ExceptionQueue,
  type ExceptionQueueId,
  type PartExceptions,
  type RedesignSaving,
} from "@/lib/portfolio";
import { formatUnitUsd } from "@/lib/catalog";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Button } from "@/components/ui/button";
import { Rise } from "@/components/ui/motion";
import { cn } from "@/lib/utils";
import { DoorCrossNav, DOOR_ICONS, type DoorNav } from "../DoorCrossNav";
import { usePortfolioParts } from "./usePortfolioParts";

/* ------------------------------------------------------------------ */
/*  Presentation atoms                                                 */
/* ------------------------------------------------------------------ */

const QUEUE_ICON: Record<ExceptionQueueId, LucideIcon> = {
  "dfm-required": ShieldAlert,
  "default-heavy": HelpCircle,
  "crossover-fragile": Scale,
};

type QueueTone = ExceptionQueue["tone"];

/** the exact reason a part sits in a given queue — bound to a real field. */
function reasonFor(part: PartExceptions, queue: ExceptionQueueId): string {
  switch (queue) {
    case "dfm-required":
      return part.blockerReason ?? "Recommended route is not DFM-ready.";
    case "default-heavy":
      return `${formatPct(part.guessPct)} of the route's drivers are generic defaults — ${part.groundedDrivers}/${part.totalDrivers} grounded.`;
    case "crossover-fragile": {
      const f = part.fragility;
      if (!f) return "Make-vs-buy crossover is volume-sensitive.";
      return `Crossover ≈ ${f.crossoverQty.toLocaleString()} units near your ${f.nearestQty.toLocaleString()}-unit order.`;
    }
    default:
      return "";
  }
}

/* ------------------------------------------------------------------ */
/*  Door                                                              */
/* ------------------------------------------------------------------ */

export function PortfolioDoor({ nav }: { nav: DoorNav }) {
  const router = useRouter();
  const {
    status,
    error,
    entries,
    assessments,
    queues,
    pulse,
    savings,
    hydratingCount,
    hasMore,
    loadingMore,
    loadMore,
    retry,
  } = usePortfolioParts();

  const [selected, setSelected] = useState<ExceptionQueueId | null>(null);

  const open = (id: string) => router.push(`/cost-decisions/${id}`);

  // id → assessment, for rendering a queue's cohort rows.
  const byId = useMemo(() => {
    const m = new Map<string, PartExceptions>();
    for (const a of assessments) m.set(a.id, a);
    return m;
  }, [assessments]);

  // Default the open queue to the worst non-empty one; fall back to the first.
  const activeQueueId: ExceptionQueueId =
    selected ?? queues.find((q) => q.count > 0)?.id ?? queues[0]?.id ?? "dfm-required";
  const activeQueue = queues.find((q) => q.id === activeQueueId) ?? queues[0];

  const Icon = DOOR_ICONS.portfolio;

  return (
    <div className="flex h-full min-h-full flex-col p-6">
      <DoorCrossNav nav={nav} />

      <div className="mx-auto w-full max-w-6xl space-y-6 py-6">
        <Rise>
          <div className="flex items-start gap-3">
            <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-[var(--radius-lg)] bg-muted text-muted-foreground">
              <Icon className="size-4" />
            </span>
            <div>
              <span className="num cv-eyebrow text-accent-text">I own a portfolio · TRIAGE</span>
              <h1 className="mt-1 text-display font-semibold tracking-tight text-foreground">
                Triage the exceptions
              </h1>
              <p className="mt-1 max-w-prose text-sm text-muted-foreground">
                The engine surfaces what needs attention before you ask — the parts that
                can&apos;t be made, the numbers we&apos;re guessing, the make-vs-buy calls on a
                knife-edge. Each queue drills to the parts; each part opens its saved decision.
              </p>
            </div>
          </div>
        </Rise>

        {status === "loading" && (
          <Rise delay={80}>
            <PortfolioSkeleton />
          </Rise>
        )}

        {status === "error" && (
          <Rise delay={80}>
            <ErrorState
              title="Couldn't load your portfolio"
              message={error ?? undefined}
              onRetry={retry}
            />
          </Rise>
        )}

        {status === "ready" && entries.length === 0 && (
          <Rise delay={80}>
            <EmptyState
              icon={LayoutDashboard}
              title="No costed parts to triage yet"
              description="The portfolio triages the parts you've costed. Cost a part — or run many at once in a batch — and the exceptions surface here."
              action={
                <div className="flex flex-wrap justify-center gap-2">
                  <Button onClick={() => nav.onGoDoor("part")}>Drop a part to cost</Button>
                  <Button variant="secondary" onClick={() => router.push("/batch")}>
                    <Layers className="size-4" />
                    Run a batch
                  </Button>
                </div>
              }
            />
          </Rise>
        )}

        {status === "ready" && entries.length > 0 && (
          <>
            <Rise delay={80}>
              <PulseStrip pulse={pulse} hydratingCount={hydratingCount} />
            </Rise>

            <Rise delay={120}>
              <section className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_1fr]">
                {/* Queue selector — the three exception queues, ranked worst-first */}
                <div className="space-y-2.5" role="tablist" aria-label="Exception queues">
                  {queues.map((q) => (
                    <QueueCard
                      key={q.id}
                      queue={q}
                      active={q.id === activeQueueId}
                      onSelect={() => setSelected(q.id)}
                    />
                  ))}
                </div>

                {/* Cohort — the selected queue's parts (drill to the part hero) */}
                <Cohort
                  queue={activeQueue}
                  byId={byId}
                  allClean={pulse.flagged === 0}
                  hydratingCount={hydratingCount}
                  onOpen={open}
                  onGoPart={() => nav.onGoDoor("part")}
                />
              </section>
            </Rise>

            <Rise delay={160}>
              <SavingsPanel savings={savings} onOpen={open} />
            </Rise>

            {hasMore && (
              <div className="text-center">
                <Button variant="secondary" size="sm" loading={loadingMore} onClick={loadMore}>
                  Load more parts
                </Button>
              </div>
            )}

            {/* Honest scope + gap note */}
            <div className="flex items-start gap-2 rounded-[var(--radius)] border border-dashed border-border bg-card/50 px-3 py-2.5 text-xs leading-relaxed text-subtle-foreground">
              <Info className="mt-0.5 size-3.5 shrink-0" />
              <p>
                Triage runs over the <span className="text-muted-foreground">{pulse.assessed}</span>{" "}
                {pulse.assessed === 1 ? "part" : "parts"} you&apos;ve costed — every count and posture
                figure is real, none is a portfolio-scale estimate. The one-call governed rollup
                across a full portfolio (and the DFM-batch aggregate) lands in{" "}
                <span className="text-muted-foreground">Phase 3</span>; run many parts at once today
                in a{" "}
                <button
                  type="button"
                  onClick={() => router.push("/batch")}
                  className="text-muted-foreground underline underline-offset-2 hover:text-foreground"
                >
                  batch
                </button>
                .
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Portfolio pulse — REAL / derivable KPIs only                       */
/* ------------------------------------------------------------------ */

function PulseStrip({
  pulse,
  hydratingCount,
}: {
  pulse: ReturnType<typeof usePortfolioParts>["pulse"];
  hydratingCount: number;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Kpi
        label="Parts costed"
        value={String(pulse.assessed)}
        sub={hydratingCount > 0 ? `${hydratingCount} still loading…` : "in your portfolio"}
      />
      <Kpi
        label="Need attention"
        value={String(pulse.flagged)}
        sub={
          pulse.assessed > 0
            ? `${formatPct(pulse.flagged / pulse.assessed)} of costed parts`
            : "—"
        }
        tone={pulse.flagged > 0 ? "warn" : "pass"}
      />
      <Kpi
        label="DFM-blocked"
        value={String(pulse.dfmRequired)}
        sub="price withheld"
        tone={pulse.dfmRequired > 0 ? "fail" : "pass"}
      />
      <div className="rounded-[var(--radius-lg)] border border-border bg-card p-3.5">
        <p className="cv-eyebrow">Grounded posture</p>
        <p className="num mt-1 text-2xl font-semibold tabular-nums text-foreground">
          {pulse.totalDrivers > 0 ? formatPct(pulse.groundedPct) : "—"}
        </p>
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted" aria-hidden>
          <div
            className="h-full rounded-full bg-accent-text transition-[width]"
            style={{ width: `${Math.round(pulse.groundedPct * 100)}%` }}
          />
        </div>
        <p className="num mt-1.5 text-[11px] text-subtle-foreground">
          {pulse.groundedDrivers}/{pulse.totalDrivers} route drivers grounded
        </p>
      </div>
    </div>
  );
}

function Kpi({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub: string;
  tone?: QueueTone | "pass";
}) {
  const fg =
    tone === "fail"
      ? "text-fail"
      : tone === "warn"
        ? "text-warn"
        : tone === "pass"
          ? "text-pass"
          : "text-foreground";
  return (
    <div className="rounded-[var(--radius-lg)] border border-border bg-card p-3.5">
      <p className="cv-eyebrow">{label}</p>
      <p className={cn("num mt-1 text-2xl font-semibold tabular-nums", fg)}>{value}</p>
      <p className="num mt-1.5 text-[11px] text-subtle-foreground">{sub}</p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Queue card + cohort                                                */
/* ------------------------------------------------------------------ */

function QueueCard({
  queue,
  active,
  onSelect,
}: {
  queue: ExceptionQueue;
  active: boolean;
  onSelect: () => void;
}) {
  const t = TONE[queue.tone];
  const QIcon = QUEUE_ICON[queue.id];
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onSelect}
      className={cn(
        "group flex w-full items-center gap-3 rounded-[var(--radius-lg)] border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "border-border-strong bg-muted/60"
          : "border-border bg-card hover:border-border-strong hover:bg-muted/40"
      )}
    >
      <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-[var(--radius)]", t.bg, t.fg)}>
        <QIcon className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span className="truncate text-sm font-semibold text-foreground">{queue.label}</span>
          <span className={cn("num ml-auto text-lg font-semibold tabular-nums", queue.count > 0 ? t.fg : "text-subtle-foreground")}>
            {queue.count}
          </span>
        </span>
        <span className="num mt-0.5 block text-[11px] uppercase tracking-wide text-subtle-foreground">
          {queue.verb}
        </span>
      </span>
    </button>
  );
}

function Cohort({
  queue,
  byId,
  allClean,
  hydratingCount,
  onOpen,
  onGoPart,
}: {
  queue: ExceptionQueue | undefined;
  byId: Map<string, PartExceptions>;
  allClean: boolean;
  hydratingCount: number;
  onOpen: (id: string) => void;
  onGoPart: () => void;
}) {
  if (!queue) return null;
  const members = queue.memberIds
    .map((id) => byId.get(id))
    .filter((p): p is PartExceptions => p != null);

  return (
    <div className="rounded-[var(--radius-lg)] border border-border bg-card">
      <div className="flex items-start gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground">{queue.label}</p>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{queue.description}</p>
        </div>
      </div>

      {members.length > 0 ? (
        <ul className="divide-y divide-border">
          {members.map((p) => (
            <li key={p.id}>
              <button
                type="button"
                onClick={() => onOpen(p.id)}
                className="group flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
              >
                <span className="min-w-0 flex-1">
                  <span className="num flex items-center gap-2 truncate text-sm font-medium text-foreground group-hover:underline">
                    {p.label}
                    {queue.id === "dfm-required" && p.routeBlockerCount > 0 && (
                      <span className="num inline-flex items-center gap-1 rounded-sm border border-fail-border bg-fail-bg px-1 py-0 text-[10px] font-medium text-fail">
                        {p.routeBlockerCount} blocker{p.routeBlockerCount === 1 ? "" : "s"}
                      </span>
                    )}
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                    {reasonFor(p, queue.id)}
                  </span>
                </span>
                <ArrowRight className="size-4 shrink-0 text-subtle-foreground transition-transform group-hover:translate-x-0.5" />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div className="px-4 py-10 text-center">
          {/* Honest ordering: never claim "clean" while parts are still loading. */}
          {hydratingCount > 0 ? (
            <p className="text-sm text-subtle-foreground">
              No parts in this queue yet — {hydratingCount} still loading.
            </p>
          ) : allClean ? (
            <>
              <span className="mx-auto flex size-9 items-center justify-center rounded-full bg-pass-bg text-pass">
                <CheckCircle2 className="size-5" />
              </span>
              <p className="mt-2 text-sm font-medium text-foreground">Nothing in this queue</p>
              <p className="mx-auto mt-1 max-w-xs text-xs text-muted-foreground">
                No costed part trips this exception yet — the numbers here are grounded and the
                routes are clear.
              </p>
            </>
          ) : (
            <>
              <p className="text-sm font-medium text-foreground">No parts in this queue</p>
              <button
                type="button"
                onClick={onGoPart}
                className="mt-2 text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
              >
                Cost another part
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Savings — honest coming-state + REAL per-part deltas               */
/* ------------------------------------------------------------------ */

function SavingsPanel({
  savings,
  onOpen,
}: {
  savings: RedesignSaving[];
  onOpen: (id: string) => void;
}) {
  return (
    <section className="rounded-[var(--radius-lg)] border border-border bg-card">
      <div className="flex items-start gap-3 border-b border-border px-4 py-3">
        <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-[var(--radius)] bg-accent-subtle text-accent-text">
          <TrendingDown className="size-4" />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground">Savings pipeline</p>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
            Portfolio-scale savings — rolled up across annual volumes into one ranked $ pipeline —
            needs portfolio cost, which lands in{" "}
            <span className="text-foreground">Phase 3 (W3)</span>. It is deliberately not estimated
            here. What&apos;s real today is <span className="text-foreground">per part</span>: where
            the engine finds a cheaper redesign, its own delta.
          </p>
        </div>
      </div>

      {savings.length > 0 ? (
        <ul className="divide-y divide-border">
          {savings.slice(0, 6).map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onOpen(s.id)}
                className="group flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
              >
                <span className="num w-14 shrink-0 text-right text-lg font-semibold tabular-nums text-accent-text">
                  −{formatPct(s.savePct)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="num block truncate text-sm font-medium text-foreground group-hover:underline">
                    {s.label}
                  </span>
                  <span className="num mt-0.5 block truncate text-xs text-muted-foreground">
                    {formatUnitUsd(s.makeNowUsd)} → {formatUnitUsd(s.redesignedUsd)}/unit at{" "}
                    {s.qty.toLocaleString()} via {procLabel(s.redesignedProcess)} · {s.caveat}
                  </span>
                </span>
                <span className="num shrink-0 text-right text-xs text-subtle-foreground">
                  {formatUsd0(s.saveUsd)}/unit
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div className="px-4 py-8 text-center">
          <p className="text-sm font-medium text-foreground">
            No cheaper redesign across your costed parts
          </p>
          <p className="mx-auto mt-1 max-w-md text-xs text-muted-foreground">
            The engine hasn&apos;t found a lower-cost redesign alternative for any part yet. When it
            does, the real per-part delta ranks here — never a made-up portfolio total.
          </p>
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Skeleton                                                           */
/* ------------------------------------------------------------------ */

function PortfolioSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-[var(--radius-lg)]" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_1fr]">
        <div className="space-y-2.5">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-[var(--radius-lg)]" />
          ))}
        </div>
        <Skeleton className="h-64 w-full rounded-[var(--radius-lg)]" />
      </div>
    </div>
  );
}
