"use client";

/**
 * Where a check stops before an answer: out of checks (X3), a file that can't be
 * read (X4), and a phone number to verify first.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { UpgradeButton } from "@/components/billing/upgrade-button";
import { formatProPrice, parsePlans, type Plans } from "@/lib/billing";
import { useShell } from "../shell";
import { R } from "../routes";
import { cx } from "../ui";

/* ── X3 ─────────────────────────────────────────────────────────────────── */

export function OutOfChecks({ message, onClose }: { message: string; onClose?: () => void }) {
  const { usage } = useShell();
  const router = useRouter();
  const ref = React.useRef<HTMLElement>(null);
  const back = React.useRef<HTMLElement | null>(null);
  const [plans, setPlans] = React.useState<Plans | null>(null);
  React.useEffect(() => {
    back.current = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    fetch("/api/proxy/billing/plans", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => setPlans(b ? parsePlans(b) : null))
      .catch(() => setPlans(null));
    return () => back.current?.focus?.();
  }, []);
  const pro = usage?.plan === "pro";
  const cap = usage?.cap ?? 0;
  const used = usage?.used ?? cap;
  const price = formatProPrice(plans?.pro.price ?? null);
  const close = () => (onClose ? onClose() : router.push(R.parts));
  return (
    <div className="v4-over">
      <button type="button" className="scrim" tabIndex={-1} aria-hidden="true" onClick={close} />
      <section
        ref={ref}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="oc-title"
        aria-describedby="oc-why"
        tabIndex={-1}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            close();
          }
        }}
      >
        <div className="hd">
          <h1 className="ptitle" id="oc-title">
            {pro ? "This month's Pro checks used" : "Free checks used"}
          </h1>
          <p className="pmeta" style={{ marginTop: 6 }}>
            {cap ? (
              <span>
                <b>
                  {used} of {cap}
                </b>{" "}
                used
              </span>
            ) : null}
            <span>{pro ? "They reset each billing month" : "Free checks don't reset"}</span>
            <span>Saved results stay available</span>
          </p>
          <p id="oc-why" className="sr">
            {message}
          </p>
        </div>
        {cap ? (
          <div className="meter">
            {cap <= 30 ? (
              <div className="barn" role="img" aria-label={`${used} of ${cap} checks used`} style={{ gridTemplateColumns: `repeat(${cap}, minmax(0,1fr))` }}>
                {Array.from({ length: cap }, (_, i) => (
                  <i key={i} className={cx(i >= used && "free")} />
                ))}
              </div>
            ) : (
              <span role="progressbar" aria-label="Checks used" aria-valuemin={0} aria-valuemax={cap} aria-valuenow={used} style={{ height: 10, borderRadius: 4, background: "rgba(20,24,31,.1)", overflow: "hidden", display: "block" }}>
                <span style={{ display: "block", height: "100%", width: `${Math.min(100, (used / cap) * 100)}%`, background: "var(--ink)" }} />
              </span>
            )}
            <span>1 check = one part&apos;s preview, analysis and cost. Re-running a step uses another.</span>
          </div>
        ) : null}
        {!pro ? (
          <div className="opt">
            <span>
              <b>Pro</b>
              <span className="p num">{price ? price.replace("/mo", " / month") : "Monthly"}</span>
            </span>
            <UpgradeButton label="Upgrade" className="btn ink" checkoutAvailable={plans?.pro.checkout_available} />
            <p>{plans?.pro.monthly_checks ?? 50} checks a month · your machines and prices · cancel anytime</p>
            {plans && !plans.pro.checkout_available ? <p className="honest">Checkout is unavailable right now. Email us for more checks.</p> : null}
            <p className="honest">Checks only. Batch runs, Fit in context and other pilot tools aren&apos;t included.</p>
          </div>
        ) : null}
        <div className="opt">
          <span>
            <b>Pilot</b>
            <span className="p num">$7,500 · 4–6 weeks · up to 500 parts</span>
          </span>
          <a className="btn" href="/pilot">
            Plan pilot
          </a>
          <p>One factory · your machines, materials and rates · all tools · credited to year one if you continue</p>
        </div>
        <div className="opt">
          <span>
            <b>Part review</b>
            <span className="p">Free · up to 25 parts</span>
          </span>
          <a className="btn" href="/pilot">
            Request
          </a>
          <p>Parts from one plant · we check whether a pilot fits</p>
        </div>
        <div className="ft">
          <span style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            <Link className="btn ghost sm" href={R.parts}>
              Back to parts
            </Link>
            <Link className="btn ghost sm" href={R.billing}>
              Review usage
            </Link>
          </span>
          <a className="btn ghost sm" href="/contact">
            Contact sales
          </a>
        </div>
      </section>
    </div>
  );
}

/* ── phone ──────────────────────────────────────────────────────────────── */

export function PhoneNeeded({ message }: { message: string }) {
  return (
    <div className="note" role="alert" style={{ margin: "12px 12px 0" }}>
      <b>Verify your phone to start your free checks</b>
      <span>{message}</span>
      <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <a className="btn ink sm" href="/verify">
          Verify your phone
        </a>
        <Link className="btn sm ghost" href={R.billing}>
          Usage and plans
        </Link>
      </span>
      <span style={{ color: "var(--ink3)", fontSize: 12.5 }}>One text with a code. Then drop the file again; nothing was checked yet.</span>
    </div>
  );
}

/* ── X4 ─────────────────────────────────────────────────────────────────── */

const CAD_TOOLS: [string, string, string][] = [
  ["sw", "SOLIDWORKS", "File › Save As, then choose STEP AP214 (*.step)."],
  ["fusion", "Fusion", "File › Export, then choose STEP (*.step)."],
  ["onshape", "Onshape", "Right-click the part › Export, then choose STEP."],
  ["inventor", "Inventor", "File › Export › CAD Format, then choose STEP."],
  ["creo", "Creo", "File › Save As › Save a Copy, then choose STEP."],
  ["nx", "NX", "File › Export › STEP."],
];

export function CadToolSteps() {
  const [tool, setTool] = React.useState("sw");
  const t = CAD_TOOLS.find((x) => x[0] === tool) ?? CAD_TOOLS[0];
  return (
    <>
      <div className="cad-tools" role="group" aria-label="Your CAD tool">
        <span className="seg">
          {CAD_TOOLS.map(([k, label]) => (
            <button key={k} type="button" className={cx(tool === k && "on")} aria-pressed={tool === k} onClick={() => setTool(k)}>
              {label}
            </button>
          ))}
        </span>
      </div>
      <div className="path" aria-live="polite">
        {t[1]}: {t[2]}
      </div>
    </>
  );
}

export function CantReadSheet({
  fileName,
  problem,
  head,
  quote,
  meta,
  onRepair,
  onPick,
  onRetry,
}: {
  fileName: string;
  problem: "open" | "unreadable" | "unsupported" | "geometry" | "refused";
  head: string;
  quote: string;
  meta: string[];
  onRepair?: () => void;
  onPick: () => void;
  onRetry?: () => void;
}) {
  const fixText =
    problem === "open"
      ? "Repair or heal the gap, then export the solid body, not surfaces."
      : problem === "unsupported"
        ? "Export the part as STEP, STL or IGES from your CAD tool, then upload that file."
        : "Re-export as a solid body. Wireframe and sketch exports can’t be checked.";
  return (
    <aside className="sheet" aria-label="What's wrong and how to fix it">
      <div className="top">
        <h1 className="ptitle">Can&apos;t read this file</h1>
        <p className="pmeta" style={{ marginTop: 6 }}>
          {[fileName, ...meta].map((m, i) => (
            <span key={i} style={{ overflowWrap: "anywhere" }}>
              {m}
            </span>
          ))}
        </p>
      </div>
      <div className="scroll">
        <div className="quote" role="alert">
          <b>{head}</b>
          <span>{quote}</span>
        </div>
        <div className="cr-step">
          <b>Fix in CAD</b>
          <p>{fixText}</p>
          <CadToolSteps />
        </div>
        {onRetry ? (
          <>
            <div className="sep" />
            <div className="cr-step">
              <b>Try again</b>
              <p>The check didn&apos;t reach the engine. The file doesn&apos;t need re-exporting.</p>
              <span>
                <button className="btn ink sm" type="button" onClick={onRetry}>
                  Retry check
                </button>
              </span>
            </div>
          </>
        ) : null}
        {problem === "open" && onRepair ? (
          <>
            <div className="sep" />
            <div className="cr-step">
              <b>
                Repair here <small style={{ color: "var(--ink3)", fontWeight: 500 }}>Pilot</small>
              </b>
              <p>Closes gaps and shows the result beside the original. Reports if it can&apos;t.</p>
              <span>
                <button className="btn sm" type="button" onClick={onRepair}>
                  Request repair
                </button>
              </span>
            </div>
          </>
        ) : null}
        <div className="sep" />
        <div className="cr-step">
          <b>Upload another file</b>
          <p>STEP, STL or IGES · up to 200 MB</p>
          <span>
            <button className="btn ink sm" type="button" onClick={onPick}>
              Choose file
            </button>
          </span>
        </div>
      </div>
    </aside>
  );
}
