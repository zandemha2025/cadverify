"use client";

/**
 * Shared TOAST host for the product shell — the light-instrument "states, never
 * nags" surface. Any screen in the shell can `useToast()` to confirm a REAL
 * action ("decision recorded", "calibration context switched", "machine added").
 * It carries no content of its own: callers pass the message, so a toast can
 * never assert something the engine did not actually do.
 */
import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { C, MONO } from "@/lib/verify/tokens";

type ToastFn = (message: string) => void;

const ToastCtx = createContext<ToastFn | null>(null);

/** `const toast = useToast(); toast("decision recorded — appended to record")`. */
export function useToast(): ToastFn {
  const fn = useContext(ToastCtx);
  // A no-op fallback keeps a screen usable if it is ever rendered outside the
  // provider (e.g. a unit test) rather than throwing.
  return fn ?? (() => {});
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [msg, setMsg] = useState<string>("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const toast = useCallback<ToastFn>((message) => {
    setMsg(message);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setMsg(""), 3600);
  }, []);

  return (
    <ToastCtx.Provider value={toast}>
      {children}
      {msg && (
        <div
          role="status"
          aria-live="polite"
          style={{
            position: "fixed",
            left: "50%",
            bottom: 26,
            transform: "translateX(-50%)",
            zIndex: 90,
            maxWidth: 520,
            background: C.ink,
            color: "#fff",
            borderRadius: 12,
            padding: "11px 18px",
            fontSize: 13,
            fontFamily: MONO,
            boxShadow: "0 18px 50px -18px rgba(23,24,26,0.5)",
            animation: "vtoastIn 240ms cubic-bezier(0.2,0,0,1) both",
          }}
        >
          {msg}
        </div>
      )}
    </ToastCtx.Provider>
  );
}
