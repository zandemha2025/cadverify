"use client";

import { useRouter } from "next/navigation";
import { GitCompareArrows } from "lucide-react";
import CostDecisionHistoryTable from "@/components/CostDecisionHistoryTable";
import { CostHonestyNote } from "@/components/cost/CostHonestyNote";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";

export default function CostHistoryPage() {
  const router = useRouter();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Cost history"
        subtitle="Your saved should-cost / make-vs-buy decisions — export, share, and compare them."
        actions={
          <Button
            variant="secondary"
            size="sm"
            onClick={() => router.push("/cost-decisions/compare")}
          >
            <GitCompareArrows /> Compare decisions
          </Button>
        }
      />

      <CostHonestyNote />

      <section className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Saved decisions
        </h2>
        <CostDecisionHistoryTable />
      </section>
    </div>
  );
}
