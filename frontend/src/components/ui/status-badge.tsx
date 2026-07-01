import * as React from "react";
import { cn } from "@/lib/utils";
import {
  TONE,
  TONE_ICON,
  verdictTone,
  verdictLabel,
  severityTone,
  severityLabel,
  batchStatusTone,
  confidenceTone,
  type Tone,
} from "@/lib/status";

export interface StatusBadgeProps
  extends React.HTMLAttributes<HTMLSpanElement> {
  /** explicit tone overrides the resolvers below */
  tone?: Tone;
  verdict?: string;
  severity?: string;
  status?: string;
  confidence?: string;
  /** explicit label overrides the resolved label */
  label?: string;
  /** show the leading lucide icon (default true). When false, a colored dot is shown instead so status is never color-only. */
  icon?: boolean;
  size?: "sm" | "md";
}

/**
 * The ONE pill for every verdict / severity / batch-status / confidence in the
 * app. Resolves {tone, label, Icon} from lib/status and renders token classes.
 */
export function StatusBadge({
  tone: toneProp,
  verdict,
  severity,
  status,
  confidence,
  label: labelProp,
  icon = true,
  size = "md",
  className,
  ...props
}: StatusBadgeProps) {
  let tone: Tone = toneProp ?? "neutral";
  let label = labelProp ?? "";

  if (!toneProp) {
    if (verdict !== undefined) tone = verdictTone(verdict);
    else if (severity !== undefined) tone = severityTone(severity);
    else if (status !== undefined) tone = batchStatusTone(status);
    else if (confidence !== undefined) tone = confidenceTone(confidence);
  }
  if (!labelProp) {
    if (verdict !== undefined) label = verdictLabel(verdict);
    else if (severity !== undefined) label = severityLabel(severity);
    else if (status !== undefined)
      label = status.charAt(0).toUpperCase() + status.slice(1);
    else if (confidence !== undefined)
      label = confidence.charAt(0).toUpperCase() + confidence.slice(1);
  }

  const Icon = TONE_ICON[tone];
  const t = TONE[tone];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm border font-medium",
        size === "sm"
          ? "px-1.5 py-0.5 text-[11px] leading-4"
          : "px-2 py-0.5 text-xs leading-4",
        t.bg,
        t.fg,
        t.border,
        className
      )}
      {...props}
    >
      {icon ? (
        <Icon className="size-3.5" aria-hidden />
      ) : (
        <span className={cn("size-1.5 rounded-full", t.dot)} aria-hidden />
      )}
      {label}
    </span>
  );
}
