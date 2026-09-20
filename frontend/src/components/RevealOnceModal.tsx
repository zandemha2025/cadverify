"use client";
import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { KEY_REVEAL_EVENT, type KeyRevealDetail } from "@/lib/key-reveal";

export function RevealOnceModal() {
  const [token, setToken] = useState<string | null>(null);
  const [acknowledged, setAck] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    // Dashboard key creation/rotation delivers the secret only in the no-store
    // mutation response. SSO onboarding may still arrive through the existing
    // short-lived, path-scoped cookie, which is scrubbed immediately.
    const reveal = (event: Event) => {
      const detail = (event as CustomEvent<KeyRevealDetail>).detail;
      if (!detail?.token?.startsWith("cv_live_")) return;
      setToken(detail.token);
      setAck(false);
      setCopied(false);
    };
    const m = document.cookie.match(/(?:^|;\s*)cv_mint_once=([^;]+)/);
    if (m) {
      setToken(decodeURIComponent(m[1]));
      document.cookie = "cv_mint_once=; Max-Age=0; path=/settings/developer";
    }
    window.addEventListener(KEY_REVEAL_EVENT, reveal);
    return () => window.removeEventListener(KEY_REVEAL_EVENT, reveal);
  }, []);

  async function copy() {
    if (!token) return;
    await navigator.clipboard.writeText(token);
    setCopied(true);
  }

  function dismiss() {
    setToken(null);
    setAck(false);
    setCopied(false);
    // Paranoid: also clear sessionStorage if anything else mirrored it.
    try {
      sessionStorage.removeItem("cv_mint_once");
    } catch {
      /* noop */
    }
  }

  return (
    <Dialog
      open={!!token}
      onOpenChange={(open) => {
        // Only allow closing once the user has acknowledged saving the key.
        if (!open && acknowledged) dismiss();
      }}
    >
      <DialogContent hideClose className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Save your API key</DialogTitle>
          <DialogDescription>
            Copy it now — we will not show it again.
          </DialogDescription>
        </DialogHeader>

        <pre className="num overflow-x-auto rounded-[var(--radius)] border border-border bg-muted p-3 text-sm break-all">
          {token}
        </pre>

        <div className="flex items-center gap-3">
          <Button type="button" variant="secondary" size="sm" onClick={copy}>
            {copied ? "Copied" : "Copy"}
          </Button>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAck(e.target.checked)}
              className="size-4 accent-primary"
            />
            I&apos;ve saved it somewhere safe
          </label>
        </div>

        <DialogFooter>
          <Button
            type="button"
            disabled={!acknowledged}
            onClick={dismiss}
            className="w-full"
          >
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
