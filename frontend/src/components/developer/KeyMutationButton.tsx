"use client";

import { useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { KEY_REVEAL_EVENT } from "@/lib/key-reveal";

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
  const [loading, setLoading] = useState(false);

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

    setLoading(true);
    try {
      const response = await fetch(path, {
        method,
        headers: operation === "create" ? { "content-type": "application/json" } : undefined,
        body: operation === "create" ? JSON.stringify({ name: "Default" }) : undefined,
      });
      // Always consume the finite response before refreshing. This prevents an
      // intentional navigation from aborting an otherwise successful mutation.
      const text = await response.text();
      if (!response.ok) {
        throw new Error(errorCopy(text, `${SUCCESS_COPY[operation]} failed. Try again.`));
      }

      if (operation !== "revoke") {
        window.dispatchEvent(new Event(KEY_REVEAL_EVENT));
      }
      toast.success(SUCCESS_COPY[operation]);
      router.refresh();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : "API key update failed. Try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      className={className}
      loading={loading}
      onClick={mutate}
    >
      {children}
    </Button>
  );
}
