"use client";

/** O1: check a part. Drop or choose a file, or run the sample. */
import * as React from "react";
import Link from "next/link";
import { listMachines } from "@/lib/verify/machine-api";
import { effectiveRateCard } from "@/lib/verify/rate-api";
import { fetchCostDecisions } from "@/lib/api";
import { CAD_ACCEPT } from "../pending-file";
import { R } from "../routes";
import { cx } from "../ui";
import { useShell } from "../shell";

function mb(n: number): string {
  return `${(n / 1048576).toFixed(n < 1048576 ? 2 : 1)} MB`;
}

const TOOLS: [string, [string, string, string?][]][] = [
  ["Parts", [["Your parts", R.parts], ["Records", R.records], ["Recent analyses", R.analyses], ["Compare A/B", R.compare], ["RFQ packages", R.packages], ["Programs", R.programs]]],
  ["Many parts · Pilot", [["Batch runs", R.many], ["Triage", R.triage], ["Import from SAP", R.imports, "read only"], ["Import from Windchill", R.imports, "read only"]]],
  ["Make and fit", [["Design Studio", R.studio], ["Cost and DFM workbench", R.workbench], ["Fit in context", R.fit, "Pilot"], ["Photo to 3D", R.photo]]],
  ["Your shop", [["Machines and printers", R.shop], ["Rates and actual costs", R.rates], ["Changes to review", R.changes], ["Actual results", R.actuals]]],
  ["Account", [["Organization", R.org], ["Security and sign-in", R.security], ["API and docs", R.api], ["Integrations", R.imports], ["Plan and billing", R.billing], ["Notifications", R.notifications]]],
];

export function StartScreen({
  file,
  onFile,
  onClear,
  onCheck,
  onSample,
  notice,
}: {
  file: File | null;
  onFile: (f: File) => void;
  onClear: () => void;
  onCheck: () => void;
  onSample: () => void;
  notice?: React.ReactNode;
}) {
  const { usage } = useShell();
  const [over, setOver] = React.useState(false);
  const [open, setOpen] = React.useState(false);
  const [machines, setMachines] = React.useState<number | null>(null);
  const [checked, setChecked] = React.useState<number | null>(null);
  const [rates, setRates] = React.useState<string | null>(null);
  const input = React.useRef<HTMLInputElement>(null);
  React.useEffect(() => {
    listMachines().then((p) => setMachines(p.machines.length)).catch(() => setMachines(null));
    fetchCostDecisions({ limit: 1 }).then((p) => setChecked(p.cost_decisions.length)).catch(() => setChecked(null));
    effectiveRateCard().then((c) => setRates(c.using_governed ? "Rates: your rate card" : "Rates: Default v0, typical")).catch(() => setRates(null));
  }, []);
  const checksLine = !usage ? null : usage.unlimited ? (
    <span>
      <b>Unlimited</b> checks · {usage.plan === "pilot" ? "pilot" : usage.plan}
    </span>
  ) : (
    <span>
      <b>{usage.remaining}</b> {usage.plan === "pro" ? `of ${usage.cap} Pro checks left` : "free checks"}
    </span>
  );
  const uses = usage && !usage.unlimited ? ` · uses 1 of ${usage.remaining} ${usage.plan === "pro" ? "Pro" : "free"} checks` : " · uses 1 check";
  const steps: [string, string, boolean | null, string | null][] = [
    ["First part", "The sample or your own file.", checked == null ? null : checked > 0, null],
    ["Service conditions", "Rules out materials that won't survive heat, pressure or chemicals.", null, R.setup],
    ["Machines and printers", "Answers name the machine and use your rates.", machines == null ? null : machines > 0, R.shop],
    ["Real costs", "A method’s range turns measured with 3 held-out jobs; recalibration needs 8.", null, R.actuals],
  ];
  const done = steps.filter((s) => s[2] === true).length;
  const nowIdx = steps.findIndex((s) => s[2] !== true);
  return (
    <main className="world pv" aria-label="Check a part">
      <section className="stage" aria-label="Check a part">
        <div className="floor" />
        <div className="pagehead">
          <h1 className="ptitle">Check a part</h1>
          <p className="pmeta">
            {checksLine}
            {rates ? <span>{rates}</span> : null}
            {machines != null ? <span>{machines ? `${machines} machine${machines === 1 ? "" : "s"}` : "No machines yet"}</span> : null}
          </p>
        </div>
        {notice ? <div style={{ position: "absolute", left: "calc(33% - 300px)", width: 600, top: 96, zIndex: 3 }}>{notice}</div> : null}
        <div
          className={cx("plinth", over && "over")}
          role="group"
          aria-label="Drop a CAD file here"
          onDragEnter={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragOver={(e) => e.preventDefault()}
          onDragLeave={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node)) setOver(false);
          }}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            const f = e.dataTransfer?.files?.[0];
            if (f) onFile(f);
          }}
        >
          <span className="ico">
            <svg width="22" height="22" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="M10 13V3.5M6 7.5l4-4 4 4M3.5 12.5v2.5a1.5 1.5 0 0 0 1.5 1.5h10a1.5 1.5 0 0 0 1.5-1.5v-2.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <b aria-live="polite">{file ? file.name : over ? "Drop to check it" : "Drop a STEP, STL or IGES file"}</b>
          <span>{file ? `${mb(file.size)} · ready to check${uses}` : "Up to 200 MB · visible to your team only"}</span>
          {file ? (
            <span className="swap" style={{ display: "flex", gap: 8, marginTop: 6 }}>
              <button className="btn go" type="button" onClick={onCheck}>
                Check it
              </button>
              <button className="btn" type="button" onClick={onClear}>
                Choose another
              </button>
            </span>
          ) : (
            <>
              <span style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap", justifyContent: "center" }}>
                <button className="btn ink" type="button" onClick={() => input.current?.click()}>
                  Choose a file
                </button>
                <button className="btn" type="button" onClick={onSample}>
                  Try a sample part
                </button>
              </span>
              <span>The sample uses 1 check.</span>
            </>
          )}
          <input
            ref={input}
            type="file"
            accept={CAD_ACCEPT}
            aria-label="Choose a CAD file to check"
            tabIndex={-1}
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) onFile(f);
            }}
          />
        </div>
        <p className="five">Available after a check</p>
      </section>
      <aside className="sheet" aria-label="Getting started">
        <div className="top">
          <h2 className="stitle">Setup</h2>
          <p className="smeta">{done} done · optional</p>
        </div>
        <div className="scroll">
          {steps.map(([t, d, isDone, href], i) => {
            const body = (
              <>
                <span className="n" aria-hidden="true">
                  {isDone ? "✓" : i + 1}
                </span>
                <span>
                  <b>
                    {t}
                    {isDone ? <span className="sr"> (done)</span> : null}
                  </b>
                  <span>{d}</span>
                </span>
              </>
            );
            const cls = cx("setup-step", isDone && "done", i === nowIdx && "now");
            return href ? (
              <Link key={t} className={cls} href={href}>
                {body}
              </Link>
            ) : (
              <div key={t} className={cls}>
                {body}
              </div>
            );
          })}
          <div style={{ height: 1, background: "var(--rule)", margin: "8px 12px" }} />
          <button className="tools-btn" type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            All tools <em>{TOOLS.reduce((n, [, l]) => n + l.length, 0)}</em>
            <span>{open ? "Hide" : "Show all"}</span>
          </button>
          {open ? (
            <div className="tg swap">
              {TOOLS.map(([h, links]) => (
                <React.Fragment key={h}>
                  <h3>{h}</h3>
                  {links.map(([label, href, note]) => (
                    <Link key={label} href={href}>
                      {label}
                      <em>{note ?? ""}</em>
                    </Link>
                  ))}
                </React.Fragment>
              ))}
            </div>
          ) : null}
        </div>
      </aside>
      <div className="dial preview" aria-label="The five answers every part gets" role="group">
        {[
          ["Make", "how"],
          ["Cost", "how many"],
          ["Use", "where"],
          ["Shop", "your machines"],
          ["Decide", "what next"],
        ].map(([a, b]) => (
          <span key={a}>
            {a}
            <small>{b}</small>
          </span>
        ))}
      </div>
    </main>
  );
}
