"use client";

import { useState } from "react";
import AnalysisHistoryTable from "@/components/AnalysisHistoryTable";
import QuotaDisplay from "@/components/QuotaDisplay";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent } from "@/components/ui/card";
import type { RateLimits } from "@/lib/api";

export default function HistoryPage() {
  const [rateLimits, setRateLimits] = useState<RateLimits | undefined>();

  return (
    <div className="space-y-6">
      <PageHeader
        title="History"
        subtitle="Quota consumption and your recent analyses."
      />

      <section className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Quota consumption
        </h2>
        <Card>
          <CardContent compact>
            <QuotaDisplay rateLimits={rateLimits} />
          </CardContent>
        </Card>
      </section>

      <section className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Recent analyses
        </h2>
        <AnalysisHistoryTable onRateLimitsUpdate={setRateLimits} />
      </section>
    </div>
  );
}
