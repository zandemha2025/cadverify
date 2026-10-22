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

function start() {
  if (started || typeof window === "undefined") return;
  started = true;
  const local = readLocal();
  if (local) current = local;
  void fetch(`${API_BASE}/account/preferences`, { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((p: { length_unit?: string } | null) => {
      const u = p?.length_unit;
      if ((u === "mm" || u === "in") && u !== current) {
        current = u;
        writeLocal(u);
        emit();
      }
    })
    .catch(() => undefined);
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
}

export function useUnits(): { unit: LengthUnit; setUnit: (u: LengthUnit) => Promise<boolean> } {
  const unit = React.useSyncExternalStore(subscribe, () => current, () => "mm" as LengthUnit);
  return { unit, setUnit: setLengthUnit };
}
