"use client";

/**
 * RecentParts — "my recent parts" strip for the part door, straight off the REAL
 * analyses endpoint (`fetchAnalyses`, session-scoped server-side). It shows only
 * what the engine actually has: real rows, real verdicts, real timestamps — and
 * an honest empty/loading/error state, never an invented row. Each chip opens the
 * stored analysis at its real detail route.
 */

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { History } from "lucide-react";
import { fetchAnalyses, type AnalysisSummary } from "@/lib/api";
import { StatusBadge } from "@/components/ui/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Stagger } from "@/components/ui/motion";

const RECENT_LIMIT = 6;

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

type Status = "loading" | "error" | "ready";

export function RecentParts() {
  const router = useRouter();
  const [status, setStatus] = useState<Status>("loading");
  const [items, setItems] = useState<AnalysisSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    fetchAnalyses({ limit: RECENT_LIMIT })
      .then((page) => {
        if (cancelled) return;
        setItems(page.analyses);
        setStatus("ready");
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Could not load recent parts");
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const retry = useCallback(() => setReloadKey((k) => k + 1), []);

  return (
    <section aria-label="Recent parts" className="space-y-2">
      <div className="flex items-center gap-2">
        <History className="size-3.5 text-subtle-foreground" />
        <span className="cv-eyebrow">My recent parts</span>
      </div>

      {status === "loading" && (
        <div className="flex flex-wrap gap-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-9 w-44" />
          ))}
        </div>
      )}

      {status === "error" && (
        <p className="text-xs text-muted-foreground">
          {error}{" "}
          <button
            type="button"
            onClick={retry}
            className="font-medium text-accent-text underline-offset-2 hover:underline"
          >
            Retry
          </button>
        </p>
      )}

      {status === "ready" && items.length === 0 && (
        <p className="rounded-[var(--radius)] border border-dashed border-border px-3 py-2.5 text-xs text-subtle-foreground">
          No parts yet — the parts you drop will show up here.
        </p>
      )}

      {status === "ready" && items.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <Stagger step={45} ms={280}>
            {items.map((a) => (
              <button
                key={a.ulid}
                type="button"
                onClick={() => router.push(`/analyses/${a.ulid}`)}
                title={`Open ${a.filename}`}
                className="group inline-flex max-w-full items-center gap-2 rounded-[var(--radius)] border border-border bg-card px-2.5 py-1.5 text-left transition-colors hover:border-border-strong hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="num min-w-0 truncate text-xs font-medium text-foreground">
                  {a.filename}
                </span>
                <StatusBadge verdict={a.overall_verdict} size="sm" />
                <span className="num shrink-0 text-[10px] text-subtle-foreground">
                  {relativeTime(a.created_at)}
                </span>
              </button>
            ))}
          </Stagger>
        </div>
      )}
    </section>
  );
}
