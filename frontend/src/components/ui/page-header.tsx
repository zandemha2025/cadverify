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
        "flex flex-wrap items-start justify-between gap-3",
        className
      )}
    >
      <div className="min-w-0 flex-[1_1_16rem]">
        <div className="flex items-center gap-2">
          <h1 className="min-w-0 break-words text-xl font-semibold leading-7 text-foreground">
            {title}
          </h1>
          {badge}
        </div>
        {subtitle && (
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        )}
      </div>
      {actions && (
        <div className="flex min-w-0 w-full flex-wrap items-center gap-2 sm:w-auto sm:shrink-0 max-w-full">{actions}</div>
      )}
    </div>
  );
}
