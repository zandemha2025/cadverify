"use client";

import { useState } from "react";
import AnalysisHistoryTable from "@/components/AnalysisHistoryTable";
import QuotaDisplay from "@/components/QuotaDisplay";
import type { RateLimits } from "@/lib/api";

export default function DashboardPage() {
  const [rateLimits, setRateLimits] = useState<RateLimits | undefined>();

  return (
    <main className="space-y-8">
      <h1 className="text-2xl font-semibold">Dashboard</h1>

      {/* Quota Consumption */}
      <section>
        <h2 className="mb-2 text-lg font-medium text-gray-700">
          Quota Consumption
        </h2>
        <div className="rounded-md border p-4">
          <QuotaDisplay rateLimits={rateLimits} />
        </div>
      </section>

      {/* Recent Analyses */}
      <section>
        <h2 className="mb-2 text-lg font-medium text-gray-700">
          Recent Analyses
        </h2>
        <AnalysisHistoryTable onRateLimitsUpdate={setRateLimits} />
      </section>
    </main>
  );
}
