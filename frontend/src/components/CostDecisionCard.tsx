"use client";

/**
 * CostDecisionCard — the glass-box should-cost breakdown (progressive
 * disclosure body behind the answer hero). Pure presentational.
 *
 * Order: per-quantity recommendation table → per-process should-cost →
 * provenance-tagged driver breakdown with the Σ-line-items == unit-cost
 * coherence check (the explainability differentiator) → lead time →
 * assumptions. The make-vs-buy headline now lives in <CostAnswer> above this.
 *
 * Refactored onto the shared primitives (Card / Badge / StatusBadge / Table)
 * and the single status/process/provenance source (lib/status).
 */

import type {
  CostReport,
  CostEstimate,
  CostDriver,
  CostGeometry,
} from "@/lib/api";
import { procLabel } from "@/lib/status";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/ui/status-badge";
import { ProvenanceChip } from "@/components/glass-box";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

function money(x: number): string {
  return USD.format(x);
}

function fmtDriverValue(d: CostDriver): string {
  if (d.unit === "$") return money(d.value);
  const v =
    Math.abs(d.value) >= 100
      ? d.value.toLocaleString(undefined, { maximumFractionDigits: 1 })
      : d.value.toLocaleString(undefined, { maximumFractionDigits: 3 });
  return d.unit ? `${v} ${d.unit}` : v;
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2 text-base font-semibold leading-[22px] text-foreground">
      {children}
    </h3>
  );
}

/* ------------------------------------------------------------------ */
/*  GEOMETRY_INVALID repair card (G1 refusal)                         */
/* ------------------------------------------------------------------ */

export function CostGeometryInvalidCard({
  reason,
  geometry,
  filename,
}: {
  reason: string | null;
  geometry: CostGeometry | null;
  filename?: string;
}) {
  return (
    <Card tone="fail" className="bg-fail-bg p-5">
      <div className="flex items-center gap-2">
        <StatusBadge tone="fail" label="Geometry invalid" />
        {filename && (
          <span className="num text-xs text-fail/80">{filename}</span>
        )}
      </div>
      <p className="mt-2 text-sm font-semibold text-fail">
        No cost produced — repair required.
      </p>
      <p className="mt-1 text-sm text-muted-foreground">
        {reason ||
          "The geometry is not watertight or has non-positive volume, so a should-cost cannot be computed."}
      </p>

      {geometry && (
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Volume" value={`${geometry.volume_cm3.toFixed(1)} cm³`} />
          <Stat
            label="Bounding box"
            value={`${geometry.bbox_mm.map((v) => Math.round(v)).join(" × ")} mm`}
          />
          <Stat
            label="Watertight"
            value={geometry.watertight ? "Yes" : "No"}
            danger={!geometry.watertight}
          />
          <Stat label="Faces" value={geometry.face_count.toLocaleString()} />
        </div>
      )}

      <a
        href="https://docs.cadverify.com/errors#GEOMETRY_INVALID"
        target="_blank"
        rel="noreferrer"
        className="mt-4 inline-block text-sm font-medium text-primary underline-offset-4 hover:underline"
      >
        How to repair this part →
      </a>
    </Card>
  );
}

function Stat({
  label,
  value,
  danger,
}: {
  label: string;
  value: string;
  danger?: boolean;
}) {
  return (
    <Card className="p-3">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p
        className={`num mt-0.5 text-sm font-semibold ${
          danger ? "text-fail" : "text-foreground"
        }`}
      >
        {value}
      </p>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Glass-box breakdown                                               */
/* ------------------------------------------------------------------ */

export default function CostDecisionCard({ report }: { report: CostReport }) {
  if (report.status !== "OK" || !report.decision) {
    return (
      <CostGeometryInvalidCard
        reason={report.reason}
        geometry={report.geometry}
        filename={report.filename}
      />
    );
  }

  const dec = report.decision;
  const geo = report.geometry;

  const byProcess = new Map<string, CostEstimate[]>();
  for (const e of report.estimates) {
    const arr = byProcess.get(e.process) ?? [];
    arr.push(e);
    byProcess.set(e.process, arr);
  }
  for (const arr of byProcess.values())
    arr.sort((a, b) => a.quantity - b.quantity);

  const headline = (byProcess.get(dec.make_now_process) ?? [])[0];

  return (
    <div className="space-y-6">
      {/* Per-quantity recommendation table */}
      <section>
        <SectionTitle>Recommendation by quantity</SectionTitle>
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Qty</TableHead>
                <TableHead>Process / material</TableHead>
                <TableHead numeric>$ / unit</TableHead>
                <TableHead numeric>Lead time</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {report.quantities.map((q) => {
                const r = dec.recommendation[String(q)];
                const alt = dec.if_redesigned[String(q)];
                if (!r) return null;
                return (
                  <TableRow key={q} className="align-top">
                    <TableCell className="num font-medium">
                      {q.toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-foreground">
                          {procLabel(r.process)}
                        </span>
                        <span className="text-muted-foreground">
                          / {r.material}
                        </span>
                        {!r.dfm_ready && (
                          <StatusBadge
                            tone="warn"
                            label="not DFM-ready"
                            size="sm"
                            icon={false}
                          />
                        )}
                      </div>
                      {alt && (
                        <div className="mt-1 text-xs text-muted-foreground">
                          cheaper if redesigned: {procLabel(alt.process)}{" "}
                          <span className="num">{money(alt.unit_cost_usd)}</span>
                          /unit
                          {alt.caveat ? ` (${alt.caveat})` : ""}
                        </div>
                      )}
                    </TableCell>
                    <TableCell numeric className="font-semibold">
                      {money(r.unit_cost_usd)}
                    </TableCell>
                    <TableCell numeric className="text-muted-foreground">
                      {r.lead_low_days != null && r.lead_high_days != null
                        ? `${r.lead_low_days}–${r.lead_high_days} d`
                        : "—"}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </Card>
      </section>

      {/* Per-process should-cost */}
      <section>
        <SectionTitle>Process options · should-cost</SectionTitle>
        <div className="grid gap-3 sm:grid-cols-2">
          {Array.from(byProcess.entries()).map(([proc, ests]) => {
            const head = ests[0];
            const isHeadline = proc === dec.make_now_process;
            return (
              <Card
                key={proc}
                className={isHeadline ? "border-accent-subtle-border bg-accent-subtle/50" : ""}
              >
                <CardContent compact>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <h4 className="text-sm font-semibold text-foreground">
                        {procLabel(proc)}
                      </h4>
                      {isHeadline && (
                        <Badge variant="primary" size="sm">
                          MAKE NOW
                        </Badge>
                      )}
                    </div>
                    <span className="num rounded-sm bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                      ±{head.est_error_band_pct}%
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {head.material}
                  </p>

                  <div className="mt-2 space-y-1">
                    {ests.map((e) => (
                      <div
                        key={e.quantity}
                        className="flex items-center justify-between text-sm"
                      >
                        <span className="num text-muted-foreground">
                          qty {e.quantity.toLocaleString()}
                        </span>
                        <span className="num font-semibold text-foreground">
                          {money(e.unit_cost_usd)}/unit
                        </span>
                      </div>
                    ))}
                  </div>

                  {!head.dfm_ready && (
                    <div className="mt-2 rounded-sm bg-warn-bg px-2 py-1.5 text-xs text-warn">
                      <span className="font-semibold">
                        Not DFM-ready as-modeled.
                      </span>{" "}
                      {head.dfm_blockers[0] ??
                        "Design-for-process changes required."}
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </section>

      {/* Driver breakdown with provenance (glass-box) */}
      {headline && (
        <section>
          <SectionTitle>
            Cost drivers · {procLabel(headline.process)} @ qty{" "}
            {headline.quantity.toLocaleString()}
          </SectionTitle>
          <p className="-mt-1 mb-2 text-xs text-muted-foreground">
            Every figure is provenance-tagged. Line items sum to the unit cost —
            no naked numbers.
          </p>

          <Card>
            <CardContent compact>
              <div className="space-y-1.5">
                {headline.drivers
                  .filter((d) => d.name !== "cycle_time")
                  .map((d) => (
                    <div
                      key={d.name}
                      className="flex flex-wrap items-center justify-between gap-2 text-sm"
                    >
                      <span className="num text-muted-foreground">{d.name}</span>
                      <span className="flex items-center gap-2">
                        <span className="num font-medium text-foreground">
                          {fmtDriverValue(d)}
                        </span>
                        <ProvenanceChip
                          provenance={d.provenance}
                          source={d.source}
                        />
                        {d.error_band_pct != null && (
                          <span className="num text-[10px] text-muted-foreground">
                            ±{d.error_band_pct}%
                          </span>
                        )}
                      </span>
                    </div>
                  ))}
              </div>

              <div className="mt-3 border-t border-border pt-3">
                <div className="space-y-1">
                  {Object.entries(headline.line_items).map(([k, v]) => (
                    <div
                      key={k}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="text-muted-foreground">{k}</span>
                      <span className="num text-foreground">{money(v)}</span>
                    </div>
                  ))}
                </div>
                <LineItemSum estimate={headline} />
              </div>
            </CardContent>
          </Card>
        </section>
      )}

      {/* Lead time detail */}
      {headline && <LeadTimeBlock estimate={headline} />}

      {/* Assumptions + notes + scope footnote */}
      <section>
        <SectionTitle>Assumptions</SectionTitle>
        <div className="flex flex-wrap gap-2">
          {report.assumptions.map((a) => (
            <span
              key={a.name}
              className="inline-flex items-center gap-1.5 rounded-sm border border-border bg-card px-2 py-1 text-xs text-foreground"
            >
              <span className="font-medium">{a.name}</span>
              <span className="num text-muted-foreground">
                {a.unit === "$/hr"
                  ? `$${a.value}/hr`
                  : a.unit === "frac"
                    ? a.value
                    : `${a.value}${a.unit && a.unit !== "frac" ? ` ${a.unit}` : ""}`}
              </span>
              <ProvenanceChip provenance={a.provenance} source={a.source} />
            </span>
          ))}
        </div>

        {report.notes.length > 0 && (
          <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
            {report.notes.map((n, i) => (
              <li key={i}>• {n}</li>
            ))}
          </ul>
        )}

        <p className="num mt-3 text-xs text-muted-foreground">
          Measured geometry: {geo.volume_cm3.toFixed(1)} cm³ ·{" "}
          {geo.bbox_mm.map((v) => Math.round(v)).join(" × ")} mm ·{" "}
          {geo.face_count.toLocaleString()} faces. STEP files are costed from a
          tessellated mesh (DFM + cost), not B-rep / GD&amp;T.
        </p>
      </section>
    </div>
  );
}

/** Renders the Σ line-items == unit_cost coherence check, visibly. */
function LineItemSum({ estimate }: { estimate: CostEstimate }) {
  const sum = Object.values(estimate.line_items).reduce((a, b) => a + b, 0);
  const coherent = Math.abs(sum - estimate.unit_cost_usd) < 0.02;
  return (
    <div className="mt-2 flex items-center justify-between border-t border-border pt-2 text-sm">
      <span className="font-semibold text-foreground">
        Σ line items = unit cost
      </span>
      <span
        className={`num font-semibold ${coherent ? "text-foreground" : "text-fail"}`}
      >
        {money(sum)}
        {!coherent && (
          <span className="ml-1 text-xs">
            (≠ {money(estimate.unit_cost_usd)})
          </span>
        )}
      </span>
    </div>
  );
}

function LeadTimeBlock({ estimate }: { estimate: CostEstimate }) {
  const lt = estimate.lead_time;
  const components = Object.entries(lt.components).filter(([, v]) => v);
  const cap = lt.capacity as {
    n_machines?: number;
    machine_hours_per_day?: number;
    provenance?: string;
  };
  return (
    <section>
      <SectionTitle>
        Lead time · {procLabel(estimate.process)} @ qty{" "}
        {estimate.quantity.toLocaleString()}
      </SectionTitle>
      <Card>
        <CardContent compact>
          <p className="num text-display font-semibold leading-9 text-foreground">
            {lt.low_days}–{lt.high_days}{" "}
            <span className="text-base font-medium text-muted-foreground">
              days
            </span>
          </p>
          {components.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
              {components.map(([k, v]) => (
                <span
                  key={k}
                  className="num rounded-sm border border-border bg-muted px-2 py-0.5"
                >
                  {k} {Math.round(v)} d
                </span>
              ))}
            </div>
          )}
          {cap && cap.n_machines != null && (
            <p className="num mt-2 text-xs text-muted-foreground">
              Capacity: {cap.n_machines} machine
              {cap.n_machines === 1 ? "" : "s"} × {cap.machine_hours_per_day}{" "}
              hr/day
              {cap.provenance ? ` [${cap.provenance}]` : ""}
            </p>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
