"use client";

import { useState } from "react";
import { Share2 } from "lucide-react";
import { toast } from "sonner";
import { shareAnalysis, unshareAnalysis } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import ShareModal from "./ShareModal";

interface ShareButtonProps {
  analysisId: string;
  initialShared?: boolean;
  initialShareUrl?: string | null;
}

export default function ShareButton({
  analysisId,
  initialShared = false,
  initialShareUrl = null,
}: ShareButtonProps) {
  const [isShared, setIsShared] = useState(initialShared);
  const [shareUrl, setShareUrl] = useState<string | null>(initialShareUrl);
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);

  async function handleShare() {
    setLoading(true);
    try {
      const result = await shareAnalysis(analysisId);
      setIsShared(true);
      setShareUrl(result.share_url);
      setShowModal(true);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to share");
    } finally {
      setLoading(false);
    }
  }

  async function handleRevoke() {
    setLoading(true);
    try {
      await unshareAnalysis(analysisId);
      setIsShared(false);
      setShareUrl(null);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to revoke share");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      {!isShared ? (
        <Button
          variant="secondary"
          size="sm"
          loading={loading}
          onClick={handleShare}
        >
          {!loading && <Share2 />}
          Share
        </Button>
      ) : (
        <div className="flex items-center gap-2">
          <StatusBadge tone="pass" label="Shared" size="sm" />
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setShowModal(true)}
          >
            Copy link
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-fail hover:text-fail"
            loading={loading}
            onClick={handleRevoke}
          >
            Revoke
          </Button>
        </div>
      )}

      {showModal && shareUrl && (
        <ShareModal shareUrl={shareUrl} onClose={() => setShowModal(false)} />
      )}
    </>
  );
}
