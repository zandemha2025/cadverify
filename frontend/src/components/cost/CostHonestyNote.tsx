/**
 * CostHonestyNote — the non-negotiable honesty label that travels with EVERY
 * persisted / exported / shared should-cost artifact. Presentational (no hooks),
 * so it is safe to render in a Server Component (the public share page).
 *
 * A saved decision must never look more certain than the live one: this states
 * plainly that the figure is an assumption-based should-cost with its confidence
 * band "not yet validated" — never a certified quote.
 */
import { CircleDashed } from "lucide-react";

export function CostHonestyNote({ className }: { className?: string }) {
  return (
    <div
      className={`flex items-start gap-2 rounded-[var(--radius)] border border-border bg-muted px-3 py-2.5 text-xs text-muted-foreground ${className ?? ""}`}
    >
      <CircleDashed className="mt-px size-3.5 shrink-0" aria-hidden />
      <span>
        This is an <span className="font-medium text-foreground">explainable should-cost</span>{" "}
        estimate — every driver is provenance-tagged and the confidence band is{" "}
        <span className="font-medium text-foreground">assumption-based, not yet validated</span>{" "}
        on your parts. It is not a validated quote.
      </span>
    </div>
  );
}
