"use client";

/**
 * Toasts (board X11): one line confirming something that really happened.
 * Bottom center, 4 s, hover or focus pauses the timer, × closes, and Undo
 * appears when the caller passes a reverse action.
 *
 * `const toasts = useToasts();` then render `{toasts.node}` once inside the page,
 * and call `toasts.show("Removed housing.step from Pump housing", { undo: () => restore() })`.
 * Options: `undo` (shows Undo; called once, then the toast closes), `undoLabel`,
 * `duration` in ms (default 4000; 0 keeps it until closed). At most three show at once; the oldest goes first.
 * Never pass a message for something the server didn't confirm.
 */
import * as React from "react";
import { cx } from "../ui";
import "./moments.css";

export type ToastOptions = { undo?: () => void; undoLabel?: string; duration?: number };
export type ToastItem = { id: number; message: string } & ToastOptions;
type Item = ToastItem;

const CLOSE = (
  <svg width="11" height="11" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="m3 3 8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

let seq = 0;

export function useToasts(): { node: React.ReactNode; show: (message: string, options?: ToastOptions) => void; clear: () => void } {
  const [items, setItems] = React.useState<Item[]>([]);
  const show = React.useCallback((message: string, options: ToastOptions = {}) => {
    seq += 1;
    const item = { id: seq, message, ...options };
    setItems((list) => [...list, item].slice(-3));
  }, []);
  const close = React.useCallback((id: number) => setItems((list) => list.filter((t) => t.id !== id)), []);
  const clear = React.useCallback(() => setItems([]), []);
  const node = <ToastStack items={items} onClose={close} />;
  return { node, show, clear };
}

/** The stack itself, for hosts that keep their own list. `inline` drops the fixed positioning. */
export function ToastStack({ items, onClose, inline }: { items: Item[]; onClose: (id: number) => void; inline?: boolean }) {
  return (
    <div className={cx("mo-tst", inline && "inline")} aria-live="polite">
      {items.map((t) => (
        <Toast key={t.id} item={t} onClose={() => onClose(t.id)} />
      ))}
    </div>
  );
}

function Toast({ item, onClose }: { item: Item; onClose: () => void }) {
  const total = item.duration ?? 4000;
  const left = React.useRef(total);
  const started = React.useRef(0);
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const bar = React.useRef<HTMLSpanElement>(null);
  const holds = React.useRef(0);
  const closeRef = React.useRef(onClose);
  React.useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  const run = React.useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    if (total <= 0) return;
    started.current = Date.now();
    timer.current = setTimeout(() => closeRef.current(), left.current);
    const el = bar.current;
    if (el) {
      el.style.setProperty("--mo-t", `${left.current}ms`);
      el.classList.remove("run");
      el.style.transform = `scaleX(${left.current / total})`;
      void el.offsetWidth;
      el.style.transform = "";
      el.classList.add("run");
    }
  }, [total]);

  const pause = React.useCallback(() => {
    holds.current += 1;
    if (holds.current > 1 || !timer.current) return;
    clearTimeout(timer.current);
    timer.current = null;
    left.current = Math.max(400, left.current - (Date.now() - started.current));
    const el = bar.current;
    if (el) {
      el.classList.remove("run");
      el.style.transform = `scaleX(${left.current / total})`;
    }
  }, [total]);

  const resume = React.useCallback(() => {
    holds.current = Math.max(0, holds.current - 1);
    if (holds.current === 0 && !timer.current) run();
  }, [run]);

  React.useEffect(() => {
    run();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [run]);

  return (
    <div className="toast" role="status" onMouseEnter={pause} onMouseLeave={resume} onFocus={pause} onBlur={resume}>
      <span className="m">{item.message}</span>
      {item.undo ? (
        <button
          className="u"
          type="button"
          onClick={() => {
            item.undo?.();
            onClose();
          }}
        >
          {item.undoLabel ?? "Undo"}
        </button>
      ) : null}
      <button className="tx2" type="button" onClick={onClose} aria-label="Close notice">
        {CLOSE}
      </button>
      {total > 0 ? <span ref={bar} className="tm" aria-hidden="true" /> : null}
    </div>
  );
}
