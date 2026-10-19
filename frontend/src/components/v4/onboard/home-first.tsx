"use client";

/**
 * N5: Home before any part, and just after.
 *
 * First visit: three ways to a real answer, side by side: your own file (drop
 * or choose), the sample bracket, or a simple part from Design Studio, with
 * the six setup steps on the right (all optional, most locked until a part is
 * checked).
 *
 * Back with a part or two: "Pick up where you left off" names the next step
 * that makes the answers about this shop (add machines, re-check, your labor
 * rate), with the recent records and the three ways again. The setup sheet
 * stays until every step is done or it's dismissed; then Home is the usual one.
 */
import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { fetchCostDecision, type CostDecisionDetail } from "@/lib/api";
import { useAuth } from "@/components/ui/auth-provider";
import { sampleBracketFile } from "@/lib/verify/sample-cad";
import { CAD_ACCEPT, setPendingFile } from "../pending-file";
import { R } from "../routes";
import { useShell } from "../shell";
import { cx } from "../ui";
import { Frame, Column, Head } from "../home/frame";
import { PartialAlert, Skeleton } from "../home/states";
import { PartThumb } from "../home/thumb";
import { refusal } from "../home/drop";
import { recentRows, yoursOf, type HomeInput } from "../home/home-derive";
import * as api from "../home/data";
import { firstSteps, homeMode, materialWord, ranOnMachines, resumeCard, type FirstStep, type HomeMode } from "./first-run";
import { checkedBefore } from "./checked";
import { readSetupDismissed, writeSetupDismissed } from "./state";
import "../home/home.css";
import "./onboard.css";

/** Home's first-run mode for the signed-in person (N5), from Home's own loaded data, and a way to dismiss it. */
export function useFirstHomeMode(input: HomeInput): { mode: HomeMode; dismiss?: () => void } {
  const { user } = useAuth();
  const uid = user?.id ?? null;
  const [dismissed, setDismissed] = React.useState<boolean | null>(null);
  React.useEffect(() => {
    setDismissed(readSetupDismissed(uid));
  }, [uid]);
  const dismiss = React.useCallback(() => {
    if (uid == null) return;
    writeSetupDismissed(uid, true);
    setDismissed(true);
  }, [uid]);
  const mode: HomeMode = dismissed == null ? (input.records == null ? "loading" : input.records.length === 0 ? "first" : "loading") : homeMode({ records: input.records?.length ?? null, parts: input.partsTotal, dismissed });
  return { mode, dismiss: uid != null ? dismiss : undefined };
}

type Extra = { org: string | null; members: number | null; inProgram: number | null; latest: CostDecisionDetail | null; latestFailed: boolean; sampleRun: boolean | null };

function useExtra(input: HomeInput, mode: HomeMode) {
  const [x, setX] = React.useState<Extra>({ org: null, members: null, inProgram: null, latest: null, latestFailed: false, sampleRun: null });
  const [membersFailed, setMembersFailed] = React.useState(false);
  const newest = input.records?.[0]?.id ?? null;
  React.useEffect(() => {
    let live = true;
    api.org().then((o) => live && setX((c) => ({ ...c, org: o.name })), () => undefined);
    api.members().then(
      (m) => live && setX((c) => ({ ...c, members: m.filter((r) => r.is_active).length })),
      () => live && setMembersFailed(true),
    );
    // Same cached read as Home's programs line: parts in a program.
    api.portfolio().then((p) => live && setX((c) => ({ ...c, inProgram: api.programFacts(p).inProgram })), () => undefined);
    void checkedBefore(sampleBracketFile()).then((v) => live && setX((c) => ({ ...c, sampleRun: v })));
    return () => {
      live = false;
    };
  }, []);
  React.useEffect(() => {
    if (mode !== "back" || !newest) return;
    let live = true;
    fetchCostDecision(newest).then(
      (d) => live && setX((c) => ({ ...c, latest: d, latestFailed: false })),
      () => live && setX((c) => ({ ...c, latestFailed: true })),
    );
    return () => {
      live = false;
    };
  }, [mode, newest]);
  return { ...x, membersFailed };
}

export function FirstHome({
  mode,
  input,
  failed,
  pending,
  retry,
  openGuide,
  runSample,
  overlay,
  onDismiss,
}: {
  mode: "first" | "back";
  input: HomeInput;
  failed: Set<string>;
  pending: Set<string>;
  retry: () => void;
  openGuide: () => void;
  runSample: () => void;
  overlay: React.ReactNode;
  onDismiss?: () => void;
}) {
  const { usage, pickFile } = useShell();
  const headRef = React.useRef<HTMLDivElement>(null);
  const x = useExtra(input, mode);

  const latest = x.latest;
  const cost = latest?.result ?? null;
  const key = latest?.mesh_hash ?? input.records?.[0]?.mesh_hash ?? null;
  const file = latest?.filename ?? input.records?.[0]?.filename ?? null;
  const partHref = key ? R.part(key) : R.parts;
  const addHref = key ? `${R.part(key)}?shop=add` : `${R.shop}?add=1`;
  const onMachines = ranOnMachines(cost);
  const nMachines = input.machines ? input.machines.reduce((n, m) => n + (m.count ?? 1), 0) : null;
  const labor = cost?.assumptions?.find((a) => a.name === "labor_rate")?.value ?? null;

  const steps = firstSteps({
    records: input.records?.length ?? null,
    parts: input.partsTotal,
    part: file && key ? { file, material: cost ? materialWord(cost.material_class) : null, onMachines, href: partHref } : null,
    machines: input.machines,
    rates: input.rates,
    yours: yoursOf(input.posture),
    labor,
    programs: input.programs != null ? { programs: input.programs, notIn: input.partsTotal != null && x.inProgram != null ? Math.max(0, input.partsTotal - x.inProgram) : null } : null,
    actuals: input.actuals,
    members: x.members,
    failed: { records: failed.has("records"), machines: failed.has("machines"), rates: failed.has("rates"), programs: failed.has("portfolio"), actuals: failed.has("actuals"), members: x.membersFailed },
    hrefs: { check: R.check, shop: R.shop, rates: R.rates, programs: R.programs, actuals: R.actuals, team: R.org, addMachines: addHref },
  });
  const done = steps.filter((s) => s.tone === "done").length;
  const resume = mode === "back" && file && key ? resumeCard({ file, partHref, cost, machines: nMachines, onMachines, hrefs: { addMachines: addHref, rates: R.rates, recheck: `${partHref}?lens=shop` } }) : null;

  const left = usage ? (usage.unlimited ? null : usage.remaining) : null;
  const checksFact = !usage ? null : usage.unlimited ? "Pilot plan · checks aren’t capped" : `${usage.remaining} ${usage.plan === "pro" ? "Pro" : "free"} ${usage.remaining === 1 ? "check" : "checks"}${mode === "back" ? " left" : ""}`;
  const usesOne = !usage || usage.unlimited ? "Uses 1 check" : `Uses 1 of ${usage.remaining} ${usage.plan === "pro" ? "Pro" : "free"} checks`;
  const facts = [
    x.org,
    mode === "back" && input.partsTotal != null ? `${input.partsTotal} ${input.partsTotal === 1 ? "part" : "parts"}` : null,
    mode === "back" && input.records ? `${input.records.length}${input.recordsMore ? "+" : ""} ${input.records.length === 1 ? "record" : "records"}` : null,
    checksFact,
    nMachines == null ? null : nMachines ? `${nMachines} ${nMachines === 1 ? "machine" : "machines"}` : mode === "first" ? "No machines yet" : "No machines",
    input.rates ? `Rates: ${input.rates.using_governed ? "your rate card" : "Default v0, typical"}` : null,
  ].filter((f): f is string => Boolean(f));

  const missing = [...failed].filter((s) => ["records", "parts", "machines", "rates"].includes(s));
  const foot = mode === "first" ? "All optional. Without them, answers use typical machines and rates and say so." : nMachines ? "Picks up here each visit until every step is done or dismissed." : "Skipped steps wait here. Nothing re-checks until you ask.";
  const recent = recentRows(input.records, new Date(), 3);
  const sampleSmall = x.sampleRun ? "Run before · runs again without a new check" : usesOne;

  return (
    <Frame label="Home">
      <Head ref={headRef}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
          <div style={{ minWidth: 0 }}>
            <h1 className="ptitle">Home</h1>
            <p className="pmeta" style={{ marginTop: 6 }}>
              {facts.map((f, i) => (
                <span key={i}>{f}</span>
              ))}
            </p>
          </div>
          <button type="button" className="btn ghost sm" onClick={openGuide}>
            Start here
          </button>
        </div>
      </Head>
      <Column head={headRef}>
        {missing.length ? (
          <section className="panel" aria-label="Some data didn't load">
            <PartialAlert missing={missing.map((m) => (m === "portfolio" ? "programs" : m))} rest={pending.size === 0 ? "Everything else on Home is complete." : undefined} onRetry={retry} />
          </section>
        ) : null}
        {mode === "first" ? (
          <div className="swap nb-first">
            <div className="nb-ways">
              <OwnPartWay usesOne={usesOne} />
              <section className="nb-way" aria-labelledby="nb-w2">
                <div className="pic">
                  <SampleArt />
                </div>
                <h2 id="nb-w2">The sample bracket</h2>
                <p>50 × 40 × 6 mm · STL · real engine, same answers as your parts</p>
                <small>{sampleSmall}</small>
                <span className="acts">
                  <button className="btn" type="button" onClick={runSample}>
                    Run the sample
                  </button>
                </span>
              </section>
              <section className="nb-way" aria-labelledby="nb-w3">
                <div className="pic">
                  <StudioArt />
                </div>
                <h2 id="nb-w3">A simple part</h2>
                <p>Design Studio: plate, bracket or enclosure · exports STEP</p>
                <small>Check it when it’s drawn: 1 check, like any part</small>
                <span className="acts">
                  <Link className="btn" href={R.studio}>
                    Open Design Studio
                  </Link>
                </span>
              </section>
            </div>
            <p className="nb-five">
              Every check answers <b>Make</b> how <b>Cost</b> how many <b>Use</b> where <b>Shop</b> your machines <b>Decide</b> what next
            </p>
          </div>
        ) : (
          <div className="swap nb-first">
            <section className="panel" aria-labelledby="nb-resume-t">
              <div className="ph">
                <h2 id="nb-resume-t">Pick up where you left off</h2>
                <span>{recent[0] ? `Last check ${recent[0].time}` : ""}</span>
              </div>
              {resume ? (
                <div className="nb-resume">
                  <PartThumb size={120} glyph={52} />
                  <div className="t">
                    <span className="k">{resume.k}</span>
                    <b>{resume.title}</b>
                    <p>{resume.text}</p>
                    <span className="pmeta">{resume.meta}</span>
                  </div>
                  <span className="acts">
                    <Link className="btn ink" href={resume.go.href}>
                      {resume.go.label}
                    </Link>
                    <Link className="btn ghost sm" href={resume.alt.href}>
                      {resume.alt.label}
                    </Link>
                  </span>
                </div>
              ) : x.latestFailed ? (
                <div className="nb-resume one">
                  <span className="t">
                    <b>{file}</b>
                    <p>The newest record didn’t load, so the next step isn’t known yet.</p>
                  </span>
                  <span className="acts">
                    <Link className="btn ink" href={partHref}>
                      Open the part
                    </Link>
                  </span>
                </div>
              ) : (
                <Skeleton rows={3} label="Loading where you left off" />
              )}
            </section>
            <section className="panel" aria-labelledby="nb-recent-t">
              <div className="ph">
                <h2 id="nb-recent-t">Recent records</h2>
                <span>
                  <Link href={R.records}>All {input.records?.length ?? 0}{input.recordsMore ? "+" : ""}</Link>
                </span>
              </div>
              <div style={{ padding: "0 6px 8px" }} role="list" aria-label="Recent records">
                {recent.map((r) => (
                  <div role="listitem" key={r.id}>
                    <Link className="h-rr" href={r.href}>
                      <span style={{ minWidth: 0 }}>
                        <b>{r.file}</b>
                        <small>{r.sub}</small>
                      </span>
                      <span className="h-t">{r.time}</span>
                    </Link>
                  </div>
                ))}
              </div>
            </section>
            <section className="panel" aria-labelledby="nb-start-t">
              <div className="ph">
                <h2 id="nb-start-t">Check another part</h2>
                <span>{left != null ? `${left} ${usage?.plan === "pro" ? "Pro" : "free"} ${left === 1 ? "check" : "checks"} left` : ""}</span>
              </div>
              <div className="nb-alt3">
                <button type="button" onClick={pickFile}>
                  <span>
                    Your own part<small>STEP, STL or IGES</small>
                  </span>
                  <i aria-hidden="true">→</i>
                </button>
                <button type="button" onClick={runSample}>
                  <span>
                    The sample bracket<small>50 × 40 × 6 mm</small>
                  </span>
                  <i aria-hidden="true">→</i>
                </button>
                <Link href={R.studio}>
                  <span>
                    A simple part<small>Design Studio</small>
                  </span>
                  <i aria-hidden="true">→</i>
                </Link>
              </div>
            </section>
          </div>
        )}
      </Column>
      <SetupSheet
        steps={steps}
        done={done}
        foot={foot}
        onDismiss={mode === "back" ? onDismiss : undefined}
      />
      {overlay}
    </Frame>
  );
}

const ROW: Record<FirstStep["tone"], string> = { done: "row done", part: "row part", warn: "row", unk: "row", lock: "row lock", bad: "row bad" };
const CHIP: Record<FirstStep["tone"], string> = { done: "chip c-ok", part: "chip c-warn", warn: "chip c-warn", unk: "chip c-unk", lock: "chip c-unk", bad: "chip c-bad" };

function SetupSheet({ steps, done, foot, onDismiss }: { steps: FirstStep[]; done: number; foot: string; onDismiss?: () => void }) {
  return (
    <aside className="sheet nb-setup" aria-label="Setup" style={{ bottom: 20 }}>
      <div className="top">
        <h2 className="stitle">Setup</h2>
        <p className="smeta">{done} of 6 done · optional</p>
        <div className="prog6" role="img" aria-label={`${done} of 6 setup steps done`}>
          {steps.map((s) => (
            <i key={s.key} className={s.tone === "done" ? "on" : s.tone === "part" ? "half" : ""} />
          ))}
        </div>
      </div>
      <div className="scroll">
        <ol className="steps">
          {steps.map((s, i) => (
            <li key={s.key} className={cx(ROW[s.tone], s.next && "next")}>
              <span className="n" aria-hidden="true">
                {s.tone === "done" ? "✓" : i + 1}
              </span>
              <span className="t">
                <span className="h">
                  <b>
                    {s.title}
                    {s.tone === "done" ? <span className="nb-sr"> (done)</span> : null}
                  </b>
                  <span className={CHIP[s.tone]}>
                    <i />
                    {s.chip}
                  </span>
                </span>
                <span>{s.detail}</span>
                {s.go ? (
                  <Link className={cx("btn sm gobtn", s.next && "ink")} href={s.go.href} aria-label={`${s.go.label}: ${s.title}`}>
                    {s.go.label}
                  </Link>
                ) : null}
              </span>
            </li>
          ))}
        </ol>
        <p className="nb-sfoot">{foot}</p>
        {onDismiss ? (
          <p className="nb-sfoot">
            <button className="h-link" type="button" onClick={onDismiss}>
              Dismiss setup
            </button>{" "}
            and show the usual Home. Search › Set up your organization opens it again.
          </p>
        ) : null}
      </div>
    </aside>
  );
}

const OK = /\.(step|stp|stl|iges|igs)$/i;

/** "Your own part": drop or choose one file; it checks right away and opens on its own page. */
function OwnPartWay({ usesOne }: { usesOne: string }) {
  const router = useRouter();
  const [drag, setDrag] = React.useState(false);
  const [msg, setMsg] = React.useState<{ kind: "bad" | "many" | "ok"; text: string } | null>(null);
  const take = (files: FileList | null | undefined) => {
    setDrag(false);
    if (!files || !files.length) return;
    if (files.length > 1) return setMsg({ kind: "many", text: `${files.length} files dropped. This takes one; Many parts takes a batch.` });
    const f = files[0];
    if (!OK.test(f.name)) return setMsg({ kind: "bad", text: refusal(f.name) });
    setMsg({ kind: "ok", text: `${f.name} · checking now` });
    setPendingFile(f);
    router.push(R.check);
  };
  const over = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    if (!drag) setDrag(true);
  };
  return (
    <section
      className={cx("nb-way drop", drag && "over")}
      aria-labelledby="nb-w1"
      onDragEnter={over}
      onDragOver={over}
      onDragLeave={(e) => {
        const next = e.relatedTarget as Node | null;
        if (next && e.currentTarget.contains(next)) return;
        setDrag(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        take(e.dataTransfer?.files);
      }}
      data-testid="home-drop"
    >
      <div className="pic">
        <span className="nb-dropmsg">
          <span className="ico">
            <svg width="22" height="22" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="M10 13V3.5M6 7.5l4-4 4 4M3.5 12.5v2.5a1.5 1.5 0 0 0 1.5 1.5h10a1.5 1.5 0 0 0 1.5-1.5v-2.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span>{drag ? "Drop to check it" : "Drop a part here. It checks right away and opens on its own page."}</span>
          {msg ? (
            <span className={msg.kind === "ok" ? "nb-ok" : "nb-msg"} role="status">
              {msg.text}
              {msg.kind === "many" ? (
                <>
                  {" "}
                  <Link href={R.many}>Check many</Link>
                </>
              ) : null}
            </span>
          ) : null}
        </span>
      </div>
      <h2 id="nb-w1">Your own part</h2>
      <p>STEP, STL or IGES · up to 200 MB · one file</p>
      <small>Visible to your team only · {usesOne.charAt(0).toLowerCase() + usesOne.slice(1)}</small>
      <span className="acts">
        <label className="btn ink nb-file">
          Choose file
          <input
            type="file"
            accept={CAD_ACCEPT}
            aria-label="Choose a CAD file to check"
            onChange={(e) => {
              take(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
      </span>
    </section>
  );
}

function SampleArt() {
  return (
    <svg viewBox="0 0 446 240" role="img" aria-label="The sample routing bracket, an L-shaped plate 50 by 40 by 6 millimetres">
      <polygon points="209.4,130.2 78.4,205.8 78.4,173.4 209.4,97.8" fill="#C9CDD3" stroke="#8E949C" strokeWidth="1" strokeLinejoin="round" />
      <polygon points="377.7,227.4 209.4,130.2 209.4,97.8 377.7,195.0" fill="#DADDE2" stroke="#8E949C" strokeWidth="1" strokeLinejoin="round" />
      <polygon points="78.4,205.8 12.9,168.0 12.9,135.6 78.4,173.4" fill="#DADDE2" stroke="#8E949C" strokeWidth="1" strokeLinejoin="round" />
      <polygon points="433.8,195.0 377.7,227.4 377.7,195.0 433.8,162.6" fill="#C9CDD3" stroke="#8E949C" strokeWidth="1" strokeLinejoin="round" />
      <polygon points="200.0,27.6 433.8,162.6 377.7,195.0 209.4,97.8 78.4,173.4 12.9,135.6" fill="#F4F5F7" stroke="#8E949C" strokeWidth="1" strokeLinejoin="round" />
    </svg>
  );
}

/** An open enclosure, the kind Design Studio draws, in the same flat style. */
function StudioArt() {
  return (
    <svg viewBox="0 0 300 220" role="img" aria-label="An open enclosure, a part Design Studio can draw">
      <polygon points="40,120 150,175 150,205 40,150" fill="#DADDE2" stroke="#8E949C" strokeWidth="1" strokeLinejoin="round" />
      <polygon points="150,175 260,120 260,150 150,205" fill="#C9CDD3" stroke="#8E949C" strokeWidth="1" strokeLinejoin="round" />
      <polygon points="40,120 150,65 260,120 150,175" fill="#F4F5F7" stroke="#8E949C" strokeWidth="1" strokeLinejoin="round" />
      <polygon points="62,120 150,76 238,120 150,164" fill="#E6E8EB" stroke="#A9AEB5" strokeWidth="1" strokeLinejoin="round" />
      <polygon points="62,120 150,164 150,150 76,113" fill="#D3D6DB" stroke="none" />
      <circle cx="96" cy="133" r="4" fill="#fff" stroke="#8E949C" />
      <circle cx="204" cy="133" r="4" fill="#fff" stroke="#8E949C" />
    </svg>
  );
}
