"use client";

/**
 * Page frame for the screens in this area: the v4 world (stage backdrop) with a
 * phone fix, and the scrolling content column with its board offset as a class.
 * Same markup as `World`/`Content` in ../ui.tsx; see the report for why.
 */
import * as React from "react";
import { cx } from "../ui";
import "./home.css";

export function Frame({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <main className="world h-page" aria-label={label}>
      <div className="stage" aria-hidden="true" />
      {children}
    </main>
  );
}

/**
 * The scrolling column under a page head. Its desktop offset follows the head's
 * real height (facts can wrap), passed as a CSS variable so phones, where the
 * column is a normal block, ignore it.
 */
export function Column({ children, full, head }: { children: React.ReactNode; full?: boolean; head: React.RefObject<HTMLElement | null> }) {
  const [top, setTop] = React.useState<number | null>(null);
  React.useLayoutEffect(() => {
    const el = head.current;
    if (!el) return;
    const measure = () => setTop(el.offsetTop + el.offsetHeight + 14);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [head]);
  return (
    <div className={cx("content h-ctop", full && "full")} style={top != null ? ({ "--h-top": `${top}px` } as React.CSSProperties) : undefined}>
      {children}
    </div>
  );
}

/** The page head block (title, facts, tabs, controls) whose height the column follows. */
export const Head = React.forwardRef<HTMLDivElement, { children: React.ReactNode }>(function Head({ children }, ref) {
  return (
    <div className="pagehead" ref={ref}>
      {children}
    </div>
  );
});
