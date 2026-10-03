"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { KEY_REVEAL_EVENT, type KeyRevealDetail } from "@/lib/key-reveal";

type Operation = "create" | "rotate" | "revoke";

interface Props {
  operation: Operation;
  keyId?: number;
  variant?: "primary" | "secondary" | "ghost" | "destructive" | "link";
  size?: "sm" | "md" | "lg" | "icon";
  className?: string;
  children: ReactNode;
}

const SUCCESS_COPY: Record<Operation, string> = {
  create: "API key created",
  rotate: "API key rotated",
  revoke: "API key revoked",
};

function errorCopy(text: string, fallback: string): string {
  if (!text) return fallback;
  try {
    const payload = JSON.parse(text) as {
      detail?: string | { message?: string };
      message?: string;
    };
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail && typeof payload.detail === "object" && payload.detail.message) {
      return payload.detail.message;
    }
    if (payload.message) return payload.message;
  } catch {
    // Preserve the bounded fallback instead of exposing an HTML error page.
  }
  return fallback;
}

export function KeyMutationButton({
  operation,
  keyId,
  variant = "primary",
  size = "md",
  className,
  children,
}: Props) {
  const router = useRouter();
  const [hydrated, setHydrated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("Production");

  // A server-rendered button can look actionable before React has attached its
  // click handler. On a fast click (or a slow device/network) that silently
  // discards the user's mutation. Keep the control disabled for that brief
  // interval so both humans and browser automation can only click a live
  // handler.
  useEffect(() => setHydrated(true), []);

  const mutate = async () => {
    if (operation !== "create" && !keyId) {
      toast.error("This API key is unavailable. Refresh and try again.");
      return;
    }

    const path = operation === "create"
      ? "/api/proxy/keys"
      : operation === "rotate"
        ? `/api/proxy/keys/${keyId}/rotate`
        : `/api/proxy/keys/${keyId}`;
    const method = operation === "revoke" ? "DELETE" : "POST";

    if (operation === "create" && !open) {
      setOpen(true);
      return;
    }
    setLoading(true);
    try {
      const response = await fetch(path, {
        method,
        headers: operation === "create" ? { "content-type": "application/json" } : undefined,
        body: operation === "create" ? JSON.stringify({ name }) : undefined,
      });
      // Always consume the finite response before refreshing. This prevents an
      // intentional navigation from aborting an otherwise successful mutation.
      const text = await response.text();
      if (!response.ok) {
        throw new Error(errorCopy(text, `${SUCCESS_COPY[operation]} failed. Try again.`));
      }

      if (operation !== "revoke") {
        const payload = JSON.parse(text) as { token?: unknown };
        if (typeof payload.token !== "string" || !payload.token.startsWith("cv_live_")) {
          throw new Error("The API key was created but its one-time secret was not returned. Rotate it before use.");
        }
        window.dispatchEvent(
          new CustomEvent<KeyRevealDetail>(KEY_REVEAL_EVENT, {
            detail: { token: payload.token },
          }),
        );
      }
      toast.success(SUCCESS_COPY[operation]);
      setOpen(false);
      router.refresh();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "API key update failed. Try again.");
    } finally {
      setLoading(false);
    }
  };

  const trigger = (
    <Button
      type="button"
      variant={variant}
      size={size}
      className={className}
      disabled={!hydrated}
      loading={loading}
      onClick={mutate}
    >
      {children}
    </Button>
  );

  if (operation !== "create") return trigger;
  return (
    <>
      {trigger}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create API key</DialogTitle>
            <DialogDescription>Name the service or environment that will use this key.</DialogDescription>
          </DialogHeader>
          <label className="grid gap-2 text-sm font-medium text-foreground">
            Key name
            <Input
              autoFocus
              maxLength={80}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Production"
            />
          </label>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="button" loading={loading} disabled={!name.trim()} onClick={mutate}>Create key</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
