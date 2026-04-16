"use client";

import { useState } from "react";
import { shareAnalysis, unshareAnalysis } from "@/lib/api";
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
  const [error, setError] = useState<string | null>(null);

  async function handleShare() {
    setLoading(true);
    setError(null);
    try {
      const result = await shareAnalysis(analysisId);
      setIsShared(true);
      setShareUrl(result.share_url);
      setShowModal(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to share");
    } finally {
      setLoading(false);
    }
  }

  async function handleRevoke() {
    setLoading(true);
    setError(null);
    try {
      await unshareAnalysis(analysisId);
      setIsShared(false);
      setShareUrl(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to revoke share");
    } finally {
      setLoading(false);
    }
  }

  async function handleCopyLink() {
    if (!shareUrl) return;
    const fullUrl =
      typeof window !== "undefined"
        ? `${window.location.origin}${shareUrl}`
        : shareUrl;
    try {
      await navigator.clipboard.writeText(fullUrl);
    } catch {
      /* noop */
    }
  }

  return (
    <>
      {!isShared ? (
        <button
          type="button"
          onClick={handleShare}
          disabled={loading}
          className="rounded-md border px-3 py-1 text-sm font-medium hover:bg-gray-50 disabled:opacity-50"
        >
          {loading ? "Sharing..." : "Share"}
        </button>
      ) : (
        <div className="flex items-center gap-2">
          <span className="rounded-md bg-green-50 px-2 py-1 text-xs font-medium text-green-700">
            Shared
          </span>
          <button
            type="button"
            onClick={() => setShowModal(true)}
            className="rounded-md border px-2 py-1 text-xs hover:bg-gray-50"
          >
            Copy link
          </button>
          <button
            type="button"
            onClick={handleRevoke}
            disabled={loading}
            className="rounded-md border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50 disabled:opacity-50"
          >
            {loading ? "Revoking..." : "Revoke"}
          </button>
        </div>
      )}

      {error && (
        <p className="mt-1 text-xs text-red-600">{error}</p>
      )}

      {showModal && shareUrl && (
        <ShareModal
          shareUrl={shareUrl}
          onClose={() => setShowModal(false)}
        />
      )}
    </>
  );
}
