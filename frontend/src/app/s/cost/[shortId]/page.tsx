import type { Metadata } from "next";
import Link from "next/link";
import { Calculator } from "lucide-react";
import { fetchSharedCostDecision } from "@/lib/api";
import type { SharedCostDecision, CostEstimate, CostAssumption } from "@/lib/api";
import { procLabel } from "@/lib/status";
import {
  recommendationForQty,
  redesignedForQty,
} from "@/lib/cost-decision";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import { CostHonestyNote } from "@/components/cost/CostHonestyNote";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";

const USD = (n: number | null | undefined) =>
  n == null
    ? "—"
    : `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/* ------------------------------------------------------------------ */
/*  OG Meta Tags — noindex (this is a shared, unvalidated should-cost) */
/* ------------------------------------------------------------------ */

export async function generateMetadata({
  params,
}: {
  params: Promise<{ shortId: string }>;
}): Promise<Metadata> {
  const { shortId } = await params;
  try {
    const data = await fetchSharedCostDecision(shortId);
    const make = data.make_now_process ? procLabel(data.make_now_process) : "should-cost";
    return {
      title: `${data.filename} - Should-cost`,
      openGraph: {
        title: `${data.filename} - Should-cost decision`,
        description: `Make by ${make} · assumption-based estimate, not a validated quote`,
        type: "article",
        siteName: "CadVerify",
      },
      twitter: { card: "summary" },
      robots: { index: false, follow: false },
    };
  } catch {
    return { title: "Shared should-cost - CadVerify", robots: { index: false, follow: false } };
  }
}

/* ------------------------------------------------------------------ */
/*  Public shell (read-only, same design language, no app nav)        */
/* ------------------------------------------------------------------ */

function PublicShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex h-14 max-w-3xl items-center gap-2 px-4">
          <Calculator className="size-5 text-primary" />
          <span className="font-semibold text-foreground">CadVerify</span>
          <span className="ml-2 text-xs text-muted-foreground">
            Shared should-cost · read-only
          </span>
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-6 px-4 py-8">{children}</main>
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </h2>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card className="p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="num mt-0.5 text-sm font-semibold text-foreground">{value}</p>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Server Component — read-only public cost-decision share            */
/* ------------------------------------------------------------------ */

export default async function SharedCostDecisionPage({
  params,
}: {
  params: Promise<{ shortId: string }>;
}) {
  const { shortId } = await params;

  let data: SharedCostDecision | null = null;
  try {
    data = await fetchSharedCostDecision(shortId);
  } catch {
    /* 404 or network error */
  }

  if (!data) {
    return (
      <PublicShell>
        <Card>
          <CardContent className="py-12 text-center">
            <h1 className="text-xl font-semibold text-foreground">
              Cost decision not available
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              This shared should-cost is no longer available. It may have been
              revoked by its owner.
            </p>
            <Button asChild className="mt-6">
              <Link href="/">Go to CadVerify</Link>
            </Button>
          </CardContent>
        </Card>
      </PublicShell>
    );
  }

  const dec = data.decision;
  const geo = data.geometry || ({} as SharedCostDecision["geometry"]);
  const estByProc = new Map<string, CostEstimate>();
  for (const e of data.estimates || []) {
    if (!estByProc.has(e.process)) estByProc.set(e.process, e);
  }
  const makeNowEstimate = dec ? estByProc.get(dec.make_now_process) : undefined;
  const conf = makeNowEstimate?.confidence ?? null;

  const crossoverSentence = (() => {
    if (!dec) return "This part was costed but returned no make-vs-buy decision.";
    if (dec.crossover_qty != null) {
      const n = Math.round(dec.crossover_qty).toLocaleString();
      const make = procLabel(dec.make_now_process);
      return dec.tooling_process
        ? `Make below ~${n} units with ${make}; tool up with ${procLabel(dec.tooling_process)} above it.`
        : `${make} wins below ~${n} units; tooling amortises above it.`;
    }
    return `${procLabel(dec.make_now_process)} stays cheapest at every quantity tested.`;
  })();

  return (
    <PublicShell>
      {/* Header — the decision */}
      <Card tone={makeNowEstimate?.dfm_ready ? "pass" : "info"}>
        <CardContent className="space-y-2">
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <h1 className="truncate text-xl font-semibold text-foreground">
                {data.label || data.filename}
              </h1>
              <p className="num mt-1 text-sm text-muted-foreground">
                {data.file_type.toUpperCase()} ·{" "}
                {new Date(data.created_at).toLocaleDateString()}
              </p>
            </div>
            {dec && (
              <StatusBadge
                tone={makeNowEstimate?.dfm_ready ? "pass" : "warn"}
                label={makeNowEstimate?.dfm_ready ? "DFM-ready" : "needs redesign"}
              />
            )}
          </div>
          {dec && (
            <p className="text-sm font-semibold text-foreground">
              Make by {procLabel(dec.make_now_process)}
            </p>
          )}
          <p className="text-sm text-muted-foreground">{crossoverSentence}</p>
        </CardContent>
      </Card>

      {/* Honesty — travels with the shared artifact */}
      <CostHonestyNote />

      {/* Confidence band (honest, verbatim) */}
      {conf && (
        <Card>
          <CardContent compact className="space-y-1">
            <SectionHeading>Confidence · {Math.round(conf.level * 100)}%</SectionHeading>
            <p className="num text-sm text-foreground">
              {USD(conf.low_usd)} – {USD(conf.high_usd)} / unit{" "}
              <span className="text-muted-foreground">(±{Math.round(conf.half_width_pct)}%)</span>
            </p>
            <p className="text-xs text-muted-foreground">
              {conf.validated
                ? `Validated on ${conf.n_samples} part${conf.n_samples === 1 ? "" : "s"} · ${conf.basis}`
                : conf.basis || conf.label}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Geometry */}
      {"face_count" in geo && (
        <section>
          <SectionHeading>Geometry</SectionHeading>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Faces" value={(geo.face_count ?? 0).toLocaleString()} />
            {geo.volume_cm3 != null && (
              <StatCard label="Volume" value={`${geo.volume_cm3.toFixed(1)} cm3`} />
            )}
            {geo.bbox_mm && (
              <StatCard
                label="Dimensions"
                value={`${geo.bbox_mm.map((d) => Math.round(d)).join(" x ")} mm`}
              />
            )}
            {geo.watertight != null && (
              <StatCard label="Watertight" value={geo.watertight ? "Yes" : "No"} />
            )}
          </div>
        </section>
      )}

      {/* Recommendation by quantity */}
      {dec && data.quantities?.length > 0 && (
        <section>
          <SectionHeading>Recommendation by quantity</SectionHeading>
          <Card className="overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead numeric>Qty</TableHead>
                  <TableHead>Process / material</TableHead>
                  <TableHead numeric>$ / unit</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.quantities.map((q) => {
                  const r = recommendationForQty(dec, q);
                  const alt = redesignedForQty(dec, q);
                  if (!r) return null;
                  return (
                    <TableRow key={q} className="align-top">
                      <TableCell numeric className="font-medium">
                        {q.toLocaleString()}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-foreground">{procLabel(r.process)}</span>
                          <span className="text-muted-foreground">/ {r.material}</span>
                          {!r.dfm_ready && (
                            <StatusBadge tone="warn" label="not DFM-ready" size="sm" icon={false} />
                          )}
                        </div>
                        {alt && (
                          <div className="mt-1 text-xs text-muted-foreground">
                            cheaper if redesigned: {procLabel(alt.process)}{" "}
                            <span className="num">{USD(alt.unit_cost_usd)}</span>/unit
                            {alt.caveat ? ` (${alt.caveat})` : ""}
                          </div>
                        )}
                      </TableCell>
                      <TableCell numeric className="font-semibold">
                        {USD(r.unit_cost_usd)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </Card>
        </section>
      )}

      {/* Assumptions (provenance-tagged) */}
      {data.assumptions?.length > 0 && (
        <section>
          <SectionHeading>Assumptions</SectionHeading>
          <div className="flex flex-wrap gap-2">
            {data.assumptions.map((a: CostAssumption) => (
              <span
                key={a.name}
                className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-card px-2 py-1 text-xs text-foreground"
                title={a.source}
              >
                <span className="font-medium">{a.name}</span>
                <span className="num text-muted-foreground">
                  {a.unit === "$/hr" ? `$${a.value}/hr` : a.unit === "frac" ? a.value : `${a.value}${a.unit && a.unit !== "frac" ? ` ${a.unit}` : ""}`}
                </span>
                <span className="num rounded-xs bg-muted px-1 text-[10px] uppercase text-muted-foreground">
                  {a.provenance}
                </span>
              </span>
            ))}
          </div>
        </section>
      )}

      {/* CTA */}
      <Card>
        <CardContent className="text-center">
          <p className="text-sm text-muted-foreground">
            This is a shared should-cost decision from CadVerify — assumption-based, not a
            validated quote.
          </p>
          <Button asChild className="mt-3">
            <Link href="/">View on CadVerify</Link>
          </Button>
        </CardContent>
      </Card>
    </PublicShell>
  );
}
