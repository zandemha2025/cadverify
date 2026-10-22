"use client";

/**
 * Orientation on the part page: turn the part, see which faces the check's own
 * rule marks for the selected method in that orientation, compare the ways to
 * lay it down, and re-check in the chosen one; then what changed, before and
 * after (findings, methods, prices), from the two checks.
 *
 * - OrientTool: the stage button that opens it.
 * - OrientChip: the HUD fact "Checked with the file's +Y up" when the shown
 *   result was turned.
 * - OrientPanel: the sheet, mounted in the part page's overlay. The 3D view
 *   reads the same state (state.ts useOrientView, passed to the viewer).
 *
 * Every figure comes from the engine: the comparison from
 * GET /parts/{hash}/orientations, the before and after from the two checks.
 * A re-check is the same file, so it uses no check.
 */
import * as React from "react";
import { API_BASE } from "@/lib/api-base";
import { apiProblemDetail } from "@/lib/api-recovery";
import { cx } from "../ui";
import { usePart } from "../part/ctx";
import { useFix } from "../fix/ctx";
import { setPanel } from "../part/store";
import { KIND_COLOR, qtyWord, trimNum } from "../part/model";
import { processLabel } from "../process-names";
import {
  candidateFacts,
  candidateFor,
  candidateMat,
  candidateName,
  compare,
  isIdentity,
  label,
  matOf,
  orientationParam,
  flagWords,
  notComparedWords,
  priceBasis,
  PRICES_LINE,
  rankedFor,
  recordOf,
  same,
  shadeFor,
  turned,
  upWord,
  whyLine,
  IDENTITY,
  type Candidate,
  type Mat,
  type Options,
} from "./orient";
import { closeOrient, openOrient, patchOrient, useOrient, type OrientRecheck } from "./state";
import "./orient.css";

/** The orientation of the result on screen (identity for the file's own). */
function useShown(): Mat {
  const p = usePart();
  const rec = recordOf(p.data.validation) ?? recordOf(p.data.cost);
  return React.useMemo(() => matOf(rec), [rec]);
}

export function OrientTool() {
  const p = usePart();
  const key = p.data.key;
  const st = useOrient(key);
  const shown = useShown();
  if (!key) return null;
  const on = !!st;
  return (
    <button
      className={cx("btn sm", on && "ink")}
      type="button"
      aria-pressed={on}
      title="Turn the part to how it will be made, and re-check it that way"
      onClick={() => {
        if (on) return closeOrient();
        openOrient(key, shown);
        p.setLens("make");
      }}
    >
      Orientation
    </button>
  );
}

export function OrientChip() {
  const p = usePart();
  const rec = recordOf(p.data.validation) ?? recordOf(p.data.cost);
  if (!rec) return null;
  return (
    <span className="src s-typ" title={rec.note ?? "This check turned the part before measuring it."}>
      Checked with the file&apos;s {upWord(matOf(rec))} up
    </span>
  );
}

type Loaded = { s: "loading" } | { s: "ready"; o: Options } | { s: "none"; why: string };

function useOptions(key: string | null, units: "mm" | "inch", picked: number[] | null, needPicked: boolean): Loaded {
  const [state, setState] = React.useState<{ k: string; v: Loaded } | null>(null);
  const down = needPicked && picked ? picked.map((c) => Number(c.toFixed(9))).join(",") : null;
  const k = `${key}|${units}|${down ?? ""}`;
  React.useEffect(() => {
    if (!key) return;
    let live = true;
    const q = new URLSearchParams({ units });
    if (down) q.set("down", down);
    fetch(`${API_BASE}/parts/${encodeURIComponent(key)}/orientations?${q}`, { cache: "no-store" })
      .then(async (r) => {
        const body = await r.json().catch(() => null);
        if (!live) return;
        if (r.ok && body) setState({ k, v: { s: "ready", o: body as Options } });
        else if (r.status === 404 && /No stored source/.test(JSON.stringify(body ?? ""))) setState({ k, v: { s: "none", why: "ScaleCAD doesn't keep this file in your organization, so it can't compare the ways to lay it down. You can still turn it and re-check." } });
        else setState({ k, v: { s: "none", why: apiProblemDetail(body) ?? "The ways to lay it down didn't load. You can still turn it and re-check." } });
      })
      .catch(() => live && setState({ k, v: { s: "none", why: "The ways to lay it down couldn't reach the server. You can still turn it and re-check." } }));
    return () => {
      live = false;
    };
  }, [key, units, down, k]);
  return state && state.k === k ? state.v : { s: "loading" };
}

function processOf(code: string | null | undefined, members: string[] | undefined): string | null {
  return members?.[0] ?? code ?? null;
}

const TURNS: { axis: "x" | "y" | "z"; text: string; title: string }[] = [
  { axis: "x", text: "Tip forward", title: "A quarter turn about the left–right axis" },
  { axis: "y", text: "Tip sideways", title: "A quarter turn about the front–back axis" },
  { axis: "z", text: "Spin", title: "A quarter turn about the up axis: the same faces down, turned on the plate" },
];

export function OrientPanel({ recheck, canRecheck }: { recheck: (orientation: string | null) => void; canRecheck: boolean }) {
  const p = usePart();
  const fx = useFix();
  const key = p.data.key;
  const st = useOrient(key);
  const shown = useShown();
  const units = p.data.validation?.source_units?.declared === "inch" ? "inch" : "mm";
  const process = processOf(p.sel?.code, p.sel?.members);
  const options0 = useOptions(st ? key : null, units, null, false);
  const o0 = options0.s === "ready" ? options0.o : null;
  const needPicked = !!st?.picked && !!o0 && !candidateFor(o0, st.target);
  const options1 = useOptions(st && needPicked ? key : null, units, st?.picked ?? null, true);
  const opts = needPicked && options1.s === "ready" ? options1.o : o0;
  const rules = opts?.rules ?? null;

  // The 3D view colours what the check's rule marks for the selected method.
  // FDM bridges flat spans between walls: the engine says where, per way, and those stay uncoloured.
  const shade = shadeFor(process, rules);
  const bridges = React.useMemo(
    () => (process === "fdm" && opts ? opts.candidates.filter((c) => c.support.fdm?.bridge_boxes?.length).map((c) => ({ r: candidateMat(c), boxes: c.support.fdm.bridge_boxes! })) : []),
    [process, opts],
  );
  const shadeKey = shade ? `${shade.kind}${shade.deg}|${bridges.map((b) => `${b.r.join(",")}:${b.boxes.length}`).join(";")}` : "";
  React.useEffect(() => {
    if (!st) return;
    patchOrient({ shade: shade ? { ...shade, bridges, color: shade.kind === "overhang" ? KIND_COLOR.support : KIND_COLOR.draft } : null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!st, shadeKey]);

  // Another lens, or find and fix, closes it.
  const lensRef = React.useRef(p.lens);
  React.useEffect(() => {
    if (st && p.lens !== "make" && lensRef.current === "make") closeOrient();
    lensRef.current = p.lens;
  }, [p.lens, st]);
  React.useEffect(() => {
    if (st && fx.view) closeOrient();
  }, [fx.view, st]);

  // The re-check's own progress panel would cover this sheet: it says the same here.
  const rc = st?.recheck ?? null;
  const s = rc && p.session && p.session.startedAt >= rc.startedAt - 100 ? p.session : null;
  const hid = React.useRef<number | null>(null);
  React.useEffect(() => {
    if (s && hid.current !== s.id) {
      hid.current = s.id;
      setPanel(s.id, false);
    }
  }, [s]);

  if (!st || !key) return null;

  const go = (target: Mat) => {
    const startedAt = Date.now();
    patchOrient({ recheck: { startedAt, before: { validation: p.data.validation, cost: p.data.cost, rotation: shown }, rotation: target }, showing: "now" });
    recheck(orientationParam(target));
  };

  if (rc) return <Rechecked rc={rc} running={!s || s.status === "running"} failed={!!s && s.status !== "running" && s.status !== "done"} onBack={() => go(rc.before.rotation)} canRecheck={canRecheck} options={opts} />;

  const target = st.target;
  const here = candidateFor(opts, target);
  const ranked = rankedFor(opts, process);
  const best = process && opts ? opts.best[process] ?? null : null;
  const facts = here ? candidateFacts(here, process, rules, opts) : null;
  const flags = here ? flagWords(here, process) : "";
  const atShown = same(target, shown);
  const pickedName = st.picked && here?.basis === "picked" ? "On the face you picked" : null;
  return (
    <aside className="sheet or-sheet" aria-label="Orientation">
      <div className="top">
        <div className="or-row1">
          <h2 className="stitle">Orientation</h2>
          <button className="btn sm" type="button" onClick={closeOrient}>
            Done
          </button>
        </div>
        <p className="smeta">
          This check: {isIdentity(shown) ? "as in the file" : `the file's ${upWord(shown)} up`}. Up is the build direction for printing and the direction the tool opens for molding and casting.
        </p>
      </div>
      <div className="scroll">
        <p className="or-why">{whyLine(process, rules)}</p>

        <div className="gh">
          <span>Turn it</span>
          <span>{pickedName ?? label(target)}</span>
        </div>
        <div className="or-turns">
          {TURNS.map((t) => (
            <button key={t.axis} className="btn sm" type="button" title={t.title} onClick={() => patchOrient({ target: turned(target, t.axis), picked: null })}>
              {t.text}
            </button>
          ))}
          <button className="btn sm ghost" type="button" disabled={isIdentity(target)} onClick={() => patchOrient({ target: [...IDENTITY], picked: null })}>
            As in the file
          </button>
        </div>
        <p className="or-hint">
          {p.has3d ? "Or click a face on the part to lay it on that face. " : ""}
          {shade ? (
            <>
              <i className="or-sw" style={{ background: shade.kind === "overhang" ? KIND_COLOR.support : KIND_COLOR.draft }} aria-hidden="true" />
              {shade.kind === "overhang" ? `Coloured: faces needing support (overhang past ${trimNum(shade.deg, 0)}°).` : `Coloured: walls with less than ${trimNum(shade.deg, 0)}° of draft.`}
              {shade.kind === "overhang" && process && here?.support[process]?.bridges ? " Flat spans between walls bridge and aren't coloured." : ""}
            </>
          ) : null}
        </p>

        <div className="gh">
          <span>Ways to lay it down</span>
          <span>{process ? processLabel(process) : ""}</span>
        </div>
        {options0.s === "loading" ? (
          <p className="or-hint" role="status">
            Comparing the six sides and the largest flat faces…
          </p>
        ) : options0.s === "none" ? (
          <p className="or-hint">{options0.why}</p>
        ) : (
          ranked.map((c) => <Way key={c.id} c={c} process={process} options={opts} on={same(candidateMat(c), target) || (!!here && here.id === c.id && c.basis !== "side")} best={best === c.id} checked={same(candidateMat(c), shown)} onPick={() => patchOrient({ target: candidateMat(c), picked: null })} />)
        )}
        {opts ? (
          <p className="or-hint">
            {process && rules?.[process] ? (rules[process].overhang_deg != null ? opts.ranking.printing : opts.ranking.molding) + " " : ""}
            {opts.limits.slice(1).join(" ")}
          </p>
        ) : null}

        <div className="note or-go">
          <b>{pickedName ?? (isIdentity(target) ? "As in the file" : label(target))}</b>
          <span>{facts ? [facts.main, facts.sub].filter(Boolean).join(" · ") : options0.s === "loading" ? "Measuring…" : "Re-check to measure it this way."}</span>
          {here && process ? <span>{flags ? `Findings this way: ${flags}.` : "None of the findings that depend on orientation, this way."}</span> : null}
          <span>{priceBasis(opts) ?? PRICES_LINE}</span>
          {canRecheck ? (
            <span className="or-actions">
              <button className="btn ink sm" type="button" disabled={atShown || p.checking} onClick={() => go(target)}>
                Re-check in this orientation
              </button>
              <small>{atShown ? "This is how the shown check placed it." : "Same file, no extra check. Findings, methods and prices update together."}</small>
            </span>
          ) : (
            <span className="or-actions">
              <button className="btn sm" type="button" onClick={p.pickFile}>
                Choose the file
              </button>
              <small>To re-check it this way, choose the part&apos;s file. It must be the same file, and it doesn&apos;t use a check.</small>
            </span>
          )}
        </div>
      </div>
    </aside>
  );
}

function Way({ c, process, options, on, best, checked, onPick }: { c: Candidate; process: string | null; options: Options | null; on: boolean; best: boolean; checked: boolean; onPick: () => void }) {
  const f = candidateFacts(c, process, options?.rules ?? null, options);
  return (
    <button type="button" className={cx("mr or-way", on && "on")} aria-pressed={on} onClick={onPick}>
      <span>
        <b>{candidateName(c)}</b>
        <small>{[f.main, f.sub].filter(Boolean).join(" · ")}</small>
      </span>
      <span className="or-tags">
        {best ? (
          <span className="chip c-ok">
            <i />
            Best for {process ? processLabel(process).replace(/ \(.*\)$/, "") : "this"}
          </span>
        ) : null}
        {checked ? <span className="chip or-now">This check</span> : null}
      </span>
    </button>
  );
}

function Rechecked({ rc, running, failed, onBack, canRecheck, options }: { rc: OrientRecheck; running: boolean; failed: boolean; onBack: () => void; canRecheck: boolean; options: Options | null }) {
  const p = usePart();
  const st = useOrient(p.data.key);
  const process = processOf(p.sel?.code, p.sel?.members);
  const nowRot = matOf(recordOf(p.data.validation));
  const before = rc.before;
  const cmp = React.useMemo(
    () => (!running && !failed && p.data.validation ? compare(before, { validation: p.data.validation, cost: p.data.cost, rotation: nowRot }, p.q, process, p.data.machines, options) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [running, failed, p.data.validation, p.data.cost, p.q, process, p.data.machines, before, options],
  );
  if (running) {
    const v = p.session?.validation ?? null;
    return (
      <aside className="sheet or-sheet" aria-label="Re-checking">
        <div className="top">
          <h2 className="stitle">Re-checking</h2>
          <p className="smeta">{label(rc.rotation)} · same file, no new check</p>
        </div>
        <ol className="or-steps" role="status" aria-live="polite">
          <li className={v ? "done" : "now"}>
            <span className="m" aria-hidden="true">{v ? "✓" : ""}</span>
            <span>
              <b>Findings in this orientation</b>
              <span>{v ? "Measured" : "Measuring the turned part…"}</span>
            </span>
          </li>
          <li className={v ? "now" : ""}>
            <span className="m" aria-hidden="true" />
            <span>
              <b>Prices</b>
              <span>Every method, at the same quantities</span>
            </span>
          </li>
        </ol>
      </aside>
    );
  }
  const wrong = !failed && !same(nowRot, rc.rotation);
  if (failed || !cmp || wrong) {
    const msg = wrong
      ? "The re-check came back without the orientation asked for, so there's nothing to compare. The part page shows that re-check."
      : p.session?.failure && "message" in p.session.failure
        ? p.session.failure.message
        : p.session?.failure && "detail" in p.session.failure
          ? p.session.failure.detail
          : p.data.costError ?? "The re-check didn't finish.";
    return (
      <aside className="sheet or-sheet" aria-label="Re-check">
        <div className="top">
          <h2 className="stitle">The re-check didn&apos;t finish</h2>
          <p className="smeta">The answer from before is unchanged.</p>
        </div>
        <div className="scroll">
          <p className="or-err" role="alert">
            {msg}
          </p>
          <div className="or-actions" style={{ padding: "6px 12px" }}>
            <button className="btn sm" type="button" onClick={() => patchOrient({ recheck: null })}>
              Back to orientation
            </button>
          </div>
        </div>
      </aside>
    );
  }
  const showing = st?.showing ?? "now";
  return (
    <aside className="sheet or-sheet" aria-label="Re-checked">
      <div className="top">
        <div className="or-row1">
          <span className="seg" role="group" aria-label="Compare">
            <button type="button" className={cx(showing === "before" && "on")} aria-pressed={showing === "before"} onClick={() => patchOrient({ showing: "before" })}>
              Before
            </button>
            <button type="button" className={cx(showing === "now" && "on")} aria-pressed={showing === "now"} onClick={() => patchOrient({ showing: "now" })}>
              Now
            </button>
          </span>
          <button className="btn sm" type="button" onClick={closeOrient}>
            Done
          </button>
        </div>
        <h2 className="stitle" style={{ marginTop: 10 }}>
          Re-checked: {isIdentity(nowRot) ? "as in the file" : `the file's ${upWord(nowRot)} up`}
        </h2>
        <p className="smeta">Same file, no new check · the 3D view shows {showing === "before" ? "how it was checked before" : "how it is checked now"}</p>
      </div>
      <div className="scroll">
        <div className="gh">
          <span>What changed</span>
          <span>{process ? processLabel(process) : ""}</span>
        </div>
        <div className="or-chg">
          <div className="r">
            <span />
            <span>Before</span>
            <span style={{ textAlign: "right" }}>Now</span>
          </div>
          {cmp.rows.map((r, i) => (
            <div className="r" key={`${i}:${r.what}`}>
              <span>{r.what}</span>
              <span className="b num">{r.before}</span>
              <span className={cx("a num", r.tone)}>{r.now}</span>
            </div>
          ))}
        </div>
        {cmp.findings.cleared.length || cmp.findings.added.length ? (
          <>
            <div className="gh">
              <span>Findings{process ? ` for ${processLabel(process)}` : ""}</span>
              <span>
                {cmp.findings.cleared.length} gone · {cmp.findings.added.length} new
              </span>
            </div>
            <ul className="or-list">
              {cmp.findings.cleared.map((t, i) => (
                <li key={`c${i}`}>
                  <span className="chip c-ok">
                    <i />
                    Gone
                  </span>
                  <span>{t}</span>
                </li>
              ))}
              {cmp.findings.added.map((t, i) => (
                <li key={`a${i}`}>
                  <span className="chip c-bad">
                    <i />
                    New
                  </span>
                  <span>{t}</span>
                </li>
              ))}
            </ul>
          </>
        ) : process ? (
          <p className="or-hint">No finding for {processLabel(process)} appeared or went away.</p>
        ) : null}
        {cmp.methods.changed.length ? (
          <>
            <div className="gh">
              <span>Methods</span>
              <span>{cmp.methods.changed.length} changed</span>
            </div>
            <ul className="or-list">
              {cmp.methods.changed.map((m) => (
                <li key={m.name}>
                  <span className={cx("chip", m.tone === "ok" ? "c-ok" : m.tone === "bad" ? "c-bad" : "c-warn")}>
                    <i />
                    {m.now}
                  </span>
                  <span>
                    {m.name}, was {m.before.toLowerCase()}
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : null}
        <p className="or-hint">
          {cmp.pricesSame
            ? priceBasis(options) ?? PRICES_LINE
            : `Prices changed for ${cmp.pricesChanged.map((c) => processLabel(c)).join(", ")}; the Cost view shows them at ${qtyWord(p.q)} and the other quantities.`}
          {notComparedWords(cmp.pricesNotCompared) ? ` ${notComparedWords(cmp.pricesNotCompared)}` : ""}
        </p>
        <div className="or-actions" style={{ padding: "10px 12px 4px" }}>
          <button className="btn ink sm" type="button" onClick={closeOrient}>
            Keep this orientation
          </button>
          {canRecheck ? (
            <button className="btn sm" type="button" onClick={onBack}>
              Back to {isIdentity(before.rotation) ? "the file's own" : `the file's ${upWord(before.rotation)} up`}
            </button>
          ) : null}
        </div>
      </div>
    </aside>
  );
}
