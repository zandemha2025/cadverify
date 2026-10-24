"use client";

/**
 * The line shown where a CAD file is picked or dropped: what happens to it, in
 * one sentence, and a link to the facts behind it (Your files and data).
 */
import type { CSSProperties } from "react";
import Link from "next/link";
import { R } from "../routes";
import { cx } from "../ui";
import { UPLOAD_LINE } from "./facts";
import "./trust.css";

export function FileTrustLine({ className, style }: { className?: string; style?: CSSProperties }) {
  return (
    <span className={cx("ftrust", className)} style={style}>
      {UPLOAD_LINE}{" "}
      <Link href={R.data}>Your files and data</Link>
    </span>
  );
}
