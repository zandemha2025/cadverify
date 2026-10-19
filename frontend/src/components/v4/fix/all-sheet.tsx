"use client";

/** K4: every problem on the part, ranked by what fixing it makes possible, or grouped by where it is. */
import * as React from "react";
import { cx } from "../ui";
import { useShell } from "../shell";
import { usePart } from "../part/ctx";
import { classLabel } from "../part/sheet-bits";
import { cheapestAt, money, priceAt, qtyWord } from "../part/model";
import { allQuantities, defaultMethod, useFix } from "./ctx";
import { fixText, measuredFig, type Problem } from "./problems";
import { placeName, placesOf, type Unlock } from "./rank";
import { fixRoute, whoFixes } from "./capabilities";
import { useUploadFixed } from "./problem-sheet";
import "./fix.css";

/** "Checked like any upload · uses 1 of your 12 checks left", from what the usage API reports. */
export function newCheckLine(usage: { unlimited: boolean; remaining: number } | null, lead = "Checked like any upload"): string {
  if (!usage) return lead;
  if (usage.unlimited) return `${lead} · no check limit on your plan`;
  return `${lead} · uses 1 of your ${usage.remaining} ${usage.remaining === 1 ? "check" : "checks"} left`;
}

function needsLine(p: Problem): string {
  const groups = new Map<string, string[]>();
  for (const m of p.methods) {
    const k = m.need == null ? "" : m.unit === "deg" ? `${m.need}°` : m.unit === "mm" ? `${m.need.toFixed(1)} mm` : String(m.need);
    if (!k) continue;
    (groups.get(k) ?? groups.set(k, []).get(k)!).push(m.name.charAt(0).toLowerCase() + m.name.slice(1));
  }
  const parts = [...groups.entries()].slice(0, 4).map(([k, names]) => `${k}: ${[...new Set(names)].join(", ")}`);
  if (parts.length) return parts.join(" · ");
  if (p.id === "open") return "A closed solid, for every method";
  return p.noChange === "shop" ? "Nothing in the design" : p.methods.length ? `Reported by ${p.methods.length} ${p.methods.length === 1 ? "method" : "methods"}` : "Every method";
}

export function AllProblemsSheet() {
  const p = usePart();
  const fx = useFix();
  const shell = useShell();
  const up = useUploadFixed();
  const v = fx.view?.kind === "all" ? fx.view : null;
  const [openId, setOpenId] = React.useState<string | null>(null);
  if (!v) return null;
  const q = fx.allQty;
  const qs = allQuantities(p.qs);
  const ranked = fx.ranked;
  const places = placesOf(ranked);
  const sel = ranked.find((u) => u.problem.id === v.sel)?.problem ?? ranked[0]?.problem ?? null;
  const n = ranked.length;
  const singles = p.methods.filter((m) => m.members.length === 1);
  const today = cheapestAt(singles, q);
  const first = ranked.find((u) => u.tier < 3) ?? null;
  const fixable = ranked.filter((u) => fixRoute(u.problem, fx.origin));
  const millingWorks = singles.some((m) => (m.code === "cnc_3axis" || m.code === "cnc_5axis") && (m.verdict === "ok" || m.verdict === "warn"));
  const firstFix = fixable[0] ? fixRoute(fixable[0].problem, fx.origin) : null;
  const figs = [
    today ? { k: "Cheapest today", v: money(priceAt(today, q)), s: today.name.toLowerCase(), tone: "" } : { k: "Cheapest today", v: p.data.cost ? "None" : "Not priced", s: p.data.cost ? "all blocked" : "analysis only", tone: p.data.cost ? "bad" : "" },
    first ? { k: "First fix", v: first.value.replace(/ each$/, ""), s: placeName(first.problem).toLowerCase(), tone: first.tier <= 1 ? "ok" : "" } : { k: "First fix", v: "None", s: "nothing to unlock", tone: "" },
    { k: "ScaleCAD fixes", v: `${fixable.length} of ${n}`, s: fixable.length ? (firstFix?.kind === "repair" ? "mesh repair, on a copy" : firstFix?.kind === "studio" ? `as revision ${(fx.origin.studio?.currentRevision ?? 0) + 1}` : "on a copy") : "by itself", tone: "" },
  ];
  const row = (u: Unlock) => {
    const P = u.problem;
    const rank = ranked.indexOf(u) + 1;
    const on = sel?.id === P.id;
    const expanded = on && openId === P.id;
    const place = places.find((pl) => pl.ids.includes(P.id));
    const who = whoFixes(P, fx.origin, millingWorks);
    const m0 = defaultMethod(P, fx.set, p.methods, q, null, null);
    const meas = measuredFig(P, m0);
    return (
      <React.Fragment key={P.id}>
        <button
          type="button"
          className={cx("kpr", on && "on")}
          aria-pressed={on}
          aria-expanded={expanded}
          onClick={() => {
            fx.setAll({ sel: P.id });
            setOpenId(expanded ? null : P.id);
          }}
        >
          <span className="rk">{rank}</span>
          <span>
            <b>{P.title}</b>
            <small>
              <span className="where">
                <i>{place?.n ?? "·"}</i>
                {P.where}
              </span>
            </small>
            <small>{u.sub}</small>
          </span>
          <span className="vv">
            <strong className={cx(u.tier <= 1 && "ok")}>{u.value}</strong>
            <span className={cx("chip", who.tone)}>
              <i />
              {who.label}
            </span>
          </span>
        </button>
        {expanded ? (
          <div className="kpd swap">
            <span>Measured</span>
            <span>
              {meas.v} · {meas.s}
            </span>
            <span>Needs</span>
            <span>{needsLine(P)}</span>
            <span>Fix</span>
            <span>{fixText(P, m0, null).fix}</span>
            <span>Check</span>
            <span className="kcode">{P.codes.join(" · ")}</span>
            <button className="btn sm kshow" type="button" onClick={() => fx.openProblem(P.id)}>
              Show it on the part
            </button>
          </div>
        ) : null}
      </React.Fragment>
    );
  };
  const ext = p.data.fileType ? p.data.fileType.toUpperCase() : "file";
  const faText = fx.origin.studio
    ? fixable.length
      ? `${fixable.map((u) => u.problem.title.toLowerCase()).join(", ")}: as revision ${fx.origin.studio.currentRevision + 1}, then a check. The rest aren’t template parameters; download the STEP from Design Studio to change them in your CAD tool.`
      : "None of these is a template parameter. Download the STEP from Design Studio to change them in your CAD tool."
    : fx.origin.open
      ? "The open shell, with mesh repair on a copy (a pilot tool). Everything else is a change in your CAD tool; upload the new file and it’s checked again."
      : `This is a closed ${ext}. Mesh repair only closes open shells, and ScaleCAD doesn’t edit CAD geometry. Each fix is a change in your CAD tool; upload the new file and it’s checked again.`;
  return (
    <>
      <div className="top">
        <h2 className="stitle">{n ? `${n} ${n === 1 ? "problem" : "problems"} on this part` : "No problems on this part"}</h2>
        <p className="smeta">
          {v.by === "place" ? "Grouped by where they are on the part" : "Ranked by what fixing each makes possible"} · at {qtyWord(q)} · {classLabel(p.data.cost?.material_class).toLowerCase()}
        </p>
        <div className="figs">
          {figs.map((g) => (
            <div className="fig" key={g.k}>
              <span>{g.k}</span>
              <b className={cx("num", g.tone, !/^[$\d−+]/.test(g.v) && "t")}>{g.v}</b>
              <small>{g.s}</small>
            </div>
          ))}
        </div>
        <div className="kctl">
          <span className="seg" role="group" aria-label="Order">
            {(
              [
                ["rank", "Ranked"],
                ["place", "By place"],
              ] as const
            ).map(([k, label]) => (
              <button key={k} type="button" className={cx(v.by === k && "on")} aria-pressed={v.by === k} onClick={() => fx.setAll({ by: k })}>
                {label}
              </button>
            ))}
          </span>
          {qs.length > 1 ? (
            <span className="seg" role="group" aria-label="Quantity">
              {qs.map((x) => (
                <button key={x} type="button" className={cx("num", x === q && "on")} aria-pressed={x === q} onClick={() => fx.setAll({ q: x })}>
                  {qtyWord(x)}
                </button>
              ))}
            </span>
          ) : null}
        </div>
        <p className="krule2">New lowest price first, then methods added, then warnings cleared · prices if redesigned</p>
      </div>
      <div className="scroll">
        {!n ? <p className="kplain">The check reported nothing that stops or flags a method, beyond the notes below.</p> : null}
        {v.by === "place"
          ? places.map((pl) => (
              <React.Fragment key={pl.name}>
                <div className="gh">
                  <span>{pl.n === "·" ? pl.name : `${pl.n} · ${pl.name}`}</span>
                  <span>
                    {pl.ids.length} {pl.ids.length === 1 ? "problem" : "problems"}
                  </span>
                </div>
                {ranked.filter((u) => pl.ids.includes(u.problem.id)).map(row)}
              </React.Fragment>
            ))
          : ranked.map(row)}
        {fx.set.notListed ? <p className="knl">{fx.set.notListed}</p> : null}
      </div>
      <div className="kfa">
        <b>
          ScaleCAD can fix {fixable.length} of {n} here
        </b>
        <p>{faText}</p>
        <div className="row">
          {fixable.length && firstFix ? (
            <button className="btn ink sm" type="button" onClick={() => fx.openAsk(fixable[0].problem.id, firstFix.kind === "repair" ? "repair" : firstFix.kind === "studio" ? "studio" : "upload")}>
              Fix what ScaleCAD can
            </button>
          ) : null}
          {sel ? (
            <button className="btn sm" type="button" onClick={() => fx.openAsk(sel.id, "upload")}>
              Steps for your CAD tool
            </button>
          ) : null}
          {!fx.origin.studio ? (
            <button className="btn sm" type="button" onClick={up.pick}>
              Upload the fixed file
            </button>
          ) : null}
          {up.el}
        </div>
        <div className="row">
          <span>{newCheckLine(shell.usage)}</span>
        </div>
      </div>
    </>
  );
}
