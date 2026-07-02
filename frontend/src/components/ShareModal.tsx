"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface ShareModalProps {
  shareUrl: string;
  onClose: () => void;
  /** "analysis" (default) or "cost" — tunes the title + honesty copy. */
  kind?: "analysis" | "cost";
}

export default function ShareModal({ shareUrl, onClose, kind = "analysis" }: ShareModalProps) {
  const [copied, setCopied] = useState(false);
  const isCost = kind === "cost";

  const fullUrl =
    typeof window !== "undefined"
      ? `${window.location.origin}${shareUrl}`
      : shareUrl;

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(fullUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard API may fail in insecure contexts */
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {isCost ? "Share this should-cost decision" : "Share this analysis"}
          </DialogTitle>
          <DialogDescription>
            {isCost
              ? "Anyone with this link can view a read-only copy of this decision. Provenance and the confidence band travel with it — it stays labeled assumption-based, not yet validated."
              : "Anyone with this link can view a read-only version of this analysis."}
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-2">
          <Input
            readOnly
            value={fullUrl}
            className="num flex-1 bg-muted"
            onFocus={(e) => e.target.select()}
          />
          <Button variant="secondary" size="sm" onClick={handleCopy}>
            {copied ? "Copied!" : "Copy link"}
          </Button>
        </div>

        {isCost && (
          <p className="text-xs text-muted-foreground">
            Not a validated quote — an explainable should-cost estimate.
          </p>
        )}

        <DialogFooter>
          <Button onClick={onClose} className="w-full sm:w-auto">
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
