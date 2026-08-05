import { AlertTriangle } from "lucide-react";

import type { CostUnitWarning } from "@/lib/api";

/** Persistent recovery guidance for a successful-but-unit-ambiguous decision. */
export function UnitWarningBanner({
  warnings,
}: {
  warnings?: CostUnitWarning[] | null;
}) {
  if (!warnings?.length) return null;

  return (
    <div
      role="alert"
      data-testid="cad-unit-warning"
      className="rounded-[var(--radius)] border border-warn-border bg-warn-bg p-4"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-warn" aria-hidden />
        <div className="min-w-0">
          <p className="text-sm font-semibold text-warn">
            Confirm CAD source units before using this decision.
          </p>
          {warnings.map((warning, index) => (
            <p
              key={`${warning.code}-${index}`}
              className="mt-1 text-sm text-muted-foreground"
            >
              {warning.message}
            </p>
          ))}
          <p className="mt-2 text-xs font-medium text-warn">
            Open Adjust inputs &amp; re-cost, choose Millimetres or Inches, then run the decision again.
          </p>
        </div>
      </div>
    </div>
  );
}
