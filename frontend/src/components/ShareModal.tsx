"use client";

import { useState } from "react";

interface ShareModalProps {
  shareUrl: string;
  onClose: () => void;
}

export default function ShareModal({ shareUrl, onClose }: ShareModalProps) {
  const [copied, setCopied] = useState(false);

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
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-[28rem] rounded-lg bg-white p-6 shadow-xl space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Share this analysis</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
            aria-label="Close"
          >
            &#x2715;
          </button>
        </div>

        <p className="text-sm text-gray-600">
          Anyone with this link can view a read-only version of this analysis.
        </p>

        <div className="flex items-center gap-2">
          <input
            type="text"
            readOnly
            value={fullUrl}
            className="flex-1 rounded-md border bg-gray-50 px-3 py-2 font-mono text-sm text-gray-700"
            onFocus={(e) => e.target.select()}
          />
          <button
            type="button"
            onClick={handleCopy}
            className="rounded-md border px-3 py-2 text-sm font-medium hover:bg-gray-50"
          >
            {copied ? "Copied!" : "Copy link"}
          </button>
        </div>

        <button
          type="button"
          onClick={onClose}
          className="w-full rounded-md bg-black px-4 py-2 text-sm text-white hover:bg-gray-800"
        >
          Done
        </button>
      </div>
    </div>
  );
}
