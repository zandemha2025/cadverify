"use client";

import { use, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, ArrowLeft, Download, FileCheck2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  downloadRfqPackage,
  fetchRfqPackage,
  type RfqPackageDetail,
} from "@/lib/api";

function dateLabel(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "--";
}

export default function RfqPackageDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const [pkg, setPkg] = useState<RfqPackageDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    fetchRfqPackage(id)
      .then(setPkg)
      .catch((err) => toast.error(err instanceof Error ? err.message : "Could not load RFQ package"))
      .finally(() => setLoading(false));
  }, [id]);

  const download = async () => {
    if (!pkg) return;
    setDownloading(true);
    try {
      await downloadRfqPackage(pkg.id, pkg.title);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Download failed");
    } finally {
      setDownloading(false);
    }
  };

  if (!pkg) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" onClick={() => router.push("/rfq-packages")}>
          <ArrowLeft /> Back
        </Button>
        <p className="text-sm text-muted-foreground">
          {loading ? "Loading..." : "RFQ package not found."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={pkg.title}
        subtitle={`${pkg.item_count} decisions · ${dateLabel(pkg.created_at)}`}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="ghost" size="sm" onClick={() => router.push("/rfq-packages")}>
              <ArrowLeft /> Back
            </Button>
            <Button variant="secondary" size="sm" onClick={() => void download()} disabled={downloading}>
              <Download /> {downloading ? "Downloading" : "Download ZIP"}
            </Button>
          </div>
        }
      />

      <div className="grid gap-4 lg:grid-cols-4">
        <Card>
          <CardHeader><CardTitle className="text-sm">Approved</CardTitle></CardHeader>
          <CardContent className="text-2xl font-semibold">{pkg.approved_count}/{pkg.item_count}</CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">Stale</CardTitle></CardHeader>
          <CardContent className="text-2xl font-semibold">{pkg.stale_count}</CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">Unvalidated</CardTitle></CardHeader>
          <CardContent className="text-2xl font-semibold">{pkg.unvalidated_count}</CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">Raw CAD</CardTitle></CardHeader>
          <CardContent className="text-2xl font-semibold">{pkg.raw_cad_included ? "Yes" : "No"}</CardContent>
        </Card>
      </div>

      {pkg.warnings.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="size-4 text-amber-700" />
              Warnings
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {pkg.warnings.map((warning, idx) => (
              <div key={`${warning.code}-${idx}`} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900">
                <span className="font-medium">{warning.code}</span>
                <span className="ml-2">{warning.message}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <FileCheck2 className="size-4" />
            Package items
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="py-2 pr-4">Decision</th>
                  <th className="py-2 pr-4">Process</th>
                  <th className="py-2 pr-4">Approval</th>
                  <th className="py-2 pr-4">Flags</th>
                  <th className="py-2 pr-4">Manifest</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {pkg.items.map((item) => (
                  <tr key={item.decision.id}>
                    <td className="py-3 pr-4">
                      <button
                        type="button"
                        onClick={() => router.push(`/cost-decisions/${item.decision.id}`)}
                        className="font-medium text-foreground hover:text-primary"
                      >
                        {item.decision.filename}
                      </button>
                    </td>
                    <td className="py-3 pr-4">{item.decision.make_now_process || "--"}</td>
                    <td className="py-3 pr-4">{item.decision.approval_status}</td>
                    <td className="py-3 pr-4">
                      {[
                        item.decision.is_stale ? "stale" : null,
                        item.decision.unvalidated_confidence ? "unvalidated" : null,
                        item.raw_cad?.included ? "raw CAD" : null,
                      ].filter(Boolean).join(", ") || "clear"}
                    </td>
                    <td className="py-3 pr-4">
                      {item.declared_part ? "normalized-stem exact" : "--"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
