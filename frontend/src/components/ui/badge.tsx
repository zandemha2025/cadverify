import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-sm border font-medium",
  {
    variants: {
      variant: {
        neutral: "border-border bg-muted text-muted-foreground",
        outline: "border-border bg-transparent text-foreground",
        primary: "border-accent-subtle-border bg-accent-subtle text-accent-text",
      },
      size: {
        sm: "px-1.5 py-0.5 text-[11px] leading-4",
        md: "px-2 py-0.5 text-xs leading-4",
      },
    },
    defaultVariants: {
      variant: "neutral",
      size: "md",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, size, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant, size, className }))} {...props} />
  );
}

export { Badge, badgeVariants };
