"use client";

/**
 * Keyboard-shortcuts overlay (the `?` surface). Static, honest reference for the
 * shell's REAL bindings — every row here is wired in the shell's keydown handler
 * (⌘K palette, H/V/P/R/G/M/T/C nav, ? this sheet, Esc closes everything). No
 * shortcut is listed that the shell does not actually implement.
 */
import { C, MONO } from "@/lib/verify/tokens";

const GROUPS: { title: string; rows: { keys: string; label: string }[] }[] = [
  {
    title: "GLOBAL",
    rows: [
      { keys: "⌘ K", label: "Command palette — jump anywhere" },
      { keys: "?", label: "This shortcuts sheet" },
      { keys: "Esc", label: "Close palette / overlays / menus" },
    ],
  },
  {
    title: "NAVIGATE",
    rows: [
      { keys: "H", label: "Home desk" },
      { keys: "V", label: "Verify" },
      { keys: "P", label: "Parts catalog" },
      { keys: "R", label: "Records" },
      { keys: "G", label: "Programs" },
      { keys: "M", label: "Your machines" },
      { keys: "T", label: "Triage" },
      { keys: "C", label: "Calibration & truth" },
    ],
  },
];

export function ShortcutsOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 80,
        background: "rgba(23,24,26,0.35)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 560,
          maxWidth: "100%",
          background: C.panel,
          border: `1px solid ${C.hair}`,
          borderRadius: 18,
          boxShadow: "0 18px 50px -18px rgba(23,24,26,0.35)",
          padding: "22px 24px",
          animation: "vscreenIn 220ms cubic-bezier(0.2,0,0,1) both",
        }}
      >
        <div style={{ display: "flex", alignItems: "center" }}>
          <p
            style={{
              margin: 0,
              fontFamily: MONO,
              fontSize: 10,
              letterSpacing: "0.16em",
              color: C.ink45,
            }}
          >
            KEYBOARD SHORTCUTS
          </p>
          <button
            type="button"
            onClick={onClose}
            style={{
              marginLeft: "auto",
              background: "none",
              border: "none",
              cursor: "pointer",
              fontFamily: MONO,
              fontSize: 13,
              color: C.ink40,
            }}
          >
            ✕
          </button>
        </div>
        <div
          style={{
            marginTop: 16,
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: "22px 32px",
          }}
        >
          {GROUPS.map((g) => (
            <div key={g.title}>
              <p
                style={{
                  margin: "0 0 8px",
                  fontFamily: MONO,
                  fontSize: 9.5,
                  letterSpacing: "0.14em",
                  color: C.ink40,
                }}
              >
                {g.title}
              </p>
              {g.rows.map((r) => (
                <div
                  key={r.keys}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "6px 0",
                  }}
                >
                  <kbd
                    style={{
                      fontFamily: MONO,
                      fontSize: 11,
                      minWidth: 34,
                      textAlign: "center",
                      border: `1px solid ${C.hair}`,
                      borderRadius: 6,
                      padding: "3px 7px",
                      color: C.ink,
                      background: C.sunken,
                    }}
                  >
                    {r.keys}
                  </kbd>
                  <span style={{ fontSize: 13, color: C.ink60 }}>{r.label}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
