"use client";

/**
 * CALIBRATION SWITCHER — top-bar chip that names the rate context every verdict
 * is costed against. It reads the REAL rate-library: the effective card (governed
 * vs default v0) and the org's authored versions. It NEVER invents a shop name or
 * a rate count — the design's "Midwest Precision CNC · 19 rates" is illustrative.
 *
 * Today there is exactly one live calibration context per org (the engine resolves
 * one effective card), so the menu is a truthful STATUS panel with authored
 * versions, not a fake multi-shop toggle.
 */
import { useEffect, useState } from "react";
import { C, MONO } from "@/lib/verify/tokens";
import {
  calibrationLabel,
  effectiveRateCard,
  listRateVersions,
  type EffectiveRateCard,
  type RateVersionsPage,
} from "@/lib/verify/rate-api";

export function CalibrationSwitcher({ onOpenCalibration }: { onOpenCalibration: () => void }) {
  const [open, setOpen] = useState(false);
  const [eff, setEff] = useState<EffectiveRateCard | null>(null);
  const [page, setPage] = useState<RateVersionsPage | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    Promise.all([effectiveRateCard(), listRateVersions()]).then(
      ([e, p]) => {
        if (!live) return;
        setEff(e);
        setPage(p);
      },
      () => live && setFailed(true)
    );
    return () => {
      live = false;
    };
  }, []);

  const { label, grounded } = calibrationLabel(eff, page);
  const chip = failed ? "calibration unavailable" : label;
  const versionCount = page?.versions.length ?? 0;
  const publishedCount = page?.versions.filter((v) => v.status === "published" || v.is_published).length ?? 0;

  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="Calibration context — the rate card every verdict is costed against"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          border: `1px solid ${C.hair}`,
          background: "#fff",
          borderRadius: 999,
          padding: "6px 12px",
          fontSize: 12,
          color: C.ink60,
          cursor: "pointer",
          fontFamily: "inherit",
          maxWidth: 320,
        }}
      >
        <span
          aria-hidden
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            flexShrink: 0,
            background: grounded ? C.shop : "transparent",
            border: grounded ? "none" : `1.5px solid ${C.ink40}`,
          }}
        />
        <span
          style={{
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {chip}
        </span>
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {open && (
        <>
          <div
            style={{ position: "fixed", inset: 0, zIndex: 44 }}
            onClick={() => setOpen(false)}
          />
          <div
            style={{
              position: "absolute",
              top: 40,
              right: 0,
              zIndex: 45,
              width: 340,
              background: C.panel,
              border: `1px solid ${C.hair}`,
              borderRadius: 14,
              boxShadow: "0 18px 50px -18px rgba(23,24,26,0.25)",
              padding: 12,
              animation: "vscreenIn 180ms cubic-bezier(0.2,0,0,1) both",
            }}
          >
            <p style={{ margin: "2px 4px 10px", fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.14em", color: C.ink45 }}>
              CALIBRATION CONTEXT
            </p>
            <div style={{ border: `1px solid ${C.hair}`, borderRadius: 10, padding: "11px 13px" }}>
              <p style={{ margin: 0, fontSize: 13, color: C.ink }}>{chip}</p>
              <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink50, lineHeight: 1.55 }}>
                {failed
                  ? "Couldn't read the rate library — no context is claimed."
                  : eff?.using_governed
                    ? "A published governed rate card is in effect — verdicts cost against it."
                    : "The engine is using the built-in default rate card (v0). Publish a governed card in Calibration & truth to bind your real numbers."}
              </p>
            </div>
            <p style={{ margin: "8px 4px 4px", fontFamily: MONO, fontSize: 10, color: C.ink45, lineHeight: 1.55 }}>
              {failed
                ? "No rate-library status is claimed while the read is failing."
                : `${versionCount} authored rate-card version${versionCount === 1 ? "" : "s"} · ${publishedCount} published · old records stay pinned to the version used when computed.`}
            </p>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                onOpenCalibration();
              }}
              style={{
                marginTop: 8,
                width: "100%",
                textAlign: "left",
                background: C.sunken,
                border: `1px solid ${C.hair}`,
                borderRadius: 10,
                padding: "10px 13px",
                cursor: "pointer",
                fontFamily: "inherit",
                fontSize: 12.5,
                color: C.ink,
              }}
            >
              Open Calibration &amp; truth →
            </button>
          </div>
        </>
      )}
    </div>
  );
}
