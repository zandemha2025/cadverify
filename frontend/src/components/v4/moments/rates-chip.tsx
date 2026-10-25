"use client";

/**
 * Rates chip (board X11): the top-bar chip naming the rate card every cost is
 * figured against, and its "Rates in use" popover. It reads the real rate
 * library (effective card + your authored versions) and claims nothing when
 * the read fails ("Rates unavailable").
 *
 * `<RatesChip />` takes no required props. Optional `style` for placement in a bar.
 * Click opens the popover; Esc or a click outside closes it and returns focus.
 * Meant for the shell's top bar (next to search) on every v4 screen.
 */
import * as React from "react";
import Link from "next/link";
import { effectiveRateCard, listRateVersions, type EffectiveRateCard, type RateVersionsPage } from "@/lib/verify/rate-api";
import { R } from "../routes";
import { cx } from "../ui";
import "./moments.css";

export type RatesState =
  | { kind: "loading" }
  | { kind: "failed" }
  | { kind: "ready"; governed: boolean; version: number | null; authored: number; published: number };

/** Pure: the chip's state from the two reads. */
export function ratesState(eff: EffectiveRateCard | null, page: RateVersionsPage | null, failed: boolean): RatesState {
  if (failed) return { kind: "failed" };
  if (!eff || !page) return { kind: "loading" };
  const published = page.versions.filter((v) => v.status === "published" || v.is_published);
  const nums = published.map((v) => (typeof v.version === "number" ? v.version : null)).filter((n): n is number => n != null);
  return {
    kind: "ready",
    governed: eff.using_governed,
    version: eff.using_governed && nums.length ? Math.max(...nums) : null,
    authored: page.versions.length,
    published: published.length,
  };
}

export function ratesLabel(s: RatesState): string {
  if (s.kind === "failed") return "Rates unavailable";
  if (s.kind === "loading") return "Rates…";
  if (s.governed) return s.version != null ? `Your rates · v${s.version}` : "Your rates";
  return "Typical rates";
}

export function RatesChip({ style }: { style?: React.CSSProperties }) {
  const [eff, setEff] = React.useState<EffectiveRateCard | null>(null);
  const [page, setPage] = React.useState<RateVersionsPage | null>(null);
  const [failed, setFailed] = React.useState(false);
  const [open, setOpen] = React.useState(false);
  const wrap = React.useRef<HTMLSpanElement>(null);
  const chip = React.useRef<HTMLButtonElement>(null);
  const first = React.useRef<HTMLAnchorElement>(null);
  const pid = React.useId();

  React.useEffect(() => {
    let live = true;
    Promise.all([effectiveRateCard(), listRateVersions()]).then(
      ([e, p]) => {
        if (!live) return;
        setEff(e);
        setPage(p);
      },
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, []);

  React.useEffect(() => {
    if (!open) return;
    first.current?.focus();
    const onDown = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  const s = ratesState(eff, page, failed);
  const label = ratesLabel(s);
  const close = () => {
    setOpen(false);
    chip.current?.focus();
  };
  return (
    <span className="mo-rates" ref={wrap} style={style}>
      <button
        ref={chip}
        className={cx("ratechip", s.kind === "ready" && s.governed && "yours", s.kind !== "ready" && "unk")}
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={open ? pid : undefined}
        aria-label={`Rates in use: ${label}. Open rate details`}
        onClick={() => setOpen((o) => !o)}
      >
        <i aria-hidden="true" />
        {label}
      </button>
      {open ? (
        <div
          id={pid}
          className="pop swap"
          role="dialog"
          aria-label="Rates in use"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              e.stopPropagation();
              close();
            }
          }}
        >
          <div className="mo-popc">
            <b>Rates in use</b>
            {s.kind === "ready" ? (
              <div className="kv">
                <span>Rate card</span>
                <b>{s.governed ? (s.version != null ? `Yours (v${s.version})` : "Yours") : "Default (v0)"}</b>
                <span>Your versions</span>
                <b className="num">
                  {s.authored} · {s.published} published
                </b>
              </div>
            ) : null}
            <p>
              {s.kind === "failed"
                ? "Couldn’t read the rate library. No rate card is claimed until it loads."
                : s.kind === "loading"
                  ? "Reading the rate library…"
                  : s.governed
                    ? "Your published rates cost every check. Old records keep their rates."
                    : "Typical rates until you publish yours. Old records keep their rates."}
            </p>
            <span>
              <Link ref={first} className="btn sm" href={R.rates} onClick={() => setOpen(false)}>
                Open rates
              </Link>
            </span>
          </div>
        </div>
      ) : null}
    </span>
  );
}
