"use client";

/**
 * v4 building blocks. Thin wrappers over the classes in v4.css so every screen
 * reads the same: a product header (title and facts, never a pitch), sibling
 * tabs, panels, list rows, key/value lists, and the empty/loading/error states.
 */
import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { headEnd } from "./page-head";

type Tone = "ok" | "warn" | "bad" | "unk";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/** A labelled key figure. Text values (not starting with a digit or $) get the smaller text style. */
export function Fig({ k, v, sub, tone }: { k: string; v: string; sub?: string; tone?: "ok" | "warn" | "bad" }) {
  const isText = !/^[$\d−-]/.test(v);
  return (
    <div className="fig">
      <span>{k}</span>
      <b className={cx("num", tone, isText && "t")}>{v}</b>
      {sub ? <small>{sub}</small> : null}
    </div>
  );
}

export function Figs({ children }: { children: React.ReactNode }) {
  return (
    <div className="figs" aria-live="polite">
      {children}
    </div>
  );
}

/** Sibling tabs. The tab whose href matches the path (or is its longest prefix) is current. */
export function SubNav({
  tabs,
  label,
  current: currentHref,
}: {
  tabs: { label: string; href: string; count?: number }[];
  label: string;
  /** Force the current tab (by href), or `null` for none, when the path alone can't tell. */
  current?: string | null;
}) {
  const pathname = usePathname() ?? "";
  const current =
    currentHref !== undefined
      ? tabs.find((t) => t.href === currentHref)
      : tabs
          .filter((t) => pathname === t.href || pathname.startsWith(t.href + "/"))
          .sort((a, b) => b.href.length - a.href.length)[0];
  return (
    <nav className="subnav" aria-label={label}>
      {tabs.map((t) => (
        <Link key={t.href} href={t.href} className={cx(t === current && "on")} aria-current={t === current ? "page" : undefined}>
          {t.label}
          {t.count != null ? <b className="num">{t.count}</b> : null}
        </Link>
      ))}
    </nav>
  );
}

/** Page header: title, facts, optional key figures, optional tabs. `wide` spans the full width (no right sheet). */
export function PageHead({
  title,
  meta,
  figs,
  tabs,
  tabsLabel = "Section",
  tabsCurrent,
  tabsAside,
  actions,
  wide,
}: {
  title: React.ReactNode;
  meta?: React.ReactNode[];
  figs?: React.ReactNode;
  tabs?: { label: string; href: string; count?: number }[];
  tabsLabel?: string;
  /** See SubNav `current`. */
  tabsCurrent?: string | null;
  /** Tools that sit on the tab row (filters, a view switch). */
  tabsAside?: React.ReactNode;
  actions?: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={cx("pagehead", wide && "wide")}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <h1 className="ptitle">{title}</h1>
          {meta && meta.length ? (
            <p className="pmeta" style={{ marginTop: 6 }}>
              {meta.map((m, i) => (
                <span key={i}>{m}</span>
              ))}
            </p>
          ) : null}
        </div>
        {actions ? <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>{actions}</div> : null}
      </div>
      {figs}
      {tabs || tabsAside ? (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
          {tabs ? <SubNav tabs={tabs} label={tabsLabel} current={tabsCurrent} /> : <span />}
          {tabsAside}
        </div>
      ) : null}
    </div>
  );
}

/** The scrolling area under a PageHead. `full` spans the width; otherwise a right sheet owns the last 500px. */
/**
 * Keeps a page's content under its page head as the head is drawn (desktop):
 * the content sits at a fixed offset, and a head that wraps would run over its
 * first line. Measures the page head of the same page (World, the Account
 * frame and every area's wrapper alike) and sets `--head-end` on the content;
 * v4.css applies it on desktop only (phones flow the head and the content).
 */
function useUnderHead(ref: React.RefObject<HTMLDivElement | null>) {
  const watched = React.useRef<{ head: HTMLElement; ro: ResizeObserver } | null>(null);
  React.useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const head = el.closest(".world")?.querySelector<HTMLElement>(".pagehead") ?? null;
    if (watched.current?.head === head) return;
    watched.current?.ro.disconnect();
    watched.current = null;
    if (!head) {
      el.style.removeProperty("--head-end");
      return;
    }
    const place = () => el.style.setProperty("--head-end", `${headEnd(head.offsetTop, head.offsetHeight)}px`);
    const ro = new ResizeObserver(place);
    ro.observe(head);
    place();
    watched.current = { head, ro };
  });
  React.useEffect(
    () => () => {
      watched.current?.ro.disconnect();
      watched.current = null;
    },
    [],
  );
}

export function Content({ children, full, top }: { children: React.ReactNode; full?: boolean; top?: number }) {
  const ref = React.useRef<HTMLDivElement>(null);
  useUnderHead(ref);
  return (
    <div ref={ref} className={cx("content", full && "full")} data-under-head="" style={top != null ? ({ "--content-top": `${top}px` } as React.CSSProperties) : undefined}>
      {children}
    </div>
  );
}

/** The world: the stage background every v4 page sits on. */
export function World({ children, label }: { children: React.ReactNode; label?: string }) {
  return (
    <main className="world page" aria-label={label}>
      <div className="stage" aria-hidden="true" />
      {children}
    </main>
  );
}

export function Panel({
  title,
  note,
  children,
  actions,
  id,
}: {
  title?: React.ReactNode;
  note?: React.ReactNode;
  children: React.ReactNode;
  actions?: React.ReactNode;
  id?: string;
}) {
  const hid = React.useId();
  return (
    <section className="panel" aria-labelledby={title ? hid : undefined} id={id}>
      {title || note || actions ? (
        <div className="ph">
          {title ? <h2 id={hid}>{title}</h2> : <span />}
          <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {note ? <span>{note}</span> : null}
            {actions}
          </span>
        </div>
      ) : null}
      {children}
    </section>
  );
}

/** Right-hand floating sheet (the `.sheet` of the boards). */
export function Sheet({ children, label, style }: { children: React.ReactNode; label: string; style?: React.CSSProperties }) {
  return (
    <aside className="sheet" aria-label={label} style={style}>
      {children}
    </aside>
  );
}

export function Chip({ tone = "unk", children, title }: { tone?: Tone; children: React.ReactNode; title?: string }) {
  return (
    <span className={cx("chip", `c-${tone}`)} title={title}>
      <i aria-hidden="true" />
      {children}
    </span>
  );
}

/** Where a number came from: the file, your shop, or a typical default. */
export function Src({ kind, children, title }: { kind: "file" | "yours" | "typ"; children: React.ReactNode; title?: string }) {
  return (
    <span className={cx("src", `s-${kind}`)} title={title}>
      {children}
    </span>
  );
}

export function KV({ rows }: { rows: [React.ReactNode, React.ReactNode][] }) {
  return (
    <div className="kv">
      {rows.map(([k, v], i) => (
        <React.Fragment key={i}>
          <span>{k}</span>
          <b className="num">{v}</b>
        </React.Fragment>
      ))}
    </div>
  );
}

/** A list row: optional thumbnail, title, detail, trailing chip and value. Renders a Link when `href` is set. */
export function Row({
  href,
  onClick,
  thumb,
  title,
  sub,
  chip,
  value,
  on,
  label,
}: {
  href?: string;
  onClick?: () => void;
  thumb?: React.ReactNode;
  title: React.ReactNode;
  sub?: React.ReactNode;
  chip?: React.ReactNode;
  value?: React.ReactNode;
  on?: boolean;
  label?: string;
}) {
  const body = (
    <>
      {thumb ?? <span className="th" aria-hidden="true" />}
      <span style={{ minWidth: 0 }}>
        <b>{title}</b>
        {sub ? <small>{sub}</small> : null}
      </span>
      <span>{chip}</span>
      <span className="c num">{value}</span>
    </>
  );
  if (href)
    return (
      <Link className={cx("lrow", on && "on")} href={href} aria-label={label}>
        {body}
      </Link>
    );
  return (
    <button type="button" className={cx("lrow", on && "on")} onClick={onClick} aria-label={label} aria-pressed={on}>
      {body}
    </button>
  );
}

export function List({ children, label }: { children: React.ReactNode; label?: string }) {
  return (
    <div className="list" role="list" aria-label={label}>
      {React.Children.map(children, (c) => (c == null || c === false ? null : <div role="listitem">{c}</div>))}
    </div>
  );
}

export function Empty({ title, children, actions }: { title: string; children?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="empty">
      <b>{title}</b>
      {children ? <span>{children}</span> : null}
      {actions ? <span style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap", justifyContent: "center" }}>{actions}</span> : null}
    </div>
  );
}

/** Loading placeholder rows; announced once, not per row. */
export function Loading({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div className="list" role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="lrow" aria-hidden="true" style={{ cursor: "default" }}>
          <span className="th" />
          <span style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={{ height: 10, width: "46%", borderRadius: 6, background: "rgba(20,24,31,.08)" }} />
            <span style={{ height: 8, width: "70%", borderRadius: 6, background: "rgba(20,24,31,.05)" }} />
          </span>
          <span />
          <span />
        </div>
      ))}
    </div>
  );
}

/** A failed load. `onRetry` re-runs the load; `detail` is the server's message when it has one. */
export function Failed({ title, detail, onRetry, extra }: { title: string; detail?: string | null; onRetry?: () => void; extra?: React.ReactNode }) {
  return (
    <div className="note" role="alert" style={{ background: "var(--warn-bg)", borderColor: "transparent" }}>
      <b>{title}</b>
      {detail ? <span>{detail}</span> : null}
      <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {onRetry ? (
          <button className="btn sm ink" type="button" onClick={onRetry}>
            Retry
          </button>
        ) : null}
        {extra}
      </span>
    </div>
  );
}

/** Inline confirm for destructive actions: the action button turns into a question with Confirm / Cancel. */
export function ConfirmButton({
  label,
  question,
  confirmLabel,
  onConfirm,
  className = "btn sm",
  disabled,
  onAsking,
}: {
  label: string;
  question: string;
  confirmLabel?: string;
  onConfirm: () => void | Promise<void>;
  className?: string;
  disabled?: boolean;
  /** Told when the question shows or goes, so a host can hide its own Cancel (one Cancel at a time). */
  onAsking?: (asking: boolean) => void;
}) {
  const [asking, setAskingState] = React.useState(false);
  const setAsking = (v: boolean) => {
    setAskingState(v);
    onAsking?.(v);
  };
  const [busy, setBusy] = React.useState(false);
  if (!asking)
    return (
      <button className={className} type="button" onClick={() => setAsking(true)} disabled={disabled}>
        {label}
      </button>
    );
  return (
    <span role="alertdialog" aria-label={label} style={{ display: "inline-flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
      <span style={{ color: "var(--ink2)", fontSize: 13 }}>{question}</span>
      <button
        className="btn sm ink"
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onConfirm();
          } finally {
            setBusy(false);
            setAsking(false);
          }
        }}
      >
        {busy ? "Working…" : confirmLabel ?? label}
      </button>
      <button className="btn sm" type="button" onClick={() => setAsking(false)} disabled={busy}>
        Cancel
      </button>
    </span>
  );
}

/** Formats a dollar figure the way every v4 screen does. */
export function usd(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function count(n: number, one: string, many?: string): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many ?? one + "s"}`;
}
