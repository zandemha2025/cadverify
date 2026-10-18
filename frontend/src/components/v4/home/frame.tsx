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

export function Column({ children, top, full }: { children: React.ReactNode; top?: 84 | 132 | 220; full?: boolean }) {
  return <div className={cx("content", full && "full", top && `h-c${top}`)}>{children}</div>;
}
