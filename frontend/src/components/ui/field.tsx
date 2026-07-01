import * as React from "react";
import { cn } from "@/lib/utils";
import { Label } from "@/components/ui/label";

/** Consistent label / control / helper-or-error stack. */
export function Field({
  label,
  htmlFor,
  error,
  hint,
  className,
  children,
}: {
  label?: string;
  htmlFor?: string;
  error?: string | null;
  hint?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("space-y-1", className)}>
      {label && <Label htmlFor={htmlFor}>{label}</Label>}
      {children}
      {error ? (
        <p className="text-xs text-fail">{error}</p>
      ) : hint ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}
