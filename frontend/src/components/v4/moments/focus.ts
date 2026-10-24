"use client";

/**
 * Dialog focus handling for the moments: focus moves into the dialog on open,
 * Tab and Shift+Tab stay inside, Esc calls `onEscape`, and focus returns to
 * whatever had it when the dialog closes.
 */
import * as React from "react";

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

export function useFocusTrap(ref: React.RefObject<HTMLElement | null>, onEscape: () => void) {
  React.useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    return () => {
      if (back && document.contains(back)) back.focus();
    };
  }, [ref]);
  return React.useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onEscape();
        return;
      }
      if (e.key !== "Tab" || !ref.current) return;
      const items = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null || el === document.activeElement);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || active === ref.current)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    },
    [ref, onEscape],
  );
}
