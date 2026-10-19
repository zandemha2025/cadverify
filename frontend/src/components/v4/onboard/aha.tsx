"use client";

/**
 * N4: the same part re-checked on your machines, before and now. While the
 * re-check runs the sheet says what is being checked; when it lands, the part
 * moves to the Shop lens (drawn to scale inside the machine that can make it)
 * and the sheet answers "You can make it on your Haas VF-2", with what changed
 * from the first check, each machine's verdict, and the next optional steps.
 * Before shows the first check's answer. Every figure comes from the two
 * reports (ahaModel). Picking another lens closes it; the part page reads
 * normally again.
 */
import * as React from "react";
import Link from "next/link";
import { R } from "../routes";
import { cx } from "../ui";
import { usePart } from "../part/ctx";
import { setPanel } from "../part/store";
import { qtyWord } from "../part/model";
import { ahaModel, ranOnMachines } from "./first-run";
import { closeRecheck, type Recheck } from "./state";
import "./onboard.css";

export function Aha({ rc }: { rc: Recheck }) {
  const p = usePart();
  const [before, setBefore] = React.useState(false);
  const [view, setView] = React.useState<"cmp" | "next">("cmp");
  const s = p.session && p.session.startedAt >= rc.startedAt - 100 ? p.session : null;
  const running = !s || s.status === "running";
  const failed = !!s && s.status !== "running" && !(s.status === "done" && p.data.cost && ranOnMachines(p.data.cost));
  const hid = React.useRef<number | null>(null);
  const lensSet = React.useRef(false);
  const wasShop = React.useRef(false);

  // The re-check's own progress panel would cover this sheet: it says the same here.
  React.useEffect(() => {
    if (s && hid.current !== s.id) {
      hid.current = s.id;
      setPanel(s.id, false);
    }
  }, [s]);

  // The re-check runs on the Shop lens (the part beside the machine, as the answer will be);
  // on a phone the answer is scrolled into view when it lands.
  const sheetRef = React.useRef<HTMLElement>(null);
  const scrolled = React.useRef(false);
  React.useEffect(() => {
    if (!lensSet.current && !failed) {
      lensSet.current = true;
      p.setLens("shop");
    }
    if (!running && !failed && !scrolled.current) {
      scrolled.current = true;
      if (window.matchMedia("(max-width:900px)").matches) {
        const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        requestAnimationFrame(() => sheetRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" }));
      }
    }
  }, [running, failed, p]);

  // Another lens closes it.
  React.useEffect(() => {
    // Only once the part has been on Shop: switching to it happens a render after asking.
    if (p.lens === "shop") wasShop.current = true;
    else if (wasShop.current) closeRecheck();
  }, [p.lens]);

  const qs = p.qs;
  const q = p.q;
  const model = React.useMemo(
    () => (!running && !failed && p.data.cost ? ahaModel({ before: rc.before, now: p.data.cost, machines: p.data.machines, validation: p.data.validation, q, showBefore: before }) : null),
    [running, failed, p.data.cost, p.data.machines, p.data.validation, q, before, rc.before],
  );
  const names = rc.machines.length ? rc.machines : p.data.machines.map((m) => m.name ?? m.process);
  const namesText = names.length <= 2 ? names.join(" and ") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

  if (running) {
    const v = s?.validation ?? null;
    return (
      <>
        <aside className="sheet nb-aha" aria-label="Re-checking">
          <div className="top">
            <h2 className="stitle">Re-checking</h2>
            <p className="smeta">Against {namesText} · same file, no new check</p>
          </div>
          <ol className="pst" role="status" aria-live="polite">
            <li className={v ? "done" : "now"}>
              <span className="m" aria-hidden="true">
                {v ? "✓" : ""}
              </span>
              <span>
                <b>Shape and ways</b>
                <span>{v ? "Same file, same result as the first check" : "Measuring the same file again…"}</span>
              </span>
            </li>
            <li className={v ? "now" : ""}>
              <span className="m" aria-hidden="true" />
              <span>
                <b>Your machines</b>
                <span>Work area, heaviest part and materials for each</span>
              </span>
            </li>
            <li>
              <span className="m" aria-hidden="true" />
              <span>
                <b>In-house prices</b>
                <span>At your rates where you entered one, typical where blank</span>
              </span>
            </li>
          </ol>
        </aside>
        <div className="nb-tk swap" aria-hidden="true">
          <span className="k">Checking your machines</span>
          <span className="big num">
            {names.length} {names.length === 1 ? "machine" : "machines"}
          </span>
          <span className="s">{namesText}</span>
        </div>
      </>
    );
  }

  if (failed || !model) {
    const msg = s?.failure && "message" in s.failure ? s.failure.message : s?.result?.costError ?? "The re-check didn’t finish.";
    return (
      <aside className="sheet nb-aha" aria-label="Re-check">
        <div className="top">
          <h2 className="stitle">The re-check didn’t finish</h2>
          <p className="smeta">Your machines are saved. The answer below is from before.</p>
        </div>
        <div className="scroll">
          <p className="nb-err" role="alert" style={{ margin: "8px 12px" }}>
            {msg}
          </p>
          <div style={{ display: "flex", gap: 8, padding: "6px 12px" }}>
            {p.canRecheck ? (
              <button className="btn ink sm" type="button" onClick={() => p.recheck({ materialClass: rc.before.material_class })}>
                Re-check again
              </button>
            ) : null}
            <button className="btn sm" type="button" onClick={closeRecheck}>
              Close
            </button>
          </div>
        </div>
      </aside>
    );
  }

  const qw = qtyWord(q);
  return (
    <>
      {before && !model.beforeOn ? (
        <div className="nb-empty2 swap" aria-hidden="true">
          <b>No machine to fit it in</b>
          <span>No machines were added at the first check, so in-house wasn’t checked</span>
        </div>
      ) : null}
      {model.ticket ? (
        <div className={cx("nb-tk swap", !before && model.best && "now")} key={before ? "b" : "n"} aria-hidden="true">
          <span className="k">{model.ticket.k}</span>
          <span className="big num">{model.ticket.big}</span>
          <span className="s">{model.ticket.s}</span>
        </div>
      ) : null}
      <aside ref={sheetRef} className={cx("sheet nb-aha", before && !model.beforeOn && "nb-before")} aria-label="The answer">
        <div className="top">
          <div className="row1">
            <span className="seg" role="group" aria-label="Compare">
              <button type="button" className={cx(before && "on")} aria-pressed={before} onClick={() => setBefore(true)}>
                Before
              </button>
              <button type="button" className={cx(!before && "on")} aria-pressed={!before} onClick={() => setBefore(false)}>
                Now
              </button>
            </span>
            <span className="smeta" style={{ margin: 0 }}>
              {before ? (model.beforeOn ? "Before this change" : "First check") : "Re-checked just now"}
            </span>
          </div>
          <h2 className="lead" aria-live="polite">
            {model.lead.a}
            <em className={cx(model.lead.tone === "no" && "no", model.lead.tone === "plain" && "plain")}>{model.lead.b}</em>
          </h2>
          <p className="sub">{model.sub}</p>
          {qs.length > 1 ? (
            <div style={{ marginTop: 12 }}>
              <span className="seg" role="group" aria-label="Quantity">
                {qs.map((n) => (
                  <button key={n} type="button" className={cx("num", n === q && "on")} aria-pressed={n === q} onClick={() => p.setQ(n)}>
                    {qtyWord(n)}
                  </button>
                ))}
              </span>
            </div>
          ) : null}
        </div>
        <div className="scroll">
          {view === "next" ? (
            <div className="swap">
              <div className="gh">
                <span>Next, if you want</span>
                <span>all optional</span>
              </div>
              <div className="nx">
                <b>Where it’s used</b>
                <span>Heat, pressure, chemicals or a standard can rule out materials and machines.{Object.keys(p.data.context?.service_environment ?? {}).length ? "" : " Not set for this part."}</span>
                <button className="btn sm" type="button" onClick={() => p.setLens("use")}>
                  Set conditions
                </button>
              </div>
              <div className="nx">
                <b>Your labor rate</b>
                <span>{model.labor ?? "Your labor rate changes every in-house price."}</span>
                <Link className="btn sm" href={R.rates}>
                  Set labor rate
                </Link>
              </div>
              <div className="nx">
                <b>Your team</b>
                <span>People you invite get these machines and rates and skip this setup.</span>
                <Link className="btn sm" href={R.org}>
                  Invite
                </Link>
              </div>
              <div style={{ display: "flex", gap: 8, padding: "14px 12px 4px", alignItems: "center", flexWrap: "wrap" }}>
                <Link className="btn ink" href={R.home} onClick={closeRecheck}>
                  Done for now
                </Link>
                <button className="btn ghost" type="button" onClick={() => setView("cmp")}>
                  Back to the answer
                </button>
              </div>
              <p className="nb-fine">Rates and team stay on Home › Setup until they’re done.</p>
            </div>
          ) : (
            <div className="swap">
              <div className="gh">
                <span>What changed, at {qw}</span>
                <span>same file, same engine</span>
              </div>
              <div className="nb-cmp">
                <div className="cr hd">
                  <span />
                  <span>Before</span>
                  <i />
                  <span>Now</span>
                </div>
                {model.rows.map((r) => (
                  <div className="cr" key={r.k}>
                    <span className="k">{r.k}</span>
                    <span className="b num">
                      {r.b}
                      <small>{r.bs}</small>
                    </span>
                    <i aria-hidden="true">→</i>
                    <span className={cx("a num", r.tone === "ok" && "ok")}>
                      {r.a}
                      <small>{r.as}</small>
                    </span>
                  </div>
                ))}
              </div>
              <div className="gh" style={{ marginTop: 6 }}>
                <span>{before ? (model.beforeOn ? "Your machines · before this change" : "Your machines · none at the first check") : `Your machines · ${model.n}`}</span>
                <span>
                  <Link href={R.shop}>Edit</Link>
                </span>
              </div>
              {before
                ? null
                : model.machines.map((m) => (
                    <button key={m.id} type="button" className={cx("mr", m.on && "on")} aria-pressed={p.machinePick === m.id || (m.on && !p.machinePick)} onClick={() => p.setMachinePick(m.id)}>
                      <span>
                        <b>{m.name}</b>
                        <small>{m.sub}</small>
                      </span>
                      <span className={`chip c-${m.tone}`}>
                        <i />
                        {m.verdict}
                      </span>
                      <span className="c num">{m.cost}</span>
                    </button>
                  ))}
              <p className="nb-fine">{model.foot}</p>
            </div>
          )}
        </div>
        {view === "cmp" ? (
          <div className="sfoot">
            <button className="btn ink sm" type="button" onClick={() => setView("next")}>
              Next steps
            </button>
            <button className="btn sm" type="button" onClick={() => p.setLens("decide")}>
              Decide
            </button>
            <span>{p.data.decisionId ? "Saved to the part’s record" : "Not saved: record keeping is off"}</span>
          </div>
        ) : null}
      </aside>
    </>
  );
}
