"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileCheck2,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  createRfqPackage,
  downloadRfqPackage,
  fetchCostDecisions,
  fetchRfqPackages,
  type CostDecisionSummary,
  type RfqPackageSummary,
} from "@/lib/api";

function dateLabel(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "--";
}

function riskLabel(d: CostDecisionSummary): string | null {
  if (d.is_stale) return "stale";
  if (d.approval_status !== "approved") return "unapproved";
  return null;
}

export function RfqPackagesClient() {
  const router = useRouter();
  const [packages, setPackages] = useState<RfqPackageSummary[]>([]);
  const [decisions, setDecisions] = useState<CostDecisionSummary[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [supplierName, setSupplierName] = useState("");
  const [note, setNote] = useState("");
  const [includeRawCad, setIncludeRawCad] = useState(false);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);

  const selectedDecisions = useMemo(
    () => decisions.filter((d) => selected.includes(d.id)),
    [decisions, selected]
  );
  const selectedRisk = selectedDecisions.some((d) => d.is_stale || d.approval_status !== "approved");

  const refresh = async () => {
    const [pkgPage, decisionPage] = await Promise.all([
      fetchRfqPackages(),
      fetchCostDecisions({ limit: 100 }),
    ]);
    setPackages(pkgPage.packages);
    setDecisions(decisionPage.cost_decisions);
  };

  useEffect(() => {
    refresh()
      .catch((err) => toast.error(err instanceof Error ? err.message : "Could not load RFQ packages"))
      .finally(() => setLoading(false));
  }, []);

  const toggle = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const create = async () => {
    if (selected.length === 0) return;
    setCreating(true);
    try {
      const pkg = await createRfqPackage({
        decisionIds: selected,
        title,
        supplierName,
        note,
        includeRawCad,
      });
      setPackages((prev) => [pkg, ...prev]);
      setSelected([]);
      setTitle("");
      setSupplierName("");
      setNote("");
      setIncludeRawCad(false);
      toast.success("RFQ package generated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not generate package");
    } finally {
      setCreating(false);
    }
  };

  const download = async (pkg: RfqPackageSummary) => {
    setDownloading(pkg.id);
    try {
      await downloadRfqPackage(pkg.id, pkg.title);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Download failed");
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="RFQ packages"
        subtitle="Supplier evidence bundles generated from saved cost decisions."
        actions={
          <Button variant="secondary" size="sm" onClick={() => void refresh()} disabled={loading}>
            <RefreshCw /> Refresh
          </Button>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <FileCheck2 className="size-4" />
            New package
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 lg:grid-cols-3">
            <label className="space-y-1 text-sm">
              <span className="font-medium text-foreground">Title</span>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                placeholder="Pump RFQ package"
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-foreground">Supplier</span>
              <input
                value={supplierName}
                onChange={(e) => setSupplierName(e.target.value)}
                className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm"
                placeholder="optional"
              />
            </label>
            <label className="flex items-end gap-2 text-sm">
              <input
                type="checkbox"
                checked={includeRawCad}
                onChange={(e) => setIncludeRawCad(e.target.checked)}
                className="mb-3 size-4"
              />
              <span className="pb-2 text-muted-foreground">Include raw CAD only if already retained</span>
            </label>
          </div>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="min-h-20 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            placeholder="Buyer note"
          />

          {selectedRisk && (
            <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <span>Selected decisions include stale or unapproved records; the package will preserve those warnings.</span>
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-sm">
              <thead className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="py-2 pr-3">Pick</th>
                  <th className="py-2 pr-4">Decision</th>
                  <th className="py-2 pr-4">Process</th>
                  <th className="py-2 pr-4">Approval</th>
                  <th className="py-2 pr-4">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {decisions.map((decision) => {
                  const risk = riskLabel(decision);
                  return (
                    <tr key={decision.id}>
                      <td className="py-3 pr-3">
                        <input
                          type="checkbox"
                          checked={selected.includes(decision.id)}
                          onChange={() => toggle(decision.id)}
                          className="size-4"
                          aria-label={`Include ${decision.filename} in the RFQ package`}
                        />
                      </td>
                      <td className="py-3 pr-4">
                        <button
                          type="button"
                          onClick={() => router.push(`/cost-decisions/${decision.id}`)}
                          className="font-medium text-foreground hover:text-primary"
                        >
                          {decision.filename}
                        </button>
                        {risk && (
                          <span className="ml-2 rounded-sm bg-amber-100 px-1.5 py-0.5 text-xs text-amber-900">
                            {risk}
                          </span>
                        )}
                      </td>
                      <td className="py-3 pr-4">{decision.make_now_process || "--"}</td>
                      <td className="py-3 pr-4">{decision.approval_status || "unreviewed"}</td>
                      <td className="py-3 pr-4 text-muted-foreground">{dateLabel(decision.created_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <Button onClick={() => void create()} disabled={selected.length === 0 || creating}>
            <FileCheck2 />
            {creating ? "Generating" : `Generate package (${selected.length})`}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Generated packages</CardTitle>
        </CardHeader>
        <CardContent>
          {packages.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {loading ? "Loading..." : "No RFQ packages yet."}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-sm">
                <thead className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="py-2 pr-4">Package</th>
                    <th className="py-2 pr-4">Items</th>
                    <th className="py-2 pr-4">Warnings</th>
                    <th className="py-2 pr-4">Created</th>
                    <th className="py-2 pr-4">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {packages.map((pkg) => (
                    <tr key={pkg.id}>
                      <td className="py-3 pr-4">
                        <button
                          type="button"
                          onClick={() => router.push(`/rfq-packages/${pkg.id}`)}
                          className="font-medium text-foreground hover:text-primary"
                        >
                          {pkg.title}
                        </button>
                        <span className="block text-xs text-muted-foreground">
                          {pkg.supplier_name || "supplier not specified"}
                        </span>
                      </td>
                      <td className="py-3 pr-4">
                        {pkg.approved_count}/{pkg.item_count} approved
                      </td>
                      <td className="py-3 pr-4">
                        {pkg.warnings.length === 0 ? (
                          <span className="inline-flex items-center gap-1 text-emerald-700">
                            <CheckCircle2 className="size-4" /> clear
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-amber-700">
                            <AlertTriangle className="size-4" /> {pkg.warnings.length}
                          </span>
                        )}
                      </td>
                      <td className="py-3 pr-4 text-muted-foreground">{dateLabel(pkg.created_at)}</td>
                      <td className="py-3 pr-4">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => void download(pkg)}
                          disabled={downloading === pkg.id}
                        >
                          <Download />
                          {downloading === pkg.id ? "Downloading" : "ZIP"}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
