"use client";
import { useEffect, useState } from "react";

export function RevealOnceModal() {
  const [token, setToken] = useState<string | null>(null);
  const [acknowledged, setAck] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const m = document.cookie.match(/(?:^|;\s*)cv_mint_once=([^;]+)/);
    if (m) {
      setToken(decodeURIComponent(m[1]));
      // scrub immediately so a reload doesn't re-reveal
      document.cookie = "cv_mint_once=; Max-Age=0; path=/dashboard/keys";
    }
  }, []);

  if (!token) return null;

  async function copy() {
    if (!token) return;
    await navigator.clipboard.writeText(token);
    setCopied(true);
  }

  function dismiss() {
    setToken(null);
    // Paranoid: also clear sessionStorage if anything else mirrored it.
    try {
      sessionStorage.removeItem("cv_mint_once");
    } catch {
      /* noop */
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-center bg-black/40"
    >
      <div className="w-[32rem] rounded-lg bg-white p-6 space-y-4 shadow-xl">
        <h2 className="text-lg font-semibold">Save your API key</h2>
        <p className="text-sm text-neutral-600">
          Copy it now — we will not show it again.
        </p>
        <pre className="rounded-md bg-neutral-100 p-3 font-mono text-sm break-all">
          {token}
        </pre>
        <div className="flex gap-3 items-center">
          <button
            type="button"
            onClick={copy}
            className="rounded-md border px-3 py-1 text-sm"
          >
            {copied ? "Copied" : "Copy"}
          </button>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAck(e.target.checked)}
            />
            I&apos;ve saved it somewhere safe
          </label>
        </div>
        <button
          type="button"
          disabled={!acknowledged}
          onClick={dismiss}
          className="w-full rounded-md bg-black text-white px-4 py-2 disabled:opacity-40"
        >
          Done
        </button>
      </div>
    </div>
  );
}
