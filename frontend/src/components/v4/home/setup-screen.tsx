"use client";

/**
 * Organization setup (board X13): the six steps that make answers fit the shop,
 * each from the organization's own data. Opened from the account menu ("Start
 * here"), search ("Set up your organization") or Home.
 */
import * as React from "react";
import Link from "next/link";
import { useAuth } from "@/components/ui/auth-provider";
import { R } from "../routes";
import { cx } from "../ui";
import { Frame } from "./frame";
import { joinAnd } from "./states";
import * as api from "./data";
import { primaryStep, setupChecklist, setupFacts, type SetupInput, type Tone } from "./setup-derive";
import "./home.css";

type Src = "records" | "parts" | "machines" | "rates" | "portfolio" | "actuals" | "members" | "org";
const ALL: Src[] = ["records", "parts", "machines", "rates", "portfolio", "actuals", "members", "org"];
const NAME: Partial<Record<Src, string>> = { records: "records", machines: "machines", rates: "rates", portfolio: "programs", actuals: "real costs", members: "the team" };

const ROW: Record<Tone, string> = { done: "h-li done", part: "h-li part", warn: "h-li", unk: "h-li", lock: "h-li lock", bad: "h-li bad" };
const CHIP: Record<Tone, string> = { done: "chip c-ok", part: "chip c-warn", warn: "chip c-warn", unk: "chip c-unk", lock: "chip c-unk", bad: "chip c-bad" };

export function SetupScreen() {
  const { user } = useAuth();
  const [d, setD] = React.useState<Omit<SetupInput, "failed" | "me"> & { org: string | null; posture: SetupInput["posture"] }>({
    records: null,
    parts: null,
    machines: null,
    rates: null,
    posture: null,
    programs: null,
    actuals: null,
    members: null,
    org: null,
  });
  const [failed, setFailed] = React.useState<Set<Src>>(new Set());

  const run = React.useCallback((which: Src[], fresh: boolean) => {
    setFailed((f) => new Set([...f].filter((s) => !which.includes(s))));
    const bad = (s: Src) => () => setFailed((f) => new Set([...f, s]));
    const patch = (p: Partial<typeof d>) => setD((cur) => ({ ...cur, ...p }));
    for (const s of which) {
      if (s === "records") api.records(fresh).then((b) => patch({ records: b.cost_decisions.length }), bad(s));
      if (s === "parts") api.catalogPage(1, fresh).then((b) => patch({ parts: api.catalogTotal(b.facets) }), bad(s));
      if (s === "machines") api.machines(fresh).then((m) => patch({ machines: m }), bad(s));
      if (s === "rates") api.rateSource(fresh).then((r) => patch({ rates: r }), bad(s));
      if (s === "portfolio")
        api.portfolio(fresh).then((p) => {
          const f = api.programFacts(p);
          patch({ programs: { programs: f.programs, inProgram: f.inProgram }, posture: p.summary.posture ?? null });
        }, bad(s));
      if (s === "actuals") api.actualCount(fresh).then((n) => patch({ actuals: n }), bad(s));
      if (s === "members") api.members(fresh).then((m) => patch({ members: m }), bad(s));
      if (s === "org") api.org(fresh).then((o) => patch({ org: o.name }), bad(s));
    }
    // `d` is only read through the setter.
  }, []);

  React.useEffect(() => run(ALL, false), [run]);

  const steps = setupChecklist({
    ...d,
    me: user?.email ?? null,
    failed: { records: failed.has("records"), machines: failed.has("machines"), rates: failed.has("rates"), programs: failed.has("portfolio"), actuals: failed.has("actuals"), members: failed.has("members") },
  });
  const facts = setupFacts(steps);
  const primary = primaryStep(steps);
  const missing = [...failed].map((s) => NAME[s]).filter((x): x is string => Boolean(x));

  return (
    <Frame label="Organization setup">
      <div className="h-wrap">
        <div className="h-col">
          <div className="h-shd">
            <div>
              <h1 className="ptitle">Organization setup</h1>
              <p className="pmeta" style={{ marginTop: 6 }}>
                {d.org ? (
                  <span>
                    <b>{d.org}</b>
                  </span>
                ) : null}
                <span>
                  {facts.done} of {steps.length} done
                </span>
                <span>{facts.partly ? `${facts.partly} partly done` : "Nothing required"}</span>
              </p>
              <div className="h-prog" role="img" aria-label={facts.label}>
                {steps.map((s) => (
                  <i key={s.key} className={s.tone === "done" ? "on" : s.tone === "part" ? "half" : ""} />
                ))}
              </div>
            </div>
            <Link className="btn ghost sm" href={R.home}>
              Close
            </Link>
          </div>

          {missing.length ? (
            <div className="panel" role="alert" style={{ padding: "12px 14px", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <span className="chip c-bad">
                <i />
                Not loaded
              </span>
              <span style={{ flex: 1, minWidth: 200, color: "var(--ink2)", fontSize: 13.5 }}>Couldn&apos;t load {joinAnd(missing)}. Steps that need them show as unknown, not empty.</span>
              <button className="btn sm" type="button" onClick={() => run([...failed], true)}>
                Retry
              </button>
            </div>
          ) : null}

          <section className="panel" aria-label="Setup steps">
            <ol className="h-ol">
              {steps.map((s, i) => (
                <li key={s.key} className={ROW[s.tone]}>
                  <span className="h-n" aria-hidden="true">
                    {s.tone === "done" ? "✓" : i + 1}
                  </span>
                  <span className="h-tx">
                    <b>{s.title}</b>
                    <span>{s.detail}</span>
                    {s.sub ? <small>{s.sub}</small> : null}
                  </span>
                  <span className="h-r">
                    <span className={CHIP[s.tone]}>
                      <i />
                      {s.chip}
                    </span>
                    {s.go ? (
                      <Link className={cx("btn sm", s.key === primary && "ink")} href={s.go.href} aria-label={`${s.go.label}: ${s.title}`}>
                        {s.go.label}
                      </Link>
                    ) : null}
                  </span>
                </li>
              ))}
            </ol>
          </section>
          <div className="h-ft">
            <span>Updates from your data</span>
            <span>Open again: Search › Set up your organization</span>
          </div>
        </div>
      </div>
    </Frame>
  );
}
