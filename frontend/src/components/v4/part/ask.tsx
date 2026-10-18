"use client";

/** The Ask dock: answers computed from this part's own results, or an honest refusal. */
import * as React from "react";
import Link from "next/link";
import { compareCostDecisions, fetchCostDecisions } from "@/lib/api";
import { R } from "../routes";
import { cx } from "../ui";
import { usePart } from "./ctx";
import {
  REFUSAL,
  driversAnswer,
  leadAnswer,
  methodAnswer,
  money,
  nearestComputed,
  qtyWord,
  routeAsk,
  routesAnswer,
  shortId,
  verdictAnswer,
  type Answer,
} from "./model";

type Key = "routes" | "saved" | "why" | "refuse" | "typed";

export function AskDock() {
  const p = usePart();
  const [ans, setAns] = React.useState<{ key: Key; a: Answer | null; loading?: boolean } | null>(null);
  const atQ = p.qs.includes(1000) ? 1000 : p.qs[p.qs.length - 1] ?? p.q;
  const noCost = p.interrupted || p.costOff || p.checking || !p.data.cost;

  const saved = async () => {
    setAns({ key: "saved", a: null, loading: true });
    const id = p.data.decisionId;
    if (!id || !p.data.key) {
      setAns({ key: "saved", a: { tag: "Not computable", title: "Saved decisions", rows: [], text: "This check isn't saved as a record yet." } });
      return;
    }
    try {
      const page = await fetchCostDecisions({ meshHash: p.data.key, limit: 10 });
      const other = page.cost_decisions.find((d) => d.id !== id);
      if (!other) {
        setAns({ key: "saved", a: { tag: "Computed", title: "Saved decisions", rows: [], text: "This is the only saved decision for this part. Check it again with other conditions or another material to compare." } });
        return;
      }
      const c = await compareCostDecisions(id, other.id);
      const rows = c.unit_cost_by_qty.map((r) => ({ k: qtyWord(r.quantity), v: `${money(r.a?.unit_cost_usd)} vs ${money(r.b?.unit_cost_usd)}` }));
      setAns({
        key: "saved",
        a: {
          tag: "Computed",
          title: `This record vs ${new Date(other.created_at).toLocaleDateString("en-US", { day: "numeric", month: "short" })}`,
          rows,
          text: `Records ${shortId(id)} (${c.a.material_class ?? "?"}) and ${shortId(other.id)} (${c.b.material_class ?? "?"}). Cheapest route at each quantity.`,
          link: { label: "Open both in Compare", href: `${R.compare}?a=${encodeURIComponent(id)}&b=${encodeURIComponent(other.id)}` },
        },
      });
    } catch (e) {
      setAns({ key: "saved", a: { tag: "Not computable", title: "Saved decisions", rows: [], text: e instanceof Error ? e.message : "The compare didn't load." } });
    }
  };

  const pick = (k: Key) => {
    if (ans?.key === k) return setAns(null);
    if (k === "routes") setAns({ key: k, a: routesAnswer(p.methods, atQ) });
    else if (k === "why") setAns({ key: k, a: verdictAnswer(p.methods, p.data.validation, p.data.cost) });
    else if (k === "refuse") setAns({ key: k, a: REFUSAL });
    else if (k === "saved") void saved();
  };

  const submit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const q = String(new FormData(e.currentTarget).get("q") ?? "").trim();
    if (!q) return;
    const r = routeAsk(q, p.methods);
    const qq = r.kind === "routes" ? nearestComputed(p.qs, r.qty, p.q) : p.q;
    let a: Answer | null = null;
    if (r.kind === "method") {
      const m = p.methods.find((x) => x.code === r.code);
      a = m ? methodAnswer(m, p.q, p.data.cost?.material_class ?? null) : null;
    } else if (r.kind === "lead") a = leadAnswer(p.methods, p.q);
    else if (r.kind === "drivers") a = driversAnswer(p.methods.find((m) => m.inHouse && m.prices.has(p.q)) ?? p.sel ?? null, p.q);
    else if (r.kind === "routes") {
      a = routesAnswer(p.methods, qq);
      if (a && r.qty != null && r.qty !== qq) a = { ...a, text: `${qtyWord(r.qty)} isn't a computed quantity, so this is ${qtyWord(qq)}, the nearest. ${a.text}` };
    } else if (r.kind === "why") a = verdictAnswer(p.methods, p.data.validation, p.data.cost);
    else if (r.kind === "saved") return void saved();
    else a = REFUSAL;
    setAns({ key: "typed", a: a ?? { tag: "Not computable", title: "Not in this check", rows: [], text: "This check has no result for that yet." } });
  };

  const chips: [Key, string, boolean][] = [
    ["routes", `At ${qtyWord(atQ)}`, noCost],
    ["saved", "Saved decisions", noCost],
    ["why", "Why this verdict?", p.interrupted || p.checking || !p.data.validation],
    ["refuse", "Out of scope", false],
  ];
  const a = ans?.a;
  return (
    <>
      {ans ? (
        <div className="note swap answer" role="region" aria-label="Answer" aria-live="polite">
          <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className={cx("src", a?.tag === "Computed" ? "s-file" : "s-typ")}>{ans.loading ? "Computing" : a?.tag}</span>
            <b style={{ fontSize: 14 }}>{ans.loading ? "Saved decisions" : a?.title}</b>
            <button type="button" className="btn sm ghost" aria-label="Dismiss" onClick={() => setAns(null)} style={{ marginLeft: "auto", width: 28, height: 28, padding: 0 }}>
              ✕
            </button>
          </span>
          {ans.loading ? <span style={{ color: "var(--ink3)", fontSize: 13 }}>Loading the saved decisions…</span> : null}
          {a?.rows.map((r, i) => (
            <span key={i} className="num ar">
              <span style={{ color: "var(--ink2)" }}>{r.k}</span>
              <b style={{ fontWeight: 600 }}>{r.v}</b>
            </span>
          ))}
          {a ? <span style={{ fontSize: 13 }}>{a.text}</span> : null}
          {a?.link ? (
            <span>
              <Link className="btn sm" href={a.link.href}>
                {a.link.label}
              </Link>
            </span>
          ) : null}
        </div>
      ) : null}
      <div className="askchips">
        {chips.map(([k, label, off]) => (
          <button key={k} type="button" className={cx("btn sm", ans?.key === k && "ink")} aria-disabled={off} aria-pressed={ans?.key === k} onClick={() => !off && pick(k)} style={off ? { opacity: 0.45, cursor: "default" } : undefined}>
            {label}
          </button>
        ))}
      </div>
      <form className="ask" role="search" aria-label="Ask about this part" onSubmit={submit}>
        <label style={{ display: "contents" }}>
          <span className="sr">Ask about this part</span>
          <input type="text" name="q" placeholder="Ask about this part: lathe? lead time? cost drivers?" autoComplete="off" />
        </label>
        <button className="btn sm" type="submit">
          Ask
        </button>
      </form>
    </>
  );
}
