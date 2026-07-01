import * as React from "react";
import { cn } from "@/lib/utils";

/** Page title + optional subtitle + right-aligned actions. */
export function PageHeader({
  title,
  subtitle,
  actions,
  badge,
  className,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  badge?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between",
        className
      )}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold leading-7 text-foreground">
            {title}
          </h1>
          {badge}
        </div>
        {subtitle && (
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 items-center gap-2">{actions}</div>
      )}
    </div>
  );
}
