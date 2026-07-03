"use client";

/**
 * DepthPanel — the right-anchored slide-over that houses the part hero's depth
 * surfaces (the per-process DFM audit, the glass box, Compare, History). Depth is
 * one click away, never the only path (D1: findings-only-in-a-tab fails review).
 *
 * Built on Radix Dialog for the free focus trap / Escape / scroll lock / aria
 * wiring, but the enter slide is an inline, TEMPO-aware transition (×0.1 working,
 * 0 reduced motion) rather than a utility-class animation — the same motion
 * grammar as `<Rise>`.
 */

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useTempo } from "@/lib/tempo";
import { STRIKE } from "@/components/ui/motion";

export function DepthPanel({
  open,
  onOpenChange,
  eyebrow,
  title,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  eyebrow?: string;
  title: string;
  children: React.ReactNode;
}) {
  const { dur } = useTempo();
  const [shown, setShown] = React.useState(false);

  React.useEffect(() => {
    if (!open) {
      setShown(false);
      return;
    }
    const raf = requestAnimationFrame(() => setShown(true));
    return () => cancelAnimationFrame(raf);
  }, [open]);

  const d = dur(360);

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className="fixed inset-0 z-50 bg-canvas/70"
          style={{ opacity: shown ? 1 : 0, transition: `opacity ${d}ms ${STRIKE}` }}
        />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className="fixed inset-y-0 right-0 z-50 flex h-full w-full max-w-xl flex-col border-l border-border bg-background shadow-xl focus:outline-none"
          style={{
            transform: shown ? "translateX(0)" : "translateX(100%)",
            transition: `transform ${d}ms ${STRIKE}`,
            willChange: "transform",
          }}
        >
          <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
            <div className="min-w-0">
              {eyebrow && <span className="cv-eyebrow">{eyebrow}</span>}
              <DialogPrimitive.Title className="mt-1 truncate text-display font-semibold text-foreground">
                {title}
              </DialogPrimitive.Title>
            </div>
            <DialogPrimitive.Close className="rounded-sm p-1 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <X className="size-4" />
              <span className="sr-only">Close</span>
            </DialogPrimitive.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
