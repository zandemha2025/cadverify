"use client";

/**
 * Share: a small dialog, never an instant public link (buyer-12, buyer-13, it-22).
 *
 * It says who can open the link (anyone with it, no sign-in), what they will
 * see, and how long it lasts (7 days unless 1, 30 or 90 days or a date), then
 * Create and copy. A part's link shows specs, quantity and a note; the CAD
 * only when ticked; our cost estimate only when turned on, with a warning. A
 * package's link shows the package as built. The made link stays in the dialog
 * with Copy, Open and the way to Share links. Words: ./words.ts.
 */
import * as React from "react";
import Link from "next/link";
import { R } from "../routes";
import {
  COST_WARNING,
  DEFAULT_LINK_DAYS,
  LINK_DAYS,
  NEVER_SHOWN,
  WHO_OPENS,
  dateBounds,
  endsText,
  linkPayload,
  madeText,
  replacesText,
  seesLines,
  type LinkChoice,
  type LinkPayload,
  type LinkShows,
  type ShareKind,
} from "./words";
import "./share.css";

export interface ShareTarget {
  kind: ShareKind;
  id: string;
  name: string;
}

/** For a part: what the record holds, so the dialog prefills honestly. */
export interface PartFacts {
  quantity: number | null;
  specs: string[];
  cadKept: boolean;
}

/** For a package: what it holds. */
export interface PackageFacts {
  parts: number;
  cadParts: number;
  hasCost: boolean;
}

export interface MadeLink {
  share_url: string | null;
  share_expires_at: string | null;
}

export function ShareDialog({
  target,
  current,
  part: givenPart,
  loadPart,
  pkg,
  create,
  onClose,
  onMade,
}: {
  target: ShareTarget;
  /** The link that is on now, if any. */
  current?: { expiresAt: string | null } | null;
  part?: PartFacts | null;
  /** Reads the part's facts when the dialog opens (its quantity, specs, kept CAD). */
  loadPart?: () => Promise<PartFacts | null>;
  pkg?: PackageFacts | null;
  create: (body: LinkPayload) => Promise<MadeLink>;
  onClose: () => void;
  onMade?: (made: MadeLink) => void;
}) {
  const [choice, setChoice] = React.useState<LinkChoice>({ days: DEFAULT_LINK_DAYS, date: null });
  const [shows, setShows] = React.useState<LinkShows>({ includeCost: false, includeCad: false, note: "", quantity: "" });
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [made, setMade] = React.useState<MadeLink | null>(null);
  const [copied, setCopied] = React.useState<boolean | null>(null);
  const ref = React.useRef<HTMLDivElement>(null);
  const titleId = React.useId();
  const dateId = React.useId();
  const bounds = React.useMemo(() => dateBounds(), []);

  const [loaded, setLoaded] = React.useState<PartFacts | null>(null);
  // While the part's facts are read, Create waits: a link is never made before
  // the dialog knows whether the CAD can go with it.
  const [reading, setReading] = React.useState(!givenPart && !!loadPart);
  const loadOnce = React.useRef(loadPart);
  React.useEffect(() => {
    // Once, when the dialog opens (the caller's function may be a new one each render).
    const load = loadOnce.current;
    if (givenPart || !load) return;
    let live = true;
    load().then(
      (f) => live && (setLoaded(f), setReading(false)),
      () => live && setReading(false),
    );
    return () => {
      live = false;
    };
  }, [givenPart]);
  const part = givenPart ?? loaded;

  // Prefill from the part: its quantity, and the CAD when ScaleCAD holds it; never over what was typed or ticked.
  const prefilled = React.useRef(false);
  const touched = React.useRef({ quantity: false, cad: false });
  React.useEffect(() => {
    if (!part || prefilled.current) return;
    prefilled.current = true;
    setShows((s) => ({
      ...s,
      quantity: !touched.current.quantity && part.quantity != null ? String(part.quantity) : s.quantity,
      includeCad: touched.current.cad ? s.includeCad : part.cadKept,
    }));
  }, [part]);

  React.useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("[data-first]")?.focus();
    return () => back?.focus?.();
  }, []);

  const full = made?.share_url ? (made.share_url.startsWith("/") ? window.location.origin + made.share_url : made.share_url) : null;
  const copy = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  const submit = async () => {
    const p = linkPayload(target.kind, choice, target.kind === "record" ? shows : null);
    if (!p.ok) {
      setErr(p.error);
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const m = await create(p.body);
      setMade(m);
      onMade?.(m);
      if (m.share_url) await copy(m.share_url.startsWith("/") ? window.location.origin + m.share_url : m.share_url);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "The link wasn't made. Nothing was shared.");
    } finally {
      setBusy(false);
    }
  };

  const sees = seesLines({
    kind: target.kind,
    name: target.name,
    shows,
    specs: part?.specs,
    cadKept: part?.cadKept,
    parts: pkg?.parts,
    cadParts: pkg?.cadParts,
    packageHasCost: pkg?.hasCost,
  });

  return (
    <div className="shd-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        className="shd"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            onClose();
          }
          if (e.key === "Tab" && ref.current) {
            const f = [...ref.current.querySelectorAll<HTMLElement>("a[href],button:not([disabled]),input:not([disabled]),textarea,[tabindex]:not([tabindex='-1'])")];
            if (!f.length) return;
            if (e.shiftKey && document.activeElement === f[0]) {
              e.preventDefault();
              f[f.length - 1].focus();
            } else if (!e.shiftKey && document.activeElement === f[f.length - 1]) {
              e.preventDefault();
              f[0].focus();
            }
          }
        }}
      >
        <div className="shd-hd">
          <h2 id={titleId}>{made ? "Link made" : target.kind === "package" ? "Share this package" : "Share this part"}</h2>
          <span className="shd-name">{target.name}</span>
        </div>

        {made ? (
          <div className="shd-body">
            <label className="field">
              Link
              <input type="text" readOnly value={full ?? ""} onFocus={(e) => e.currentTarget.select()} data-first />
            </label>
            <p className="shd-line" role="status">
              {copied === false ? "Copy didn't work. Select the link and copy it." : madeText(made.share_expires_at)}
            </p>
            <div className="shd-acts">
              <button type="button" className="btn sm ink" onClick={() => full && void copy(full)}>
                {copied ? "Copied" : "Copy link"}
              </button>
              {full ? (
                <a className="btn sm" href={full} target="_blank" rel="noopener noreferrer">
                  Open
                </a>
              ) : null}
              <Link className="btn sm ghost" href={R.links}>
                Share links
              </Link>
              <button type="button" className="btn sm" onClick={onClose} style={{ marginLeft: "auto" }}>
                Done
              </button>
            </div>
            <p className="shd-foot">Switch it off any time in Share links. Anyone who opens it then sees that it was switched off.</p>
          </div>
        ) : (
          <div className="shd-body">
            <div className="shd-row">
              <span className="shd-k">Who can open it</span>
              <span>{WHO_OPENS}</span>
            </div>

            <div className="shd-row">
              <span className="shd-k">How long</span>
              <div className="shd-days">
                <span className="seg" role="group" aria-label="How long the link works">
                  {LINK_DAYS.map((c, i) => (
                    <button key={c.value} type="button" className={choice.days === c.value ? "on" : undefined} aria-pressed={choice.days === c.value} onClick={() => setChoice({ days: c.value, date: null })} data-first={i === 1 ? true : undefined}>
                      {c.label}
                    </button>
                  ))}
                  <button type="button" className={choice.days == null ? "on" : undefined} aria-pressed={choice.days == null} onClick={() => setChoice((c) => ({ days: null, date: c.date ?? bounds.min }))}>
                    A date
                  </button>
                </span>
                {choice.days == null ? (
                  <span className="shd-date">
                    <label htmlFor={dateId} className="sr">
                      The day the link stops working
                    </label>
                    <input id={dateId} type="date" min={bounds.min} max={bounds.max} value={choice.date ?? ""} onChange={(e) => setChoice({ days: null, date: e.target.value })} />
                  </span>
                ) : null}
                <small>{endsText(choice)}</small>
              </div>
            </div>

            {target.kind === "record" ? (
              <>
                <div className="shd-two">
                  <label className="field">
                    Quantity
                    <input type="text" inputMode="numeric" placeholder={reading ? "Reading…" : "Not given"} value={shows.quantity} onChange={(e) => ((touched.current.quantity = true), setShows({ ...shows, quantity: e.target.value }))} />
                  </label>
                  <label className="field">
                    Note to the supplier
                    <textarea maxLength={2000} placeholder="Reply-by date, tolerances, your contact" value={shows.note} onChange={(e) => setShows({ ...shows, note: e.target.value })} />
                  </label>
                </div>
                <label className={`shd-chk${part && !part.cadKept ? " off" : ""}`}>
                  <input type="checkbox" checked={shows.includeCad} disabled={reading || (!!part && !part.cadKept)} onChange={(e) => ((touched.current.cad = true), setShows({ ...shows, includeCad: e.target.checked }))} />
                  <span>
                    Include the CAD file
                    <small>{reading ? "Looking for the file ScaleCAD kept…" : part && !part.cadKept ? "ScaleCAD has no copy of this file." : "They can download the file you checked."}</small>
                  </span>
                </label>
                <label className="shd-chk">
                  <input type="checkbox" checked={shows.includeCost} onChange={(e) => setShows({ ...shows, includeCost: e.target.checked })} />
                  <span>
                    Include our cost estimate (the supplier will see it)
                    <small>Off unless you turn it on.</small>
                  </span>
                </label>
                {shows.includeCost ? (
                  <p className="shd-warn" role="note">
                    {COST_WARNING}
                  </p>
                ) : null}
              </>
            ) : null}

            <div className="shd-sees">
              <span className="shd-k">What they will see</span>
              <ul>
                {sees.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
              <small>{NEVER_SHOWN}</small>
            </div>

            {current ? <p className="shd-line">{replacesText(current.expiresAt)}</p> : null}
            {err ? (
              <p className="shd-err" role="alert">
                {err}
              </p>
            ) : null}
            <div className="shd-acts">
              <button type="button" className="btn sm ink" onClick={() => void submit()} disabled={busy || reading}>
                {busy ? "Making the link…" : reading ? "Reading the part…" : "Create and copy"}
              </button>
              <button type="button" className="btn sm" onClick={onClose}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
