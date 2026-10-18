"use client";

/**
 * Pieces shared by the Your shop screens: the page wrapper (scopes shop.css),
 * one toast line, banners, a modal dialog with focus handling, the rate card
 * chip and popover (O9, S1), and the reads behind them.
 */
import * as React from "react";
import Link from "next/link";
import { API_BASE } from "@/lib/api-base";
import { effectiveRateCard, listRateVersions, type EffectiveRateCard, type RateVersionsPage } from "@/lib/verify/rate-api";
import { World, cx } from "../ui";
import { rateCardView, type RateCardView } from "./shop-derive";
import { getRecord, listRecords, type Assumption, type RecordDetail, type RecordSummary } from "./shop-api";
import "./shop.css";

/* ------------------------------------------------------------------ */
/*  World                                                              */
/* ------------------------------------------------------------------ */

export function ShopWorld({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <World label={label}>
      <div className="shp">{children}</div>
    </World>
  );
}

/* ------------------------------------------------------------------ */
/*  Toast                                                              */
/* ------------------------------------------------------------------ */

export function useToast(): [React.ReactNode, (text: string) => void] {
  const [text, setText] = React.useState("");
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const show = React.useCallback((t: string) => {
    setText(t);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setText(""), 4000);
  }, []);
  React.useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );
  const node = (
    <div className="tst" aria-live="polite">
      {text ? (
        <div className="toast" role="status">
          {text}
        </div>
      ) : null}
    </div>
  );
  return [node, show];
}

/* ------------------------------------------------------------------ */
/*  Banner                                                             */
/* ------------------------------------------------------------------ */

export function Banner({
  tone,
  children,
  actions,
  onDismiss,
  alert,
}: {
  tone?: "ok" | "bad" | "warn";
  children: React.ReactNode;
  actions?: React.ReactNode;
  onDismiss?: () => void;
  alert?: boolean;
}) {
  return (
    <div className={cx("banner", tone)} role={alert ? "alert" : "status"}>
      <span style={{ minWidth: 0 }}>{children}</span>
      {actions || onDismiss ? (
        <span className="bx">
          {actions}
          {onDismiss ? (
            <button className="btn sm" type="button" onClick={onDismiss}>
              Dismiss
            </button>
          ) : null}
        </span>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Dialog                                                             */
/* ------------------------------------------------------------------ */

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/**
 * Modal dialog: focus moves in on open and back to the opener on close, Tab
 * stays inside, Esc and the backdrop call `onDismiss` (which may ask first).
 */
export function Dialog({
  title,
  onDismiss,
  onClose,
  children,
  footer,
  initialFocus,
}: {
  title: string;
  /** Esc or backdrop. */
  onDismiss: () => void;
  /** The ✕ button. */
  onClose: () => void;
  children: React.ReactNode;
  footer: React.ReactNode;
  initialFocus?: React.RefObject<HTMLElement | null>;
}) {
  const ref = React.useRef<HTMLDivElement>(null);
  const tid = React.useId();
  React.useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const first = initialFocus?.current ?? ref.current?.querySelector<HTMLElement>(`.db ${FOCUSABLE.split(",").join(",.db ")}`) ?? ref.current?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    return () => {
      if (opener && document.contains(opener)) opener.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onDismiss();
      return;
    }
    if (e.key !== "Tab" || !ref.current) return;
    const items = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };
  return (
    <>
      <button className="scrim" type="button" tabIndex={-1} aria-label="Close dialog" onClick={onDismiss} />
      <div className="dlg" role="dialog" aria-modal="true" aria-labelledby={tid} ref={ref} onKeyDown={onKey}>
        <div className="dh">
          <h2 id={tid}>{title}</h2>
          <button className="xbtn" type="button" aria-label="Close" onClick={onClose}>
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="db">{children}</div>
        <div className="df">{footer}</div>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Rate card in effect                                                */
/* ------------------------------------------------------------------ */

export type RateCardState = {
  eff: EffectiveRateCard | null;
  page: RateVersionsPage | null;
  view: RateCardView | null;
  error: string | null;
  reload: () => void;
};

/** The effective card and the org's authored versions (rate-library). */
export function useRateCard(): RateCardState {
  const [eff, setEff] = React.useState<EffectiveRateCard | null>(null);
  const [page, setPage] = React.useState<RateVersionsPage | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [n, setN] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    setError(null);
    Promise.all([effectiveRateCard(), listRateVersions()]).then(
      ([e, p]) => {
        if (!live) return;
        setEff(e);
        setPage(p);
      },
      (err) => live && setError(err instanceof Error ? err.message : "Couldn't read rates.")
    );
    return () => {
      live = false;
    };
  }, [n]);
  const view = React.useMemo(() => rateCardView(eff, page?.versions ?? null), [eff, page]);
  return { eff, page, view, error, reload: () => setN((x) => x + 1) };
}

/**
 * The rate card chip in the page facts and its popover (O9 and S1). `long` adds
 * the authored count; `action` is the popover's primary action.
 */
export function RateCardChip({
  rc,
  long,
  action,
}: {
  rc: RateCardState;
  long?: boolean;
  action: { label: string; href?: string; onClick?: () => void };
}) {
  const [open, setOpen] = React.useState(false);
  const btn = React.useRef<HTMLButtonElement>(null);
  const pop = React.useRef<HTMLSpanElement>(null);
  const v = rc.view;
  const close = React.useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) btn.current?.focus();
  }, []);
  React.useEffect(() => {
    if (!open) return;
    pop.current?.querySelector<HTMLElement>("a,button")?.focus();
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (pop.current?.contains(t) || btn.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);
  const label = rc.error ? "Rates unavailable" : v ? (long ? v.chipLong : v.chip) : "Reading…";
  const aria = rc.error ? "Rate card: couldn't read rates. Show details" : v ? v.aria : "Rate card: reading. Show details";
  return (
    <span className="rcw">
      <button
        ref={btn}
        className="chipbtn"
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={aria}
        onClick={() => setOpen((o) => !o)}
      >
        <i aria-hidden="true" className={cx(v?.governed && "gov", rc.error && "bad")} />
        {label}
      </button>
      {open ? (
        <span
          className="pop"
          role="dialog"
          aria-label="Rate card in effect"
          ref={pop}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              close(true);
            }
          }}
        >
          {rc.error ? (
            <>
              <b>Couldn&apos;t read rates.</b>
              <span>{rc.error}</span>
              <span className="acts">
                <button className="btn ink sm" type="button" onClick={rc.reload}>
                  Retry
                </button>
                <button className="btn sm" type="button" onClick={() => close(true)}>
                  Close
                </button>
              </span>
            </>
          ) : v ? (
            <>
              <b>{v.title}</b>
              <span>{v.counts}</span>
              <span>
                {v.governed
                  ? `Every verdict and in-house cost uses this card. Saved verdicts keep the version they used.${v.inEffect?.effective_from ? ` In effect since ${new Date(v.inEffect.effective_from).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}.` : ""}`
                  : long
                    ? "New checks and in-house costs use v0 until an admin publishes a reviewed version."
                    : "Every verdict and in-house cost uses this card until a reviewed version is published."}
              </span>
              {!v.flag ? <span>Reviewed rates are off for this organization.</span> : null}
              <span className="acts">
                {action.href ? (
                  <Link className="btn ink sm" href={action.href} onClick={() => setOpen(false)}>
                    {action.label}
                  </Link>
                ) : (
                  <button
                    className="btn ink sm"
                    type="button"
                    onClick={() => {
                      setOpen(false);
                      action.onClick?.();
                    }}
                  >
                    {action.label}
                  </button>
                )}
                <button className="btn sm" type="button" onClick={() => close(true)}>
                  Close
                </button>
              </span>
            </>
          ) : (
            <span>Reading the rate card…</span>
          )}
          <span className="fh">Esc closes</span>
        </span>
      ) : null}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Saved records (cached for the session: a saved record never changes) */
/* ------------------------------------------------------------------ */

const detailCache = new Map<string, Promise<RecordDetail>>();

export function recordDetail(id: string): Promise<RecordDetail> {
  let p = detailCache.get(id);
  if (!p) {
    p = getRecord(id);
    p.catch(() => detailCache.delete(id));
    detailCache.set(id, p);
  }
  return p;
}

export type Loadable<T> = { data: T | null; error: string | null; reload: () => void };

/** Every saved record summary for the org (newest first). */
export function useRecords(): Loadable<RecordSummary[]> {
  const [data, setData] = React.useState<RecordSummary[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [n, setN] = React.useState(0);
  React.useEffect(() => {
    let live = true;
    setError(null);
    listRecords().then(
      (rows) => live && setData(rows),
      (err) => {
        if (!live) return;
        setError(err instanceof Error ? err.message : "Couldn't load records.");
        setData(null);
      }
    );
    return () => {
      live = false;
    };
  }, [n]);
  return { data, error, reload: () => setN((x) => x + 1) };
}

/**
 * Where the shop's labor rate comes from: the governed card in effect, or the
 * default the engine recorded on your newest checks. Null until known; "none"
 * when nothing says (no governed card and no saved check).
 */
export type LaborSource = { value: number; from: "card" | "default"; version?: number | null; record?: string } | "none" | null;

export function useLaborRate(rc: RateCardState, records: RecordSummary[] | null): LaborSource {
  const [out, setOut] = React.useState<LaborSource>(null);
  const governed = rc.eff?.using_governed === true;
  const payload = rc.eff?.payload as { global?: { labor_rate?: unknown } } | null | undefined;
  React.useEffect(() => {
    let live = true;
    if (!rc.eff) return;
    if (governed) {
      const v = payload?.global?.labor_rate;
      setOut(typeof v === "number" ? { value: v, from: "card", version: rc.view?.inEffect?.version ?? null } : "none");
      return;
    }
    if (!records) return;
    const ids = records.slice(0, 4).map((r) => r.id);
    if (!ids.length) {
      setOut("none");
      return;
    }
    (async () => {
      for (const id of ids) {
        try {
          const d = await recordDetail(id);
          const a = (d.result?.assumptions ?? []).find((x: Assumption) => x.name === "labor_rate" && x.provenance === "DEFAULT");
          if (a && typeof a.value === "number") {
            if (live) setOut({ value: a.value, from: "default", record: d.filename });
            return;
          }
        } catch {
          /* try the next record */
        }
      }
      if (live) setOut("none");
    })();
    return () => {
      live = false;
    };
  }, [rc.eff, governed, payload, records, rc.view?.inEffect?.version]);
  return out;
}

/** "Labor $35/h typical" for the page facts. */
export function LaborFact({ src }: { src: LaborSource }) {
  if (src == null) return <span>Labor …</span>;
  if (src === "none")
    return (
      <span title="The default card's labor rate; its value shows after your first check">
        Labor <b>typical</b>
      </span>
    );
  const v = `$${src.value.toLocaleString("en-US", { maximumFractionDigits: 2 })}/h`;
  return (
    <span title={src.from === "default" ? `Default rate, as recorded on ${src.record}` : undefined}>
      Labor <b>{v}</b> {src.from === "card" ? (src.version != null ? `rate card v${src.version}` : "rate card") : "typical"}
    </span>
  );
}


/* ------------------------------------------------------------------ */
/*  The active organization and your role in it                         */
/* ------------------------------------------------------------------ */

export type OrgInfo = { id: string; name: string; role: string } | "none" | null;

export function useOrg(): OrgInfo {
  const [org, setOrg] = React.useState<OrgInfo>(null);
  React.useEffect(() => {
    let live = true;
    fetch(`${API_BASE}/orgs`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((b: { active_org_id?: string; organizations?: { org_id: string; name: string; org_role: string; is_active?: boolean }[] } | null) => {
        if (!live) return;
        const o = b?.organizations?.find((x) => x.org_id === b.active_org_id) ?? b?.organizations?.find((x) => x.is_active) ?? null;
        setOrg(o ? { id: o.org_id, name: o.name, role: o.org_role } : "none");
      })
      .catch(() => live && setOrg("none"));
    return () => {
      live = false;
    };
  }, []);
  return org;
}

export function isOrgAdmin(org: OrgInfo): boolean {
  return !!org && org !== "none" && (org.role === "admin" || org.role === "owner");
}
