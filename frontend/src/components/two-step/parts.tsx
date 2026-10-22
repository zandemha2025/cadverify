"use client";

/**
 * Pieces shared by the two-step sign-in page and Account › Security: the QR
 * code an authenticator app scans (drawn from the server's module rows, so the
 * secret never goes to a third-party image service), the manual key, and the
 * recovery codes shown once.
 */
import * as React from "react";

/** A QR code from rows of "1"/"0" modules, with the standard four-module margin. */
export function QrCode({ rows, size = 196, label }: { rows: string[]; size?: number; label: string }) {
  const n = rows.length;
  if (!n) return null;
  const quiet = 4;
  const total = n + quiet * 2;
  let d = "";
  rows.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      if (row[x] !== "1") {
        x += 1;
        continue;
      }
      let run = 1;
      while (x + run < row.length && row[x + run] === "1") run += 1;
      d += `M${x + quiet} ${y + quiet}h${run}v1h-${run}z`;
      x += run;
    }
  });
  return (
    <svg
      role="img"
      aria-label={label}
      width={size}
      height={size}
      viewBox={`0 0 ${total} ${total}`}
      shapeRendering="crispEdges"
      style={{ display: "block", background: "#fff", borderRadius: 8, flex: "none" }}
    >
      <rect width={total} height={total} fill="#fff" />
      <path d={d} fill="#14181F" />
    </svg>
  );
}

export function useCopy(): [string | null, (key: string, text: string) => void] {
  const [copied, setCopied] = React.useState<string | null>(null);
  const copy = React.useCallback((key: string, text: string) => {
    void navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(key);
        window.setTimeout(() => setCopied((c) => (c === key ? null : c)), 2000);
      },
      () => setCopied(null),
    );
  }, []);
  return [copied, copy];
}

const mono: React.CSSProperties = {
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
  fontVariantNumeric: "tabular-nums",
};

export function ManualKey({ value }: { value: string }) {
  const [copied, copy] = useCopy();
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
      <code style={{ ...mono, fontSize: 13.5, letterSpacing: ".04em", overflowWrap: "anywhere", userSelect: "all" }}>{value}</code>
      <button type="button" className="btn sm" onClick={() => copy("key", value.replace(/\s+/g, ""))}>
        {copied === "key" ? "Copied" : "Copy key"}
      </button>
    </div>
  );
}

/** The ten recovery codes, shown once, with copy and download. */
export function RecoveryCodes({ codes, account }: { codes: string[]; account: string }) {
  const [copied, copy] = useCopy();
  const text = `ScaleCAD recovery codes for ${account}\nEach code works once. Keep them somewhere safe.\n\n${codes.join("\n")}\n`;
  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "scalecad-recovery-codes.txt";
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <ol
        aria-label="Recovery codes"
        style={{
          ...mono,
          margin: 0,
          padding: "10px 12px",
          listStyle: "none",
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(118px, 1fr))",
          gap: "6px 14px",
          fontSize: 14,
          background: "#F6F7F8",
          border: "1px solid rgba(20,24,31,.08)",
          borderRadius: 12,
        }}
      >
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ol>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button type="button" className="btn sm" onClick={() => copy("codes", codes.join("\n"))}>
          {copied === "codes" ? "Copied" : "Copy codes"}
        </button>
        <button type="button" className="btn sm" onClick={download}>
          Download .txt
        </button>
      </div>
    </div>
  );
}

/** Six digits from whatever was typed or pasted ("123 456", "123-456"). */
export function cleanCode(raw: string): string {
  return raw.replace(/[\s-]/g, "").slice(0, 6);
}

export const SUPPORT_EMAIL = "nazeem@scalecad.ai";

/** The server's own words for a two-step refusal (they carry the real wait). */
export function twoStepError(status: number, payload: unknown, fallback: string): string {
  const detail =
    payload && typeof payload === "object" && "detail" in payload
      ? (payload as { detail?: unknown }).detail
      : null;
  const message =
    typeof detail === "string"
      ? detail
      : detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string"
        ? (detail as { message: string }).message
        : null;
  if (message && status < 500) return message;
  if (status >= 500) return message && /try again|unavailable/i.test(message) ? message : "The sign-in service couldn't finish this. Try again.";
  return fallback;
}

export function errorCode(payload: unknown): string | null {
  const detail = payload && typeof payload === "object" ? (payload as { detail?: unknown }).detail : null;
  const code = detail && typeof detail === "object" ? (detail as { code?: unknown }).code : null;
  return typeof code === "string" ? code : null;
}
