import * as React from "react";
import { cn } from "@/lib/utils";

function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-[var(--radius)] bg-muted",
        className
      )}
      {...props}
    />
  );
}

/** Skeleton rows for a table while data loads. */
function TableSkeleton({
  rows = 5,
  cols = 4,
}: {
  rows?: number;
  cols?: number;
}) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-3">
          {Array.from({ length: cols }).map((_, c) => (
            <Skeleton key={c} className="h-9 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Skeleton block sized like a card. */
function CardSkeleton({ className }: { className?: string }) {
  return <Skeleton className={cn("h-40 w-full", className)} />;
}

export { Skeleton, TableSkeleton, CardSkeleton };
