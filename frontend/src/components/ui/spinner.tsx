import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/** The ONE spinner. Use for button-loading and short inline waits only. */
export function Spinner({
  size = "md",
  className,
}: {
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <Loader2
      className={cn(
        "animate-spin text-primary",
        size === "sm" ? "size-4" : "size-6",
        className
      )}
      aria-label="Loading"
    />
  );
}
