import * as React from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";
import { TONE, type Tone } from "@/lib/status";

/** Determinate progress bar (track muted; fill primary, or a status tone). */
function Progress({
  value,
  tone,
  className,
}: {
  value: number;
  /** color the fill with a single status tone (quota usage, batch status) */
  tone?: Tone;
  className?: string;
}) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}
    >
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-300",
          tone ? TONE[tone].dot : "bg-primary"
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export type Step = {
  id: string;
  label: string;
  state: "pending" | "active" | "done";
};

/** Staged stepper for long jobs ("Parsing → Checking → Costing"). */
function ProgressSteps({
  steps,
  className,
}: {
  steps: Step[];
  className?: string;
}) {
  return (
    <ol className={cn("space-y-2", className)}>
      {steps.map((s) => (
        <li key={s.id} className="flex items-center gap-2 text-sm">
          <span
            className={cn(
              "flex size-5 items-center justify-center rounded-full border",
              s.state === "done" && "border-pass bg-pass text-white",
              s.state === "active" && "border-primary text-primary",
              s.state === "pending" && "border-border text-muted-foreground"
            )}
          >
            {s.state === "done" ? (
              <Check className="size-3" />
            ) : s.state === "active" ? (
              <Spinner size="sm" className="size-3" />
            ) : null}
          </span>
          <span
            className={cn(
              s.state === "pending"
                ? "text-muted-foreground"
                : "text-foreground"
            )}
          >
            {s.label}
          </span>
        </li>
      ))}
    </ol>
  );
}

export { Progress, ProgressSteps };
