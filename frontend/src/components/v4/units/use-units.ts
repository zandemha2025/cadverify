"use client";

/**
 * The person's length unit, remembered on their account
 * (`/api/v1/account/preferences`) and mirrored in this browser so the first
 * paint already uses it. One shared store: every view that calls `useUnits()`
 * changes together when the choice changes.
 */
import * as React from "react";
import { API_BASE } from "@/lib/api-base";
import type { LengthUnit } from "./units";

const KEY = "scalecad.lengthUnit";
let current: LengthUnit = "mm";
let started = false;
let listening = false;
const listeners = new Set<() => void>();

function readLocal(): LengthUnit | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "in" || v === "mm" ? v : null;
  } catch {
    return null;
  }
}

function writeLocal(u: LengthUnit) {
  try {
    window.localStorage.setItem(KEY, u);
  } catch {
    /* private window: the account still remembers it */
  }
}

function emit() {
  for (const l of listeners) l();
}

/** The account's unit, read again: on first use, whenever the tab comes back into view, and after a failed read. */
function refresh() {
  void fetch(`${API_BASE}/account/preferences`, { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((p: { length_unit?: string } | null) => {
      const u = p?.length_unit;
      if (u !== "mm" && u !== "in") {
        // Not read (signed out, offline, a server error): try again on the next view that asks (me-15).
        started = false;
        return;
      }
      if (u !== current) {
        current = u;
        writeLocal(u);
        emit();
      }
    })
    .catch(() => {
      started = false;
    });
}

function start() {
  if (typeof window === "undefined") return;
  if (!listening) {
    listening = true;
    const local = readLocal();
    if (local) current = local;
    // The unit is the person's, on every device: a choice made on the desk shows on the phone when it comes back to it.
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") refresh();
    });
  }
  if (started) return;
  started = true;
  refresh();
}

/**
 * Read the account's unit as soon as the app opens, before a page's heavier
 * requests take the browser's connections (me-15: the part page drew in mm
 * while the read waited behind them).
 */
export function primeLengthUnit(): void {
  start();
}

function subscribe(cb: () => void) {
  start();
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** Save the choice on the account; the view switches at once. */
export async function setLengthUnit(u: LengthUnit): Promise<boolean> {
  current = u;
  writeLocal(u);
  emit();
  const put = async () => {
    try {
      const r = await fetch(`${API_BASE}/account/preferences`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ length_unit: u }),
      });
      return r.ok;
    } catch {
      return false;
    }
  };
  if (await put()) return true;
  // Once more after a moment, so a dropped request on shop wifi doesn't leave the other devices on the old unit.
  await new Promise((r) => setTimeout(r, 2000));
  return current === u ? put() : false;
}

export function useUnits(): { unit: LengthUnit; setUnit: (u: LengthUnit) => Promise<boolean> } {
  const unit = React.useSyncExternalStore(subscribe, () => current, () => "mm" as LengthUnit);
  return { unit, setUnit: setLengthUnit };
}
