import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import { distinctErrorDetail } from "@/lib/error-copy";
import { Button } from "@/components/ui/button";

/** Inline fail-tinted card + retry. Replaces the ad-hoc red banners. */
export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  className,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
  className?: string;
}) {
  const detail = distinctErrorDetail(title, message);
  return (
    <div
      role="alert"
      className={cn(
        "rounded-[var(--radius)] border border-fail-border bg-fail-bg p-4",
        className
      )}
    >
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-5 shrink-0 text-fail" />
        <div className="flex-1">
          <p className="text-sm font-semibold text-fail">{title}</p>
          {detail && (
            <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
          )}
          {onRetry && (
            <Button
              variant="secondary"
              size="sm"
              className="mt-3"
              onClick={onRetry}
            >
              Try again
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
