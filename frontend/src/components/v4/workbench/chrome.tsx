"use client";

/**
 * Cost breakdown chrome shared by every tab: the header (the part it belongs to,
 * title, facts, tabs, the rates pill, Check another part), dialogs, the toast, and
 * "choose the file again" for a part opened from its records. This page is the
 * detail behind a part's Cost view; problems and processes live on the part page.
 * A new part comes in one way, through Check a part.
 */
import * as React from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { CostOptions, ShopProfileInfo } from "@/lib/api";
import { parseCalibration } from "@/lib/cost-views";
import { R } from "../routes";
import { CAD_ACCEPT, setPendingFile } from "../pending-file";
import { checkHref } from "../part/check-context";
import { cx } from "../ui";
import { rateChips } from "./derive";
import { attachFile, canRecost, getWb, recost, adoptWhatIf, useShops, useWb } from "./session";
import { shortSource } from "./words";
import { tabOf, tabUrlName, wbHref, type WbTab } from "./cost-url";

/* ---- tabs and links ------------------------------------------------ */

// The address of each tab lives in cost-url.ts (pure, tested): /app/part/{key}/cost?tab=…
export { tabOf, wbHref, type WbTab } from "./cost-url";

export const WB_TABS: { tab: WbTab; label: string }[] = [
  { tab: "decision", label: "Summary" },
  { tab: "glass", label: "Line by line" },
  { tab: "compare", label: "Compare" },
  { tab: "history", label: "History" },
];

export function isTab(v: string | null): boolean {
  return tabOf(v) != null;
}

/** Same-page moves (tab, selection) use the history API so the session stays mounted; others route. */
export function useWbNav(): (href: string, replace?: boolean) => void {
  const router = useRouter();
  return React.useCallback(
    (href: string, replace?: boolean) => {
      const url = new URL(href, window.location.origin);
      if (url.pathname === window.location.pathname) {
        if (replace) window.history.replaceState(null, "", url.pathname + url.search);
        else window.history.pushState(null, "", url.pathname + url.search);
      } else if (replace) router.replace(href);
      else router.push(href);
    },
    [router],
  );
}

export function WbLink({ href, className, children, onNavigate, ...rest }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; onNavigate?: () => void }) {
  const nav = useWbNav();
  return (
    <a
      {...rest}
      href={href}
      className={className}
      onClick={(e) => {
        rest.onClick?.(e);
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        onNavigate?.();
        nav(href);
      }}
    >
      {children}
    </a>
  );
}

/* ---- the tab you used last (per browser) --------------------------- */

const TAB_KEY = "v4.workbench.tab";
let tabMem: WbTab | null = null;

/** The tab a part opens on: the one you used last, else Summary. */
export function lastTab(): WbTab {
  if (tabMem) return tabMem;
  try {
    const v = tabOf(window.localStorage.getItem(TAB_KEY));
    if (v && v !== "routing") tabMem = v;
  } catch {
    /* storage blocked: Summary */
  }
  return tabMem ?? "decision";
}

export function rememberTab(tab: WbTab): void {
  if (tab === "routing") return;
  tabMem = tab;
  try {
    window.localStorage.setItem(TAB_KEY, tabUrlName(tab));
  } catch {
    /* storage blocked: remembered for this tab only */
  }
}

/* ---- portal into the v4 scope -------------------------------------- */

function useObRoot(): HTMLElement | null {
  const [root, setRoot] = React.useState<HTMLElement | null>(null);
  React.useEffect(() => setRoot(document.querySelector<HTMLElement>(".ob[data-ui='v4']")), []);
  return root;
}

export function ObPortal({ children }: { children: React.ReactNode }) {
  const root = useObRoot();
  return root ? createPortal(children, root) : null;
}

/* ---- dialog -------------------------------------------------------- */

export function Dialog({
  role = "dialog",
  labelledBy,
  describedBy,
  onClose,
  scrimLabel = "Close",
  initialFocus,
  children,
}: {
  role?: "dialog" | "alertdialog";
  labelledBy: string;
  describedBy?: string;
  onClose: () => void;
  scrimLabel?: string;
  initialFocus?: React.RefObject<HTMLElement | null>;
  children: React.ReactNode;
}) {
  const box = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    const t = window.setTimeout(() => {
      const el = initialFocus?.current ?? box.current?.querySelector<HTMLElement>("button, [href], input, select, textarea");
      el?.focus();
    }, 0);
    return () => {
      window.clearTimeout(t);
      if (back && document.contains(back)) back.focus();
    };
    // Focus moves in once on open and returns on close.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !box.current) return;
    const items = [...box.current.querySelectorAll<HTMLElement>("button:not([disabled]), [href], input:not([disabled]), select, textarea")];
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };
  return (
    <ObPortal>
      <button className="scrim" type="button" tabIndex={-1} aria-label={scrimLabel} onClick={onClose} />
      <div ref={box} className="dlg" role={role} aria-modal="true" aria-labelledby={labelledBy} aria-describedby={describedBy} onKeyDown={onKeyDown}>
        {children}
      </div>
    </ObPortal>
  );
}

/* ---- toast --------------------------------------------------------- */

const ToastCtx = React.createContext<(text: string) => void>(() => {});
export function useToast() {
  return React.useContext(ToastCtx);
}

function ToastHost({ children }: { children: React.ReactNode }) {
  const [text, setText] = React.useState<{ t: string; n: number } | null>(null);
  const timer = React.useRef<number | null>(null);
  const show = React.useCallback((t: string) => {
    if (timer.current) window.clearTimeout(timer.current);
    setText((p) => ({ t, n: (p?.n ?? 0) + 1 }));
    timer.current = window.setTimeout(() => setText(null), 3600);
  }, []);
  React.useEffect(() => () => {
    if (timer.current) window.clearTimeout(timer.current);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      <ObPortal>
        <div className="tst" aria-live="polite">
          {text ? (
            <div key={text.n} className="toast" role="status">
              {text.t}
            </div>
          ) : null}
        </div>
      </ObPortal>
    </ToastCtx.Provider>
  );
}

/* ---- choose the file again ------------------------------------------ */

type Ask = { reason: string; run: () => void; other: File | null; msg: string | null };
const NeedCtx = React.createContext<{ need: (reason: string, run: () => void) => void; choose: () => void }>({ need: () => {}, choose: () => {} });
export function useNeedFile() {
  return React.useContext(NeedCtx);
}

/* ---- what Check another part carries ------------------------------ */

/** The order quantity the open tab shows (set by the page; Check another part carries it). */
export const WbQtyCtx = React.createContext<number | null>(null);
let shownQty: number | null = null;

/** Check a part, priced in this part's material at the quantity shown here (nothing carried before it's costed). */
function carriedCheckHref(qty: number | null): string {
  const s = getWb();
  return checkHref(s.report ? { material: s.opts.material_class, qty } : {});
}

function NeedFileHost({ children }: { children: React.ReactNode }) {
  const s = useWb();
  const router = useRouter();
  const [ask, setAsk] = React.useState<Ask | null>(null);
  const input = React.useRef<HTMLInputElement>(null);
  // A part opened from its records re-costs on the file its organization kept (no upload, no check).
  const need = React.useCallback((reason: string, run: () => void) => {
    if (getWb().file || canRecost()) run();
    else setAsk({ reason, run, other: null, msg: null });
  }, []);
  const choose = React.useCallback(() => setAsk({ reason: "turn the part and see findings on it", run: () => {}, other: null, msg: null }), []);
  const name = s.filename ?? "the same CAD file";
  return (
    <NeedCtx.Provider value={{ need, choose }}>
      {children}
      {ask ? (
        <Dialog labelledBy="nf-t" describedBy="nf-d" onClose={() => setAsk(null)}>
          <div className="dh">
            <h2 id="nf-t">Choose {name}</h2>
            <button className="btn sm" type="button" aria-label="Close" onClick={() => setAsk(null)}>
              ✕
            </button>
          </div>
          <div className="db">
            <p id="nf-d">
              To {ask.reason}, the cost breakdown needs the CAD file. It isn’t kept in this browser, so choose it again. Saved decisions don’t change.
            </p>
            {ask.msg ? (
              <p role="alert" style={{ color: "var(--bad)" }}>
                {ask.msg}
              </p>
            ) : null}
          </div>
          <div className="df">
            {ask.other ? (
              <button
                className="btn"
                type="button"
                onClick={() => {
                  // A different file is another part: Check a part checks it, priced like this one.
                  if (ask.other) setPendingFile(ask.other);
                  setAsk(null);
                  router.push(carriedCheckHref(shownQty));
                }}
              >
                Check it as another part
              </button>
            ) : null}
            <button className="btn ink" type="button" onClick={() => input.current?.click()}>
              Choose file
            </button>
          </div>
          <input
            ref={input}
            type="file"
            accept={CAD_ACCEPT}
            aria-label={`Choose ${name}`}
            tabIndex={-1}
            style={{ display: "none" }}
            onChange={async (e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (!f) return;
              const r = await attachFile(f);
              if (r === "ok") {
                const run = ask.run;
                setAsk(null);
                run();
              } else if (r === "different") {
                setAsk({ ...ask, other: f, msg: `${f.name} is a different file from ${name}.` });
              } else {
                setAsk({ ...ask, other: null, msg: "That file couldn’t be read here." });
              }
            }}
          />
        </Dialog>
      ) : null}
    </NeedCtx.Provider>
  );
}

export function WbProviders({ children }: { children: React.ReactNode }) {
  return (
    <ToastHost>
      <NeedFileHost>{children}</NeedFileHost>
    </ToastHost>
  );
}

/* ---- popovers ------------------------------------------------------- */

function usePopover() {
  const [open, setOpen] = React.useState(false);
  const wrap = React.useRef<HTMLSpanElement>(null);
  const trigger = React.useRef<HTMLButtonElement>(null);
  React.useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);
  const close = React.useCallback((focus = true) => {
    setOpen(false);
    if (focus) trigger.current?.focus();
  }, []);
  return { open, setOpen, wrap, trigger, close };
}

function RatesPill({ shops }: { shops: ShopProfileInfo[] }) {
  const s = useWb();
  const toast = useToast();
  const { need } = useNeedFile();
  const { open, setOpen, wrap, trigger, close } = usePopover();
  const busy = s.cost.phase === "running";
  const cal = s.report ? parseCalibration(s.report) : null;
  const shopId = s.opts.shop ?? null;
  const shop = shops.find((x) => x.id === shopId) ?? null;
  const name = shop?.name ?? cal?.shopName ?? null;
  const chips = rateChips(s.report?.assumptions ?? [], s.opts.overrides);
  // The org's published rate card this price was figured at (absent: typical rates, v0).
  const card = s.report?.rate_card?.version ?? null;
  const base = card != null ? `Your rates v${card}` : "Typical rates";
  const pick = (id: string | null) => {
    close();
    if (id === shopId && s.report) return;
    const next: CostOptions = { ...s.opts, shop: id };
    need(id ? "re-cost with this shop’s rates" : card != null ? "re-cost on your rates" : "re-cost on typical rates", async () => {
      const r = await recost(next);
      const nm = shops.find((x) => x.id === id)?.name;
      const v = r?.rate_card?.version;
      toast(r ? (id ? `Re-costed with ${nm} rates.` : v != null ? `Shop cleared. Re-costed on your rates v${v}.` : "Shop cleared. Re-costed on typical rates.") : "Re-cost didn’t finish. The last good numbers stay.");
    });
  };
  const label = busy ? "Re-costing…" : name ? `Rates: ${name}` : `Rates: ${card != null ? `yours v${card}` : "typical"}`;
  return (
    <span className="wrap" ref={wrap}>
      <button
        ref={trigger}
        className={cx("btn sm cal", busy ? "busy" : name && "shop")}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <i className="d" aria-hidden="true" />
        {label} <span aria-hidden="true">▾</span>
      </button>
      {open ? (
        <div
          className="pop wide"
          role="dialog"
          aria-label="Rates"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              close();
            }
          }}
        >
          <div className="ph2">
            <span>Use a shop’s rates · re-costs</span>
            <span>{name ?? base}</span>
          </div>
          {[{ id: null as string | null, name: base, sub: card != null ? "No shop · your published rate card" : "No shop · every rate typical" }, ...shops.map((x) => ({ id: x.id as string | null, name: x.name, sub: [x.region, shortSource(x.source)].filter(Boolean).join(" · ") }))].map((r) => (
            <button key={r.id ?? "none"} className="mi" type="button" aria-pressed={r.id === shopId} onClick={() => pick(r.id)} disabled={busy}>
              <span className="ck" aria-hidden="true">
                {r.id === shopId ? "✓" : ""}
              </span>
              <span>
                <b>{r.name}</b>
                <small>{r.sub}</small>
              </span>
            </button>
          ))}
          {chips.card.length ? (
            <>
              <div className="ph2">
                <span>From your rates v{card}</span>
                <span>{chips.card.length}</span>
              </div>
              <div className="rchips shop">
                {chips.card.map((t) => (
                  <span key={t}>{t}</span>
                ))}
              </div>
            </>
          ) : null}
          {chips.bound.length ? (
            <>
              <div className="ph2">
                <span>From this shop</span>
                <span>{chips.bound.length}</span>
              </div>
              <div className="rchips shop">
                {chips.bound.map((t) => (
                  <span key={t}>{t}</span>
                ))}
              </div>
            </>
          ) : null}
          {s.report ? (
            <>
              <div className="ph2">
                <span>Still typical</span>
                <span>{chips.still.length}</span>
              </div>
              <div className="rchips">
                {chips.still.map((t) => (
                  <span key={t}>{t}</span>
                ))}
              </div>
            </>
          ) : null}
          <p>Bundled sample profiles, not your suppliers.</p>
        </div>
      ) : null}
    </span>
  );
}

/** Check another part: the one way in for a new part, carrying this part's material and quantity. */
function CheckAnotherButton() {
  useWb(); // re-render when the part's material changes
  const qty = React.useContext(WbQtyCtx);
  React.useEffect(() => {
    shownQty = qty;
  }, [qty]);
  return (
    <Link className="btn sm" href={carriedCheckHref(qty)} title="Check a part, priced in this part’s material at this quantity">
      Check another part
    </Link>
  );
}

/**
 * "Priced at rates v0; your rates are v1. Re-cost": a price figured at an older
 * rate card than the org's published one says so on every tab (ce-10), and
 * re-costs on the file kept with the record.
 */
function RatesStale() {
  const s = useWb();
  const toast = useToast();
  const { need } = useNeedFile();
  const r = s.decision?.rates ?? null;
  if (!r?.out_of_date) return null;
  const busy = s.cost.phase === "running";
  return (
    <div className="wb-stale" role="note">
      <span>
        <b>{r.text}</b> These prices use the rates in effect when the part was checked.
      </span>
      <button
        className="btn sm ink"
        type="button"
        disabled={busy}
        onClick={() =>
          need(`re-cost at your rates v${r.current}`, async () => {
            const out = await recost({ ...s.opts });
            toast(out ? `Re-costed at your rates v${out.rate_card?.version ?? r.current}.` : "Re-cost didn’t finish. The last good numbers stay.");
          })
        }
      >
        {busy ? "Re-costing…" : `Re-cost at v${r.current}`}
      </button>
    </div>
  );
}

/**
 * A what-if on screen (ad-hoc overrides or a shop's rates) says so, and is the part's price only
 * when the person chooses it (ce-17, ce-08).
 */
function WhatIfNote() {
  const s = useWb();
  const toast = useToast();
  const [busy, setBusy] = React.useState(false);
  const label = s.decision?.whatIf ?? null;
  if (!label) return null;
  return (
    <div className="wb-stale wb-whatif" role="note">
      <span>
        <b>{label}.</b> Saved with the part&apos;s records; the part&apos;s price is still its last check without changes.
      </span>
      <button
        className="btn sm ink"
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await adoptWhatIf();
            toast("This is now the part’s price. The what-if stays in History.");
          } catch (e) {
            toast(e instanceof Error ? e.message : "It wasn’t saved as the part’s price.");
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Saving…" : "Use this as the part’s price"}
      </button>
    </div>
  );
}

export function WbHead({ tab, part, meta, wide }: { tab: WbTab; part: string; meta: React.ReactNode[]; wide?: boolean }) {
  const { shops } = useShops();
  const s = useWb();
  const name = s.key === part ? s.filename : null;
  return (
    <div className={cx("pagehead", wide && "wide")}>
      <h1 className="ptitle">Cost breakdown</h1>
      <p className="pmeta">
        <span>
          <Link href={R.part(part)} title="Back to the part: problems, processes, conditions, your machines and the decision">
            ‹ {name ?? "The part"}
          </Link>
        </span>
        {meta
          .filter(Boolean)
          .filter((m) => !(name && m === name))
          .map((m, i) => (
            <span key={i}>{m}</span>
          ))}
      </p>
      <div className="wbrow">
        <nav className="subnav" aria-label="Cost breakdown">
          {WB_TABS.map((t) => (
            <WbLink key={t.tab} href={wbHref(t.tab, part)} className={cx(t.tab === tab && "on")} aria-current={t.tab === tab ? "page" : undefined}>
              {t.label}
            </WbLink>
          ))}
        </nav>
        <div className="wbt">
          <RatesPill shops={shops} />
          <CheckAnotherButton />
        </div>
      </div>
      <RatesStale />
      <WhatIfNote />
    </div>
  );
}
