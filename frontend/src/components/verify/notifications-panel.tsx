"use client";

/**
 * NotificationsPanel — the shell's bell dropdown, backed by durable inbox rows.
 *
 * "States, never nags." Rows are emitted beside domain mutations and can be
 * marked read per user. Empty -> the honest "all caught up" state.
 */
import { useEffect, useState } from "react";
import { C, MONO } from "@/lib/verify/tokens";
import { ConfidenceBand, Spinner } from "./primitives";
import {
  loadNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotifState,
  type DerivedNotif,
  type NotifDest,
} from "@/lib/verify/notifications-api";

const TONE: Record<DerivedNotif["tone"], string> = {
  pass: C.pass,
  cond: C.cond,
  info: C.ink,
};

// The shell owns navigation; when the mount doesn't pass a `nav` callback we fall
// back to the shell's OWN public hotkey contract (H/V/P/R/G/M/T/C on window) so a
// state row is never a dead click — without touching the frozen shell file.
const HOTKEY: Record<NotifDest, string> = {
  records: "r",
  calibration: "c",
  verify: "v",
};

export function NotificationsPanel({
  onClose,
  nav,
}: {
  onClose: () => void;
  nav?: (s: string) => void;
}) {
  const [state, setState] = useState<NotifState>({ loading: true, notifs: [], deliveryCount: null, error: null });

  useEffect(() => {
    let live = true;
    loadNotifications().then(
      (s) => live && setState(s),
      (e) =>
        live &&
        setState({
          loading: false,
          notifs: [],
          deliveryCount: null,
          error: e instanceof Error ? e.message : "could not load",
        })
    );
    return () => {
      live = false;
    };
  }, []);

  const go = (n: DerivedNotif) => {
    markNotificationRead(n.id).catch(() => {});
    const dest = n.dest;
    if (nav) nav(dest);
    else
      window.dispatchEvent(
        new KeyboardEvent("keydown", { key: HOTKEY[dest], bubbles: true })
      );
    onClose();
  };

  const clearAll = () => {
    markAllNotificationsRead().catch(() => {});
    setState((s) => ({ ...s, notifs: [] }));
  };

  const { loading, notifs, error } = state;

  return (
    <div
      style={{
        position: "fixed",
        top: 58,
        right: 18,
        zIndex: 45,
        width: 360,
        maxWidth: "calc(100vw - 36px)",
        background: C.panel,
        border: `1px solid ${C.hair}`,
        borderRadius: 16,
        boxShadow: "0 18px 50px -18px rgba(23,24,26,0.25)",
        padding: 8,
        animation: "vscreenIn 200ms cubic-bezier(0.2,0,0,1) both",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px 8px" }}>
        <p style={{ margin: 0, flex: 1, fontFamily: MONO, fontSize: 10, letterSpacing: "0.14em", color: C.ink45 }}>
          NOTIFICATIONS — STATES, NEVER NAGS
        </p>
        {!loading && notifs.length > 0 && (
          <button
            type="button"
            onClick={clearAll}
            style={{ background: "none", border: "none", cursor: "pointer", fontFamily: MONO, fontSize: 10, color: C.ink45 }}
          >
            MARK ALL READ
          </button>
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close notifications"
          style={{ background: "none", border: "none", cursor: "pointer", fontFamily: MONO, fontSize: 12, color: C.ink40 }}
        >
          ✕
        </button>
      </div>

      <div style={{ maxHeight: "min(70vh, 460px)", overflowY: "auto" }}>
        {loading && (
          <div style={{ padding: "14px 14px 18px" }}>
            <Spinner label="reading your org's states…" />
          </div>
        )}

        {!loading && error && (
          <p style={{ margin: 0, padding: "8px 14px 16px", fontFamily: MONO, fontSize: 11, color: C.fail, lineHeight: 1.6 }}>
            couldn&apos;t read your states — {error}
          </p>
        )}

        {!loading && !error && notifs.length === 0 && (
          <div style={{ padding: "6px 14px 16px" }}>
            <p style={{ margin: 0, fontSize: 13, color: C.ink }}>You&apos;re all caught up.</p>
            <p style={{ margin: "4px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45, lineHeight: 1.6 }}>
              No verifications, governed changes, or hatched bands need your attention. States appear here as your org acts — never nags.
            </p>
          </div>
        )}

        {!loading &&
          notifs.map((n) => (
            <button
              key={n.id}
              type="button"
              onClick={() => go(n)}
              style={{ width: "100%", textAlign: "left", background: "none", border: "none", borderRadius: 10, padding: "10px 14px", cursor: "pointer", fontFamily: "inherit", color: "inherit", transition: "background 120ms" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = C.bg)}
              onMouseLeave={(e) => (e.currentTarget.style.background = "none")}
            >
              <p style={{ margin: 0, fontSize: 13, color: TONE[n.tone], lineHeight: 1.4 }}>{n.title}</p>
              <p style={{ margin: "4px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45, lineHeight: 1.5 }}>{n.meta}</p>
              {n.hatched && (
                <div style={{ marginTop: 8, maxWidth: 240 }}>
                  <ConfidenceBand validated={false} pointFraction={0.5} />
                </div>
              )}
            </button>
          ))}
      </div>

      <div style={{ marginTop: 4, borderTop: `1px solid ${C.hair}`, padding: "10px 14px 6px", display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink40, lineHeight: 1.5, flex: 1 }}>
          Read states stay out of this queue.
        </span>
      </div>
    </div>
  );
}
