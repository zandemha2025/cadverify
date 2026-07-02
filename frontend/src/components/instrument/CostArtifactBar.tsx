"use client";

/**
 * CostArtifactBar — turns the live should-cost decision into a durable artifact
 * the buyer can KEEP. It appears in the instrument's decision panel once the
 * authed cost route has persisted the decision (`report.saved`), and surfaces
 * the four affordances the flagship surface was missing: SAVE (open in history),
 * EXPORT (PDF / JSON / CSV), and SHARE (public link) — every button hits a real
 * cost-decision endpoint, no lying stubs.
 *
 * HONESTY (#1 rule): the artifact carries the SAME confidence labeling as the
 * live instrument. The bar states plainly that this is an assumption-based
 * should-cost, not a validated quote; the exports/PDF/share preserve the
 * provenance tags and the "not yet validated" band verbatim (backend-enforced).
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  Bookmark,
  Check,
  Download,
  ExternalLink,
  FileJson,
  Share2,
  Sheet,
} from "lucide-react";
import {
  downloadCostPdf,
  exportCostJson,
  exportCostCsv,
  shareCostDecision,
} from "@/lib/api";
import ShareModal from "@/components/ShareModal";

type Action = "pdf" | "json" | "csv" | "share";

function BarButton({
  icon: Icon,
  label,
  busy,
  onClick,
  primary,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  busy?: boolean;
  onClick: () => void;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={[
        "inline-flex items-center gap-1.5 rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
        primary
          ? "border-accent-subtle-border bg-accent-subtle text-accent-text hover:bg-accent-subtle/70"
          : "border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground",
      ].join(" ")}
    >
      <Icon className="size-3.5" />
      {busy ? "…" : label}
    </button>
  );
}

export function CostArtifactBar({
  saved,
  filename,
}: {
  saved: { id: string; url: string };
  filename: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = React.useState<Action | null>(null);
  const [shareUrl, setShareUrl] = React.useState<string | null>(null);
  const [showModal, setShowModal] = React.useState(false);

  const run = React.useCallback(
    async (action: Action, fn: () => Promise<void>) => {
      setBusy(action);
      try {
        await fn();
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "Action failed");
      } finally {
        setBusy(null);
      }
    },
    []
  );

  const onShare = () =>
    run("share", async () => {
      const res = await shareCostDecision(saved.id);
      setShareUrl(res.share_url);
      setShowModal(true);
    });

  return (
    <div className="mt-5 border-t border-border pt-4">
      <div className="flex items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-[11px] text-pass">
          <Check className="size-3.5" />
          Saved to cost history
        </span>
        <button
          type="button"
          onClick={() => router.push(`/cost-decisions/${saved.id}`)}
          className="num inline-flex items-center gap-1 text-[11px] text-accent-text hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ExternalLink className="size-3" /> open
        </button>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <BarButton
          icon={Bookmark}
          label="Open in history"
          onClick={() => router.push(`/cost-decisions/${saved.id}`)}
        />
        <BarButton
          icon={Download}
          label="PDF"
          busy={busy === "pdf"}
          onClick={() => run("pdf", () => downloadCostPdf(saved.id, filename))}
        />
        <BarButton
          icon={FileJson}
          label="JSON"
          busy={busy === "json"}
          onClick={() => run("json", () => exportCostJson(saved.id, filename))}
        />
        <BarButton
          icon={Sheet}
          label="CSV"
          busy={busy === "csv"}
          onClick={() => run("csv", () => exportCostCsv(saved.id, filename))}
        />
        <BarButton
          icon={Share2}
          label="Share"
          primary
          busy={busy === "share"}
          onClick={onShare}
        />
      </div>

      <p className="mt-2.5 text-[11px] leading-relaxed text-subtle-foreground">
        Saved, exported and shared copies keep the provenance tags and the
        confidence band labeled{" "}
        <span className="text-muted-foreground">assumption-based, not yet validated</span>{" "}
        — an explainable should-cost, not a validated quote.
      </p>

      {showModal && shareUrl && (
        <ShareModal
          shareUrl={shareUrl}
          onClose={() => setShowModal(false)}
          kind="cost"
        />
      )}
    </div>
  );
}
