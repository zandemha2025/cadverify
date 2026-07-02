"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight } from "lucide-react";
import {
  fetchCostDecisions,
  compareCostDecisions,
} from "@/lib/api";
import type { CostDecisionSummary, CostComparison } from "@/lib/api";
import { procLabel } from "@/lib/status";
import { formatUnitCostDelta, cheaperSide } from "@/lib/cost-decision";
import { CostHonestyNote } from "@/components/cost/CostHonestyNote";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Spinner } from "@/components/ui/spinner";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
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

function SummaryCard({
  label,
  s,
}: {
  label: string;
  s: CostComparison["a"];
}) {
  return (
    <Card>
      <CardContent compact className="space-y-1">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <p className="truncate text-sm font-semibold text-foreground">
          {s.label || s.filename}
        </p>
        <p className="num text-xs text-muted-foreground">
          Make now: {s.make_now_process ? procLabel(s.make_now_process) : "—"}
          {s.material_class ? ` · ${s.material_class}` : ""}
        </p>
        <p className="num text-xs text-muted-foreground">
          Crossover:{" "}
          {s.crossover_qty != null
            ? Math.round(s.crossover_qty).toLocaleString()
            : "—"}
          {s.tooling_process ? ` · tool: ${procLabel(s.tooling_process)}` : ""}
        </p>
      </CardContent>
    </Card>
  );
}

export default function CompareCostDecisionsPage() {
  const router = useRouter();
  const [options, setOptions] = useState<CostDecisionSummary[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(true);

  const [idA, setIdA] = useState<string>("");
  const [idB, setIdB] = useState<string>("");
  const [comparison, setComparison] = useState<CostComparison | null>(null);
  const [comparing, setComparing] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchCostDecisions({ limit: 100 })
      .then((page) => {
        if (!cancelled) setOptions(page.cost_decisions);
      })
      .catch((e) => {
        if (!cancelled)
          setListError(e instanceof Error ? e.message : "Failed to load decisions");
      })
      .finally(() => {
        if (!cancelled) setListLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const runCompare = useCallback(async () => {
    if (!idA || !idB || idA === idB) return;
    setComparing(true);
    setCompareError(null);
    try {
      setComparison(await compareCostDecisions(idA, idB));
    } catch (e) {
      setCompareError(e instanceof Error ? e.message : "Compare failed");
      setComparison(null);
    } finally {
      setComparing(false);
    }
  }, [idA, idB]);

  const canCompare = idA && idB && idA !== idB;

  const optionLabel = (o: CostDecisionSummary) =>
    `${o.label || o.filename}${o.make_now_process ? ` · ${procLabel(o.make_now_process)}` : ""}`;

  return (
    <div className="space-y-6">
      <Button
        variant="ghost"
        size="sm"
        className="-ml-3"
        onClick={() => router.push("/cost-decisions")}
      >
        <ArrowLeft /> Back to cost history
      </Button>

      <PageHeader
        title="Compare cost decisions"
        subtitle="Pick two saved decisions to see the recommended unit cost by quantity side by side."
      />

      <CostHonestyNote />

      {/* Pickers */}
      <Card>
        <CardContent compact>
          {listLoading ? (
            <div className="flex justify-center py-6">
              <Spinner />
            </div>
          ) : listError ? (
            <ErrorState message={listError} />
          ) : options.length < 2 ? (
            <p className="text-sm text-muted-foreground">
              You need at least two saved cost decisions to compare.{" "}
              <button
                type="button"
                className="font-medium text-primary underline-offset-4 hover:underline"
                onClick={() => router.push("/cost")}
              >
                Cost a part
              </button>
              .
            </p>
          ) : (
            <div className="flex flex-col items-stretch gap-3 sm:flex-row sm:items-end">
              <div className="flex-1 space-y-1">
                <label className="cv-eyebrow">Decision A</label>
                <Select value={idA} onValueChange={setIdA}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select a decision" />
                  </SelectTrigger>
                  <SelectContent>
                    {options.map((o) => (
                      <SelectItem key={o.id} value={o.id} disabled={o.id === idB}>
                        {optionLabel(o)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex-1 space-y-1">
                <label className="cv-eyebrow">Decision B</label>
                <Select value={idB} onValueChange={setIdB}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select a decision" />
                  </SelectTrigger>
                  <SelectContent>
                    {options.map((o) => (
                      <SelectItem key={o.id} value={o.id} disabled={o.id === idA}>
                        {optionLabel(o)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button
                onClick={runCompare}
                loading={comparing}
                disabled={!canCompare}
              >
                Compare <ArrowRight />
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {compareError && <ErrorState message={compareError} />}

      {/* Results */}
      {comparison && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <SummaryCard label="Decision A" s={comparison.a} />
            <SummaryCard label="Decision B" s={comparison.b} />
          </div>

          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Recommended unit cost by quantity
            </h2>
            <Card className="overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead numeric>Qty</TableHead>
                    <TableHead numeric>A · $ / unit</TableHead>
                    <TableHead numeric>B · $ / unit</TableHead>
                    <TableHead numeric>Δ (B vs A)</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {comparison.unit_cost_by_qty.map((row) => {
                    const cheaper = cheaperSide(row);
                    const delta = formatUnitCostDelta(row.delta_usd, row.delta_pct);
                    return (
                      <TableRow key={row.quantity}>
                        <TableCell numeric className="font-medium">
                          {row.quantity.toLocaleString()}
                        </TableCell>
                        <TableCell
                          numeric
                          className={
                            cheaper === "a"
                              ? "font-semibold text-pass"
                              : "text-foreground"
                          }
                        >
                          {USD(row.a?.unit_cost_usd)}
                        </TableCell>
                        <TableCell
                          numeric
                          className={
                            cheaper === "b"
                              ? "font-semibold text-pass"
                              : "text-foreground"
                          }
                        >
                          {USD(row.b?.unit_cost_usd)}
                        </TableCell>
                        <TableCell
                          numeric
                          className={
                            delta.direction === "cheaper"
                              ? "text-pass"
                              : delta.direction === "pricier"
                                ? "text-warn"
                                : "text-muted-foreground"
                          }
                        >
                          {delta.text}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </Card>
          </section>
        </div>
      )}
    </div>
  );
}
