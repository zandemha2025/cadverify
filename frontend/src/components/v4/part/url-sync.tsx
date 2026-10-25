"use client";

/** Keeps the part's open view in its URL (see url-state.ts). Rendered inside the part's providers. */
import * as React from "react";
import { usePart } from "./ctx";
import { partSearch } from "./url-state";

export function PartUrlSync() {
  const p = usePart();
  const qs = p.qs.join(",");
  React.useEffect(() => {
    try {
      const next = partSearch(window.location.search, { lens: p.lens, q: p.q, qs: qs ? qs.split(",").map(Number) : [] });
      if (next === window.location.search) return;
      window.history.replaceState(window.history.state, "", `${window.location.pathname}${next}${window.location.hash}`);
    } catch {
      /* the view still works without it */
    }
  }, [p.lens, p.q, qs]);
  return null;
}
