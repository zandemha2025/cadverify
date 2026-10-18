"use client";

/**
 * Get started (board X9): the overlay on Home, opened by `?welcome=1`, by
 * "Start here", and once for a new organization. Options: check a CAD file,
 * run the sample (it runs the real engine, so it uses a check), make a simple
 * part, set up your shop. When no checks are left the sample isn't run and
 * "Sample not run" says why.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { R } from "../routes";
import { CAD_ACCEPT, setPendingFile } from "../pending-file";
import { useShell } from "../shell";
import { cx } from "../ui";
import "./home.css";

/** Same key today's guide uses, so a person who closed it there isn't shown it again. */
export const WELCOME_SEEN = "proofshape_welcome_v2";

export function rememberWelcomeSeen(): void {
  try {
    localStorage.setItem(WELCOME_SEEN, "1");
  } catch {
    /* storage off (private window): the guide still closes for this visit */
  }
}

export function welcomeSeen(): boolean {
  try {
    return localStorage.getItem(WELCOME_SEEN) === "1";
  } catch {
    return false;
  }
}

type Usage = ReturnType<typeof useShell>["usage"];

export function outOfChecks(u: Usage): boolean {
  return Boolean(u && !u.unlimited && u.remaining <= 0);
}

/** The allowance facts for the dialog header: "15 free checks left · Each part uses 1". */
function allowance(u: Usage): React.ReactNode[] {
  if (!u) return [<span key="e">Each part uses 1 check</span>];
  if (u.unlimited) return [<span key="p">Pilot plan</span>, <span key="n">Checks aren&apos;t capped</span>];
  if (u.plan === "pro")
    return [
      <span key="l">
        <b>{u.remaining}</b> of {u.cap} Pro checks left this month
      </span>,
      <span key="e">Each part uses 1</span>,
    ];
  return [
    <span key="l">
      <b>{u.remaining}</b> free {u.remaining === 1 ? "check" : "checks"} left
    </span>,
    <span key="e">Each part uses 1</span>,
  ];
}

/** Modal frame: scrim, focus moves in and back, Esc and the scrim close, Tab stays inside. */
export function Modal({ labelledBy, onClose, children, small }: { labelledBy: string; onClose: () => void; children: React.ReactNode; small?: boolean }) {
  const ref = React.useRef<HTMLElement>(null);
  const back = React.useRef<HTMLElement | null>(null);
  React.useEffect(() => {
    back.current = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const first = el?.querySelector<HTMLElement>("[data-autofocus]") ?? el?.querySelector<HTMLElement>("button, a, input");
    first?.focus();
    return () => {
      const to = back.current;
      if (to && document.contains(to)) to.focus();
    };
  }, []);
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !ref.current) return;
    const items = Array.from(ref.current.querySelectorAll<HTMLElement>("a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex='-1'])")).filter((n) => n.offsetParent !== null || n.tagName === "INPUT");
    if (!items.length) return;
    const i = items.indexOf(document.activeElement as HTMLElement);
    if (e.shiftKey && i <= 0) {
      e.preventDefault();
      items[items.length - 1].focus();
    } else if (!e.shiftKey && i === items.length - 1) {
      e.preventDefault();
      items[0].focus();
    }
  };
  return (
    <div className="h-over">
      <button className="h-scrim" type="button" tabIndex={-1} aria-hidden="true" onClick={onClose} />
      <section ref={ref} className={cx("h-dlg", small && "sm")} role="dialog" aria-modal="true" aria-labelledby={labelledBy} onKeyDown={onKey}>
        {children}
      </section>
    </div>
  );
}

function CloseX({ onClose, label = "Close" }: { onClose: () => void; label?: string }) {
  return (
    <button className="btn h-x" type="button" onClick={onClose} aria-label={label}>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
        <path d="m3 3 8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
    </button>
  );
}

export function GetStarted({ onClose, onSample }: { onClose: () => void; onSample: () => void }) {
  const router = useRouter();
  const { usage } = useShell();
  return (
    <Modal labelledBy="gs-title" onClose={onClose}>
      <div className="h-hd">
        <div>
          <h1 className="ptitle" id="gs-title">
            Get started
          </h1>
          <p className="pmeta" style={{ marginTop: 6 }}>
            {allowance(usage)}
          </p>
        </div>
        <CloseX onClose={onClose} />
      </div>
      <div className="h-opts">
        <label className="h-opt main">
          <input
            type="file"
            accept={CAD_ACCEPT}
            data-autofocus
            aria-label="Check a CAD file: STEP, STL or IGES, up to 200 MB"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (!f) return;
              rememberWelcomeSeen();
              setPendingFile(f);
              router.push(R.check);
            }}
          />
          <span className="h-ico">
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="M10 13V3m0 0L6 7m4-4 4 4M4 13v4h12v-4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span>
            <b>Check a CAD file</b>
            <small>STEP, STL or IGES · up to 200 MB</small>
          </span>
          <span aria-hidden="true">→</span>
        </label>
        <div className="h-two">
          <button className="h-opt" type="button" onClick={onSample}>
            <span className="h-ico">
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <path d="M3 13.5 10 17l7-3.5M3 9.5 10 13l7-3.5L10 6 3 9.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
              </svg>
            </span>
            <span>
              <b>Run the sample</b>
              <small>A 50 × 40 × 6 mm bracket · uses 1 check</small>
            </span>
            <span aria-hidden="true">→</span>
          </button>
          <Link className="h-opt" href={R.studio} onClick={rememberWelcomeSeen}>
            <span className="h-ico">
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <rect x="3.5" y="3.5" width="13" height="13" rx="2.5" stroke="currentColor" strokeWidth="1.5" />
                <path d="M7 10h6M10 7v6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </span>
            <span>
              <b>Make a simple part</b>
              <small>Plate, bracket or enclosure · exports STEP</small>
            </span>
            <span aria-hidden="true">→</span>
          </Link>
        </div>
      </div>
      <div className="h-dfoot">
        <span>Costs use typical rates until you add your machines and rates.</span>
        <span className="h-r">
          <Link className="btn sm" href={R.shop} onClick={rememberWelcomeSeen}>
            Set up your shop
          </Link>
        </span>
      </div>
    </Modal>
  );
}

/** "Sample not run": the allowance is used up. Nothing ran, nothing was charged. */
export function SampleQuota({ onClose, onBack }: { onClose: () => void; onBack: () => void }) {
  const { usage } = useShell();
  return (
    <Modal labelledBy="sq-title" onClose={onClose} small>
      <div className="h-hd">
        <div>
          <h1 className="ptitle" id="sq-title">
            Sample not run
          </h1>
          <p className="pmeta" style={{ marginTop: 6 }}>
            {usage ? (
              <span>
                <b>
                  {usage.used} of {usage.cap}
                </b>{" "}
                {usage.plan === "pro" ? "Pro checks used this month" : "free checks used"}
              </span>
            ) : null}
            <span>Your files and saved results are unchanged</span>
          </p>
        </div>
        <CloseX onClose={onClose} />
      </div>
      <div className="h-rbody">
        <p className="h-fine">The sample runs on the real engine, so it uses a check like any part.</p>
      </div>
      <div className="h-dfoot">
        <span className="h-r l">
          <button className="btn ghost sm" type="button" onClick={onBack} data-autofocus>
            Back to start
          </button>
          <Link className="btn ghost sm" href={R.billing}>
            Review usage
          </Link>
        </span>
        <span className="h-r">
          <Link className="btn ink sm" href={R.billing}>
            Upgrade
          </Link>
        </span>
      </div>
    </Modal>
  );
}

/**
 * The overlay state for a page that hosts Get started. `?welcome=1` opens it
 * (and is removed from the address); `autoOpen` opens it once for someone who
 * hasn't seen it (Home passes true for a new organization).
 */
export function useGetStarted(autoOpen: boolean) {
  const router = useRouter();
  const { usage } = useShell();
  const [open, setOpen] = React.useState<"closed" | "welcome" | "quota">("closed");

  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("welcome") !== "1") return;
    setOpen("welcome");
    params.delete("welcome");
    const rest = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${rest ? `?${rest}` : ""}`);
  }, []);

  React.useEffect(() => {
    if (autoOpen && !welcomeSeen()) setOpen((o) => (o === "closed" ? "welcome" : o));
  }, [autoOpen]);

  const close = React.useCallback(() => {
    rememberWelcomeSeen();
    setOpen("closed");
  }, []);

  /** Run the sample on the check page, or say why it can't run. */
  const runSample = React.useCallback(() => {
    if (outOfChecks(usage)) {
      setOpen("quota");
      return;
    }
    rememberWelcomeSeen();
    setOpen("closed");
    router.push(`${R.check}?sample=1`);
  }, [usage, router]);

  const overlay =
    open === "welcome" ? (
      <GetStarted onClose={close} onSample={runSample} />
    ) : open === "quota" ? (
      <SampleQuota onClose={close} onBack={() => setOpen("welcome")} />
    ) : null;

  return { overlay, openGuide: () => setOpen("welcome"), runSample, isOpen: open !== "closed" };
}
