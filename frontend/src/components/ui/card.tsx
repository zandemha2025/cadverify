import * as React from "react";
import { cn } from "@/lib/utils";
import { TONE, type Tone } from "@/lib/status";

function Card({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { tone?: Tone }) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius)] border border-border bg-card text-card-foreground",
        tone && TONE[tone].border,
        className
      )}
      {...props}
    />
  );
}

function CardHeader({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { tone?: Tone }) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 border-b border-border px-6 py-4",
        tone && cn(TONE[tone].bg, TONE[tone].border),
        className
      )}
      {...props}
    />
  );
}

function CardTitle({
  className,
  ...props
}: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn(
        "text-base font-semibold leading-[22px] text-foreground",
        className
      )}
      {...props}
    />
  );
}

function CardDescription({
  className,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p
      className={cn("text-xs leading-4 text-muted-foreground", className)}
      {...props}
    />
  );
}

function CardContent({
  className,
  compact,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { compact?: boolean }) {
  return <div className={cn(compact ? "p-4" : "p-6", className)} {...props} />;
}

function CardFooter({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 border-t border-border px-6 py-4",
        className
      )}
      {...props}
    />
  );
}

/** KPI tile: eyebrow label + big mono value + optional unit/hint/delta. */
function MetricCard({
  label,
  value,
  unit,
  hint,
  delta,
  className,
}: {
  label: string;
  value: React.ReactNode;
  unit?: string;
  hint?: string;
  delta?: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("p-4", className)}>
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <div className="mt-1 flex items-baseline gap-1">
        <span className="num text-display font-semibold leading-9 text-foreground">
          {value}
        </span>
        {unit && (
          <span className="num text-sm text-muted-foreground">{unit}</span>
        )}
      </div>
      {(hint || delta) && (
        <p className="mt-1 text-xs text-muted-foreground">
          {delta} {hint}
        </p>
      )}
    </Card>
  );
}

export {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
  MetricCard,
};
