"use client";

/**
 * THE VERDICT WALK — the hero loop, wired to the real engine.
 *
 * Every number below is read off a real response (POST /validate, POST
 * /validate/cost, GET /machine-inventory) or is withheld. The dev-branch engine
 * does not surface a makeability `verification` block, so the envelope/materials
 * gates render the honest unknown/feature state — NEVER a fabricated verdict. The
 * walk stops honestly at a failed gate (geometry invalid → no downstream compute).
 */
import { useMemo, useState } from "react";
import { C, MONO, USD, NUM, procLabel, statusColor } from "@/lib/verify/tokens";
import type { VerifyResult } from "@/lib/verify/run";
import type { CostReport, CostComparison } from "@/lib/api";
import {
  parseAsk,
  computeCostAtQty,
  compareRoutesAtQty,
  compareSaved,
  NL_REFUSAL,
  NONDETERMINISTIC_REFUSAL,
  type CostAtQtyResult,
  type RouteCompareResult,
} from "@/lib/verify/ask";
import {
  driverViews,
  makeNowEstimate,
  toolingEstimate,
  nearestQty,
  fractionToQty,
  qtyToFraction,
  provenanceMix,
  type DriverView,
} from "@/lib/verify/derive";
import {
  verdictBannerModel,
  perRouteRows,
  envStrikes,
  marginalRate,
  acquisitionGap,
  gapText,
  type Tone,
  type VerificationBlock,
} from "@/lib/verify/verification";
import { envelopeSummary } from "@/lib/verify/machine-api";
import { Card, Kicker, ProvChip, ProvDot, InDev, ConfidenceBand, GhostButton, EmptyState, Spinner } from "./primitives";

/** Light status colour for a verdict/fit tone. */
function toneColor(t: Tone): string {
  return t === "pass" ? C.pass : t === "cond" ? C.cond : t === "fail" ? C.fail : C.ink45;
}

type Nav = (screen: string) => void;

interface Props {
  result: VerifyResult | null;
  running: boolean;
  fileName: string | null;
  env: { temp: boolean; sour: boolean; pressure: boolean };
  setEnv: (e: { temp: boolean; sour: boolean; pressure: boolean }) => void;
  onPickFile: () => void;
  onReverify: () => void;
  nav: Nav;
}

const ENV_CHIPS: { key: "temp" | "sour" | "pressure"; label: string }[] = [
  { key: "temp", label: "120 °C service" },
  { key: "sour", label: "sour service (H₂S)" },
  { key: "pressure", label: "35 MPa pressure" },
];

export function VerifyScreen(props: Props) {
  const { result, running, env, setEnv, onPickFile, onReverify, nav } = props;
  const [scrubFrac, setScrubFrac] = useState(0.5);
  const [disclose, setDisclose] = useState<string | null>(null);

  const hostile = env.temp || env.sour || env.pressure;
  // The env door tells the EXACT truth about the round-trip. `result` reflects the
  // world as it was actually persisted for the last run; before/while a run it
  // states intent, never a "captured" claim it can't back up.
  const door = envDoorStatus(hostile, running, result);

  return (
    <div
      style={{
        animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both",
        flex: 1,
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
        background: C.bg,
        minHeight: 0,
      }}
    >
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "26px 30px 30px" }}>
        {/* the question */}
        <p
          style={{
            margin: 0,
            fontSize: 17.5,
            fontWeight: 300,
            lineHeight: 1.45,
            letterSpacing: "-0.01em",
            color: C.ink70,
            maxWidth: 560,
          }}
        >
          Can this be made — <span style={{ fontWeight: 500, color: C.ink }}>on your machines</span>, in
          materials that survive its world — and what will it really take?
        </p>

        {/* environment door */}
        <section style={{ marginTop: 16, border: `1px solid ${C.hair}`, borderRadius: 16, background: C.panel, padding: "18px 20px" }}>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
            <Kicker>DECLARE ITS WORLD</Kicker>
            <span style={{ fontFamily: MONO, fontSize: 10.5, color: door.chipColor }}>{door.chip}</span>
          </div>
          <div style={{ marginTop: 14, display: "flex", flexWrap: "wrap", gap: 8 }}>
            {ENV_CHIPS.map((chip) => {
              const on = env[chip.key];
              return (
                <button
                  key={chip.key}
                  type="button"
                  onClick={() => setEnv({ ...env, [chip.key]: !on })}
                  style={{
                    border: on ? `1px solid ${C.ink}` : `1px solid ${C.hair}`,
                    background: on ? C.ink : "#ffffff",
                    color: on ? "#ffffff" : C.ink,
                    borderRadius: 999,
                    padding: "8px 16px",
                    fontSize: 12.5,
                    cursor: "pointer",
                    fontFamily: "inherit",
                    transition: "all 150ms",
                  }}
                >
                  {chip.label}
                </button>
              );
            })}
          </div>
          <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, color: door.color, lineHeight: 1.6 }}>
            {door.line}
          </p>
        </section>

        {/* the walk */}
        {running ? (
          <ComputingBanner />
        ) : !result ? (
          <DropPrompt onPickFile={onPickFile} />
        ) : (
          <Walk
            result={result}
            scrubFrac={scrubFrac}
            setScrubFrac={setScrubFrac}
            disclose={disclose}
            setDisclose={setDisclose}
            onReverify={onReverify}
            nav={nav}
          />
        )}
      </div>

      {/* ── ask the engine (docked) — structured asks only; NL is IN DEVELOPMENT ── */}
      <AskDock cost={result?.cost ?? null} running={running} nav={nav} />
    </div>
  );
}

/** The env door's exact-truth status. The "captured on the record" claim is made
 *  ONLY when the last run actually persisted the world (result.envCaptured); a
 *  failed persistence says exactly what is true ("drives this preview only"). */
function envDoorStatus(
  hostile: boolean,
  running: boolean,
  result: VerifyResult | null
): { chip: string; chipColor: string; line: string; color: string } {
  if (result && result.envDeclared) {
    if (result.envCaptured) {
      return {
        chip: "● USER · on the record",
        chipColor: C.user,
        line: "world declared — captured on this part's record (part-context, keyed to its mesh). The verification below reflects it: materials that can't survive this world are struck with their cited standard.",
        color: C.pass,
      };
    }
    return {
      chip: "drives this preview only",
      chipColor: C.cond,
      line:
        "world declared — drives this preview only, NOT captured to the record" +
        (result.envError ? ` (${result.envError})` : "") +
        ".",
      color: C.cond,
    };
  }
  if (result && !result.envDeclared) {
    return {
      chip: "ambient",
      chipColor: C.ink40,
      line: "no world declared — the part is verified in ambient conditions.",
      color: C.ink40,
    };
  }
  if (hostile) {
    return {
      chip: running ? "capturing…" : "captured on verify",
      chipColor: C.ink40,
      line: running
        ? "declaring this world on the part's record, then re-costing against it…"
        : "world declared — it will be captured on the part's record when you verify, and any material that can't survive it is struck with its cited standard.",
      color: C.cond,
    };
  }
  return {
    chip: "ambient",
    chipColor: C.ink40,
    line: "no world declared — the part will be verified in ambient conditions.",
    color: C.ink40,
  };
}

function ComputingBanner() {
  return (
    <div
      style={{
        marginTop: 18,
        border: `1.5px solid ${C.hair}`,
        borderRadius: 16,
        background: C.panel,
        padding: "22px 24px",
      }}
    >
      <Kicker color={C.ink45}>COMPUTING — GATES CHECKING IN</Kicker>
      <p style={{ margin: "10px 0 0", fontSize: 18, fontWeight: 300 }}>
        Running the part through routing, DFM, and the glass-box should-cost…
      </p>
      <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 6 }}>
        {["routing + DFM (POST /validate)", "should-cost record (POST /validate/cost)", "your declared floor (GET /machine-inventory)"].map(
          (t, i) => (
            <p
              key={t}
              style={{
                margin: 0,
                fontFamily: MONO,
                fontSize: 10.5,
                color: C.ink50,
                animation: `vtraceIn 400ms cubic-bezier(0.2,0,0,1) ${i * 180}ms both`,
              }}
            >
              ▸ {t}
            </p>
          )
        )}
      </div>
    </div>
  );
}

function DropPrompt({ onPickFile }: { onPickFile: () => void }) {
  return (
    <div style={{ marginTop: 18 }}>
      <EmptyState
        title="Drop a part to begin the walk."
        body="STEP or STL. It's parsed in-process and the mesh is discarded — the engine keeps the decision, never your CAD. Nothing on this page is shown until the engine computes it."
      >
        <GhostButton primary onClick={onPickFile}>
          Browse files
        </GhostButton>
      </EmptyState>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────── */

function StepShell({
  n,
  title,
  right,
  children,
  delayMs = 0,
}: {
  n: number;
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  delayMs?: number;
}) {
  return (
    <div
      style={{
        border: `1px solid ${C.hair}`,
        borderRadius: 14,
        background: C.panel,
        padding: "18px 20px",
        animation: `vstepIn 400ms cubic-bezier(0.2,0,0,1) ${delayMs}ms both`,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <span style={{ fontFamily: MONO, fontSize: 11, color: C.ink35 }}>{n}</span>
        <p style={{ margin: 0, fontSize: 15, fontWeight: 500 }}>{title}</p>
        {right && <span style={{ marginLeft: "auto", fontFamily: MONO, fontSize: 11, color: C.ink45 }}>{right}</span>}
      </div>
      {children}
    </div>
  );
}

function Walk({
  result,
  scrubFrac,
  setScrubFrac,
  disclose,
  setDisclose,
  onReverify,
  nav,
}: {
  result: VerifyResult;
  scrubFrac: number;
  setScrubFrac: (f: number) => void;
  disclose: string | null;
  setDisclose: (s: string | null) => void;
  onReverify: () => void;
  nav: Nav;
}) {
  const { cost, costGeometryInvalid, machines, verification } = result;

  const bbox: [number, number, number] | null = cost?.geometry?.bbox_mm ?? null;
  const makeNow = cost ? makeNowEstimate(cost) : null;
  const crossover = cost?.decision?.crossover_qty ?? null;

  const scrubQty = useMemo(() => fractionToQty(scrubFrac), [scrubFrac]);
  const snappedQty = useMemo(
    () => (cost ? nearestQty(cost.quantities, scrubQty) : scrubQty),
    [cost, scrubQty]
  );
  const makeAtQty = cost ? makeNowEstimate(cost, snappedQty) : null;
  const toolAtQty = cost ? toolingEstimate(cost, snappedQty) : null;

  const gateStopped = !!costGeometryInvalid;

  return (
    <section style={{ marginTop: 18 }}>
      {/* verdict banner */}
      <VerdictBanner result={result} makeNow={makeNow} nav={nav} />

      <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 12 }}>
        {/* 1 · envelope — from the real machine inventory (no faked fit) */}
        <StepShell
          n={1}
          title="Envelope — against your machines"
          right={`${machines.length} machine${machines.length === 1 ? "" : "s"} declared`}
          delayMs={40}
        >
          {machines.length === 0 ? (
            <div style={{ marginTop: 12 }}>
              <div style={{ border: "1.5px dashed #d3d3d8", borderRadius: 12, padding: "22px 20px", textAlign: "center" }}>
                <p style={{ margin: 0, fontSize: 14, fontWeight: 500 }}>No machines declared.</p>
                <p style={{ margin: "7px 0 0", fontSize: 12, lineHeight: 1.6, color: C.ink50 }}>
                  Your floor is the denominator of every makeability verdict. Declare it once — a CSV or five minutes of typing.
                </p>
                <div style={{ marginTop: 12 }}>
                  <GhostButton onClick={() => nav("machines")}>Declare your floor →</GhostButton>
                </div>
              </div>
            </div>
          ) : (
            <>
              <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                {machines.slice(0, 8).map((m) => {
                  const envSum = envelopeSummary(m);
                  return (
                    <div
                      key={m.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        fontFamily: MONO,
                        fontSize: 11.5,
                        padding: "7px 10px",
                        borderRadius: 8,
                        background: C.sunken,
                      }}
                    >
                      <ProvDot p="USER" size={6} />
                      <span style={{ color: C.ink, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {m.name || procLabel(m.process)}
                      </span>
                      <span style={{ marginLeft: "auto", color: C.ink40, whiteSpace: "nowrap" }}>{envSum ?? "envelope undeclared"}</span>
                    </div>
                  );
                })}
              </div>
              <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40, lineHeight: 1.6 }}>
                part envelope {bbox ? `${bbox.map((n) => n.toFixed(1)).join(" × ")} mm ` : "— "}
                <ProvChip p={bbox ? "MEASURED" : "DEFAULT"} />
                {!verification && (
                  <>
                    {" "}· per-machine fit is decided by the makeability verification{" "}
                    <InDev label="ENGINE BLOCK — NOT EVALUATED" /> — the floor is declared; no fit is faked here.
                  </>
                )}
              </p>
              {verification && <RouteFitBlock verification={verification} />}
            </>
          )}
        </StepShell>

        {/* honest gate stop */}
        {gateStopped && (
          <div
            style={{
              border: `1.5px dashed rgba(194,69,58,0.4)`,
              borderRadius: 14,
              padding: "16px 20px",
              animation: "vstepIn 400ms cubic-bezier(0.2,0,0,1) 120ms both",
            }}
          >
            <p style={{ margin: 0, fontFamily: MONO, fontSize: 11, letterSpacing: "0.1em", color: C.fail }}>
              THE WALK STOPS AT THE FAILED GATE
            </p>
            <p style={{ margin: "8px 0 0", fontSize: 13, lineHeight: 1.6, color: C.ink55 }}>
              {costGeometryInvalid?.message ||
                "Geometry is invalid — the engine will not guess."}{" "}
              Materials, physics, hours, and cost are not computed for a part the engine can&apos;t accept — and they are never faked to fill the page.
              {costGeometryInvalid?.geometry && (
                <>
                  {" "}
                  <span style={{ fontFamily: MONO, fontSize: 11, color: C.ink50 }}>
                    measured: {NUM(costGeometryInvalid.geometry.face_count)} faces ·{" "}
                    watertight {String(costGeometryInvalid.geometry.watertight)} ·{" "}
                    vol {costGeometryInvalid.geometry.volume_cm3.toFixed(2)} cm³
                  </span>
                </>
              )}
            </p>
            <div style={{ marginTop: 12 }}>
              <GhostButton onClick={onReverify}>Repair &amp; re-upload →</GhostButton>
            </div>
          </div>
        )}

        {/* downstream steps only when the engine got past the gate */}
        {!gateStopped && (
          <>
            {/* 2 · materials */}
            <StepShell n={2} title="Materials that survive this world" delayMs={120} right={cost?.material_class ?? undefined}>
              <div style={{ marginTop: 12 }}>
                {cost ? (
                  <p style={{ margin: 0, fontFamily: MONO, fontSize: 11.5, color: C.ink60, lineHeight: 1.7 }}>
                    material class <span style={{ color: C.ink }}>{cost.material_class}</span>
                    {cost.routing?.material_hint ? ` · route hint ${cost.routing.material_hint}` : ""}{" "}
                    <ProvChip p="DEFAULT" />
                  </p>
                ) : (
                  <p style={{ margin: 0, fontFamily: MONO, fontSize: 11.5, color: C.ink50 }}>material class withheld — costing unavailable</p>
                )}
                {verification ? (
                  <EnvStrikesBlock verification={verification} envDeclared={result.envDeclared} />
                ) : (
                  <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40, lineHeight: 1.6 }}>
                    environment-driven survival filtering (NACE MR0175 / HDT tables) is part of the makeability verification —{" "}
                    <InDev label="NOT EVALUATED — DECLARE A WORLD" />. Invalid materials are filtered out visibly, never silently.
                  </p>
                )}
              </div>
            </StepShell>

            {/* 3 · process physics — from /validate (real DFM + routing) */}
            <StepShell n={3} title="Process physics — geometry against each route" delayMs={200}>
              <ProcessPhysics result={result} />
            </StepShell>

            {/* 4 · what it really takes — from /validate/cost drivers */}
            {cost && makeNow && (
              <StepShell
                n={4}
                title="What it really takes"
                delayMs={280}
                right={`on ${procLabel(makeNow.process)} · ${makeNow.material}`}
              >
                <TimeAndResources est={makeNow} disclose={disclose} setDisclose={setDisclose} />
              </StepShell>
            )}

            {/* 5 · resource cost — crossover scrub from the real estimates */}
            {cost && (
              <StepShell n={5} title="Resource cost — yours, not a market's" delayMs={360}>
                <ResourceCost
                  cost={cost}
                  makeAtQty={makeAtQty}
                  toolAtQty={toolAtQty}
                  snappedQty={snappedQty}
                  scrubFrac={scrubFrac}
                  setScrubFrac={setScrubFrac}
                  crossover={crossover}
                  toolingProcess={cost.decision?.tooling_process ?? null}
                  makeProcess={cost.decision?.make_now_process ?? makeNow?.process ?? null}
                  verification={verification}
                  nav={nav}
                />
              </StepShell>
            )}

            {/* decide + hallmark */}
            {cost && <DecideHallmark result={result} nav={nav} />}
          </>
        )}

        {verification && (
          <Card style={{ borderColor: C.hair }}>
            <Kicker>
              MAKEABILITY — {verification.verdict.replace(/_/g, " ").toUpperCase()} · {(verification.provenance ?? "user").toUpperCase()}
            </Kicker>
            <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink50, lineHeight: 1.7 }}>
              inventory declared {String(!!verification.inventory_declared)} · environment declared {String(!!verification.environment_declared)}
              {verification.best_machine ? ` · best machine ${verification.best_machine}` : ""}
            </p>
            {verification.note && (
              <p style={{ margin: "8px 0 0", fontSize: 12, color: C.ink55, lineHeight: 1.6 }}>{verification.note}</p>
            )}
          </Card>
        )}
      </div>
    </section>
  );
}

function VerdictBanner({
  result,
  makeNow,
  nav,
}: {
  result: VerifyResult;
  makeNow: ReturnType<typeof makeNowEstimate>;
  nav: Nav;
}) {
  const { validation, cost, costGeometryInvalid, verification } = result;

  if (costGeometryInvalid) {
    return (
      <BannerFrame borderColor={C.fail} bg="rgba(194,69,58,0.03)">
        <Kicker color={C.fail}>VERDICT · GEOMETRY GATE</Kicker>
        <p style={{ margin: "10px 0 0", fontSize: 24, fontWeight: 400, letterSpacing: "-0.015em", lineHeight: 1.25 }}>
          Geometry invalid — the engine won&apos;t guess.
        </p>
        <p style={{ margin: "8px 0 0", fontSize: 14, lineHeight: 1.6, color: C.ink60, maxWidth: 560 }}>
          Nothing downstream is computed from broken geometry. Repair the mesh and re-upload to re-enter the walk.
        </p>
      </BannerFrame>
    );
  }

  const unit = makeNow?.unit_cost_usd ?? null;
  const proc = cost?.decision?.make_now_process ?? makeNow?.process ?? null;

  const savedCta = cost?.saved?.id ? (
    <div style={{ marginTop: 14 }}>
      <GhostButton primary onClick={() => nav("records")}>
        Open the record →
      </GhostButton>
    </div>
  ) : null;

  // When a makeability block is present, the VERDICT LATTICE drives the banner —
  // makeable_in_house / makeable_not_on_owned / environment_excluded / not_makeable
  // / unknown — never a DFM guess standing in for makeability.
  if (verification) {
    const m = verdictBannerModel(verification.verdict);
    const color = toneColor(m.tone);
    return (
      <BannerFrame borderColor={color} bg="rgba(23,24,26,0.015)">
        <Kicker color={color}>{m.kicker}</Kicker>
        <p style={{ margin: "10px 0 0", fontSize: 24, fontWeight: 400, letterSpacing: "-0.015em", lineHeight: 1.25 }}>
          {m.title}
        </p>
        <p style={{ margin: "8px 0 0", fontSize: 14, lineHeight: 1.6, color: C.ink60, maxWidth: 560 }}>{m.sub}</p>
        {proc && unit != null && (
          <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink50, lineHeight: 1.6 }}>
            should-cost {USD(unit)}/unit on {procLabel(proc)}
            {makeNow ? ` at qty ${NUM(makeNow.quantity)}` : ""}
            {verification.best_machine ? ` · best machine ${verification.best_machine}` : ""}
          </p>
        )}
        {savedCta}
      </BannerFrame>
    );
  }

  // No makeability block (no inventory + no declared world) → the honest DFM +
  // should-cost banner; the makeability gate is stated as not-evaluated, never assumed.
  const dfm = validation?.overall_verdict ?? "unknown";
  const color = statusColor(dfm);

  return (
    <BannerFrame borderColor={color} bg="rgba(23,24,26,0.015)">
      <Kicker color={color}>VERDICT · DFM {dfm.toUpperCase()} · SHOULD-COST COMPUTED</Kicker>
      <p style={{ margin: "10px 0 0", fontSize: 24, fontWeight: 400, letterSpacing: "-0.015em", lineHeight: 1.25 }}>
        {proc && unit != null ? (
          <>
            Should-cost {USD(unit)}/unit on {procLabel(proc)}
            {makeNow ? <span style={{ fontSize: 14, color: C.ink45 }}> at qty {NUM(makeNow.quantity)}</span> : null}
          </>
        ) : cost ? (
          <>Should-cost computed</>
        ) : (
          <>Routing &amp; DFM computed — should-cost unavailable</>
        )}
      </p>
      <p style={{ margin: "8px 0 0", fontSize: 14, lineHeight: 1.6, color: C.ink60, maxWidth: 560 }}>
        The engine returned routing, DFM, and a glass-box should-cost. Whether it&apos;s makeable{" "}
        <span style={{ fontWeight: 500 }}>on your machines</span> is the makeability verification — not evaluated here
        because no machines and no world are declared. Declare your floor or a world to resolve it, never assumed.
      </p>
      {savedCta}
    </BannerFrame>
  );
}

function BannerFrame({ children, borderColor, bg }: { children: React.ReactNode; borderColor: string; bg: string }) {
  return (
    <div
      style={{
        border: `1.5px solid ${borderColor}`,
        borderRadius: 16,
        background: bg,
        padding: "20px 22px",
        animation: "vstepIn 400ms cubic-bezier(0.2,0,0,1) both",
      }}
    >
      {children}
    </div>
  );
}

/** Per-machine envelope fit, rendered faithfully from the engine's verification
 *  block: ✓ pass / ✗ fail / ? unknown, and — for a failed or unknown gate — the
 *  concrete need-vs-have delta the engine measured (never a vague "too big"). */
function RouteFitBlock({ verification }: { verification: VerificationBlock }) {
  const rows = perRouteRows(verification);
  const gap = acquisitionGap(verification);
  if (rows.length === 0) {
    return (
      <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40, lineHeight: 1.6 }}>
        the engine evaluated your floor against this part but surfaced no per-route detail — no fit is faked here.
      </p>
    );
  }
  return (
    <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
      {rows.map((r) => {
        const detail =
          r.tone === "pass"
            ? r.bestMachine ?? `${r.machinesEvaluated} machine${r.machinesEvaluated === 1 ? "" : "s"} clear`
            : r.failures.length > 0
              ? `${r.failures[0].gate}: ${gapText(r.failures[0])}`
              : r.verdict.replace(/_/g, " ");
        return (
          <div
            key={r.process}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontFamily: MONO,
              fontSize: 11.5,
              padding: "7px 10px",
              borderRadius: 8,
              background: C.sunken,
            }}
          >
            <span style={{ color: toneColor(r.tone), width: 12, textAlign: "center", flexShrink: 0 }}>{r.glyph}</span>
            <span style={{ color: C.ink, whiteSpace: "nowrap" }}>{procLabel(r.process)}</span>
            <span style={{ marginLeft: "auto", color: r.tone === "pass" ? C.ink55 : C.ink45, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {detail}
            </span>
          </div>
        );
      })}
      {gap.length > 0 && (
        <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.cond, lineHeight: 1.6 }}>
          acquisition gap · {gap.map((f) => `${f.axis || f.gate} ${gapText(f)}`).join(" · ")}{" "}
          <span style={{ color: C.ink40 }}>— what you&apos;d acquire to make this in-house</span>
        </p>
      )}
      <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40, lineHeight: 1.6 }}>
        machine fit is a <span style={{ color: C.measured }}>MEASURED</span>-geometry × <span style={{ color: C.user }}>USER</span>-declared-capability comparison — ? when a capability is undeclared, never a fabricated pass.
      </p>
    </div>
  );
}

/** The declared world's material strikes, each citing the property/standard that
 *  ruled it out (e.g. NACE MR0175 under sour service). Excluded materials are shown
 *  struck, never dropped silently; an absence of strikes is stated honestly too. */
function EnvStrikesBlock({ verification, envDeclared }: { verification: VerificationBlock; envDeclared: boolean }) {
  const strikes = envStrikes(verification);
  const worldDeclared = envDeclared || !!verification.environment_declared;
  if (strikes.length === 0) {
    return (
      <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40, lineHeight: 1.6 }}>
        {worldDeclared
          ? "the declared world was applied — no candidate material on the shortlisted routes is excluded by it."
          : "no world declared — materials are verified in ambient conditions. Declare a world above to gate them by NACE MR0175 / HDT."}
      </p>
    );
  }
  return (
    <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
      {strikes.map((s) => (
        <div key={s.material} style={{ display: "flex", alignItems: "baseline", gap: 8, fontFamily: MONO, fontSize: 11 }}>
          <span style={{ color: C.fail, textDecoration: "line-through", whiteSpace: "nowrap", flexShrink: 0 }}>{s.material}</span>
          <span style={{ color: C.ink55, lineHeight: 1.5 }}>{s.reason}</span>
        </div>
      ))}
      <p style={{ margin: "4px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40, lineHeight: 1.6 }}>
        excluded materials are struck visibly, never dropped silently — each cites the property / standard, and the decision below is computed over the survivors.
      </p>
    </div>
  );
}

function ProcessPhysics({ result }: { result: VerifyResult }) {
  const v = result.validation;
  if (!v) {
    return (
      <p style={{ marginTop: 12, fontFamily: MONO, fontSize: 11, color: C.ink50 }}>
        routing/DFM unavailable{result.validationError ? ` — ${result.validationError}` : ""} · withheld, never faked
      </p>
    );
  }
  const rows = [...v.process_scores].sort((a, b) => b.score - a.score).slice(0, 6);
  return (
    <div style={{ marginTop: 12, display: "flex", flexDirection: "column" }}>
      {rows.map((ps) => {
        const isPick = ps.process === v.best_process;
        const errCount = ps.issues.filter((i) => i.severity === "error").length;
        return (
          <div
            key={ps.process}
            style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 2px", borderBottom: `1px solid #efeff2` }}
          >
            <span style={{ fontSize: 13, color: C.ink, flex: 1 }}>
              {procLabel(ps.process)}
              {isPick && (
                <span style={{ marginLeft: 8, fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.08em", color: C.measured }}>
                  ROUTE PICK
                </span>
              )}
            </span>
            {errCount > 0 && (
              <span style={{ fontFamily: MONO, fontSize: 10.5, color: C.cond }}>
                {errCount} blocker{errCount === 1 ? "" : "s"}
              </span>
            )}
            <span
              style={{
                fontFamily: MONO,
                fontSize: 10,
                letterSpacing: "0.06em",
                border: `1px solid ${statusColor(ps.verdict)}`,
                color: statusColor(ps.verdict),
                borderRadius: 4,
                padding: "2px 8px",
                flexShrink: 0,
              }}
            >
              {ps.verdict}
            </span>
          </div>
        );
      })}
      <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40 }}>
        {v.priority_fixes.length} priority fix{v.priority_fixes.length === 1 ? "" : "es"} across routes ·{" "}
        overall {v.overall_verdict} · rendered from POST /validate
      </p>
    </div>
  );
}

function TimeAndResources({
  est,
  disclose,
  setDisclose,
}: {
  est: NonNullable<ReturnType<typeof makeNowEstimate>>;
  disclose: string | null;
  setDisclose: (s: string | null) => void;
}) {
  const drivers = driverViews(est);
  const active = drivers.find((d) => d.name === disclose) ?? null;
  const lead = est.lead_time;
  return (
    <>
      <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 10 }}>
        {drivers.map((d) => (
          <button
            key={d.name}
            type="button"
            onClick={() => setDisclose(disclose === d.name ? null : d.name)}
            style={{
              textAlign: "left",
              cursor: "pointer",
              fontFamily: "inherit",
              color: "inherit",
              background: "none",
              border: `1px solid ${disclose === d.name ? C.ink : C.hair}`,
              borderRadius: 10,
              padding: "12px 14px",
              transition: "border-color 150ms",
            }}
          >
            <p style={{ margin: 0, display: "flex", justifyContent: "space-between", gap: 8, fontFamily: MONO, fontSize: 10, letterSpacing: "0.08em", color: C.ink40 }}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.label.toUpperCase()}</span>
              <ProvChip p={d.provenance} />
            </p>
            <p style={{ margin: "6px 0 0", fontSize: 18, fontWeight: 400 }}>
              {formatDriverValue(d)}{" "}
              <span style={{ fontSize: 12, color: C.ink45 }}>{driverUnit(d)}</span>
            </p>
          </button>
        ))}
      </div>

      {active && (
        <div
          style={{
            marginTop: 10,
            border: `1px solid ${C.ink}`,
            borderRadius: 10,
            padding: "14px 16px",
            background: "#fafafb",
            animation: "vstepIn 250ms cubic-bezier(0.2,0,0,1) both",
          }}
        >
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <p style={{ margin: 0, fontFamily: MONO, fontSize: 12, color: C.ink }}>{active.label}</p>
            <ProvChip p={active.provenance} />
            <button
              type="button"
              onClick={() => setDisclose(null)}
              style={{ marginLeft: "auto", background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 11, color: C.ink40 }}
            >
              ✕
            </button>
          </div>
          <p style={{ margin: "9px 0 0", fontFamily: MONO, fontSize: 10.5, lineHeight: 1.7, color: C.ink55 }}>
            source: {active.source || "— (engine did not attach a derivation string)"}
          </p>
          <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink40, lineHeight: 1.6 }}>
            this engine build carries one derivation string per driver — the formula IS the source above; there are no separate formula/chain rows to render.
          </p>
          {active.errorBandPct != null && (
            <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10, color: C.cond }}>
              ±{Math.round(active.errorBandPct)}% [assumption band] · this driver&apos;s honest error, verbatim
            </p>
          )}
        </div>
      )}

      <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40, lineHeight: 1.7 }}>
        lead {lead.low_days.toFixed(1)}–{lead.high_days.toFixed(1)} days{" "}
        <span style={{ color: C.def }}>[queue model — not your scheduler]</span> · computed hours are ○ MODEL from an
        assumption at SHOP rates — tap any driver for its verbatim derivation.
      </p>
    </>
  );
}

function ResourceCost({
  cost,
  makeAtQty,
  toolAtQty,
  snappedQty,
  scrubFrac,
  setScrubFrac,
  crossover,
  toolingProcess,
  makeProcess,
  verification,
  nav,
}: {
  cost: NonNullable<VerifyResult["cost"]>;
  makeAtQty: ReturnType<typeof makeNowEstimate>;
  toolAtQty: ReturnType<typeof toolingEstimate>;
  snappedQty: number;
  scrubFrac: number;
  setScrubFrac: (f: number) => void;
  crossover: number | null;
  toolingProcess: string | null;
  makeProcess: string | null;
  verification: VerificationBlock | null;
  nav: Nav;
}) {
  // The machine-specific MARGINAL rate: when a PASSING owned machine re-costs this
  // route at its OWN declared rate, the header reads OWNED → MARGINAL and names the
  // machine + rate (SHOP provenance). Absent → the generic MAKE NOW header.
  const marginal = marginalRate(verification, makeProcess);
  const conf = makeAtQty?.confidence;
  const validated = conf?.validated ?? false;
  // real tick position inside the engine's band (schematic center only if absent)
  const pointFrac =
    conf && conf.high_usd > conf.low_usd
      ? Math.min(1, Math.max(0, (conf.point_usd - conf.low_usd) / (conf.high_usd - conf.low_usd)))
      : 0.5;
  const crossFrac = crossover ? qtyToFraction(crossover) : null;
  const mix = provenanceMix(makeAtQty ?? null);

  return (
    <>
      <div style={{ marginTop: 14, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <span style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.1em", color: C.ink45 }}>
          QUANTITY <span style={{ color: C.ink }}>{NUM(snappedQty)}</span>
          <span style={{ color: C.ink40 }}> · computed at the nearest real point</span>
        </span>
        <span style={{ fontFamily: MONO, fontSize: 10, color: C.ink40 }}>annual volume · <span style={{ color: C.user }}>program not set</span></span>
      </div>
      <input
        type="range"
        min={0}
        max={1000}
        step={1}
        value={Math.round(scrubFrac * 1000)}
        onChange={(e) => setScrubFrac(Number(e.target.value) / 1000)}
        aria-label="Quantity"
        style={{ width: "100%", marginTop: 8, accentColor: C.ink }}
      />
      <div style={{ marginTop: 4, position: "relative", display: "flex", justifyContent: "space-between", fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>
        <span>1</span>
        <span>{crossover ? `crossover ≈ ${NUM(crossover)}` : "no crossover computed"}</span>
        <span>10,000</span>
        {crossFrac != null && (
          <span aria-hidden style={{ position: "absolute", top: -22, left: `${crossFrac * 100}%`, transform: "translateX(-50%)", width: 1, height: 16, background: "rgba(23,24,26,0.3)" }} />
        )}
      </div>

      <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: toolAtQty ? "1fr 1fr" : "1fr", gap: 10 }}>
        {/* make-now (owned → marginal) */}
        <div style={{ border: `1.5px solid rgba(31,138,91,0.35)`, borderRadius: 12, padding: "14px 16px", background: "rgba(31,138,91,0.02)" }}>
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", color: C.pass }}>
            {procLabel(makeProcess)} — {marginal ? "OWNED → MARGINAL" : "MAKE NOW"}
          </p>
          <p style={{ margin: "8px 0 0", fontSize: 26, fontWeight: 300, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums" }}>
            {USD(makeAtQty?.unit_cost_usd)} <span style={{ fontSize: 13, color: C.ink45 }}>/unit at this qty</span>
          </p>
          {marginal && (
            <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10, lineHeight: 1.6, color: C.shop }}>
              {marginal.machine ? `on ${marginal.machine} ` : ""}at {USD(marginal.rateUsd)}/hr · <ProvChip p="SHOP" /> — your machine&apos;s own marginal rate, owned capital sunk
            </p>
          )}
          <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10, lineHeight: 1.7, color: C.ink45 }}>
            hours × your rates + mass × your lot price · {mix.groundedPct}% of drivers grounded (● measured/shop/user)
          </p>
          <div style={{ marginTop: 10 }}>
            <ConfidenceBand validated={validated} pointFraction={pointFrac} />
          </div>
          <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 9.5, color: validated ? C.pass : C.cond }}>
            {conf?.label ??
              (makeAtQty ? `±${Math.round(makeAtQty.est_error_band_pct)}% [assumption band] · not shop-validated` : "band withheld")}
          </p>
        </div>

        {/* tooling / acquire */}
        {toolAtQty && (
          <div style={{ border: `1.5px solid ${C.hair}`, borderRadius: 12, padding: "14px 16px" }}>
            <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", color: C.ink45 }}>
              {procLabel(toolingProcess)} — NOT OWNED → ACQUIRE
            </p>
            <p style={{ margin: "8px 0 0", fontSize: 26, fontWeight: 300, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums" }}>
              {USD(toolAtQty.unit_cost_usd)} <span style={{ fontSize: 13, color: C.ink45 }}>/unit incl. tooling</span>
            </p>
            <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10, lineHeight: 1.7, color: C.ink45 }}>
              {crossover ? `amortizes past ${NUM(crossover)} units` : "no crossover — tooling never pays back at these volumes"}
              {toolAtQty.dfm_ready ? "" : " · conditional on a DFM redesign"}
            </p>
            <div style={{ marginTop: 10 }}>
              <GhostButton onClick={() => nav("acquisition")}>Open acquisition consideration →</GhostButton>
            </div>
          </div>
        )}
      </div>
      {cost.decision?.note && (
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40, lineHeight: 1.6 }}>
          engine note: {cost.decision.note}
        </p>
      )}
    </>
  );
}

function DecideHallmark({ result, nav }: { result: VerifyResult; nav: Nav }) {
  const saved = result.cost?.saved;
  const est = result.cost ? makeNowEstimate(result.cost) : null;
  const validated = est?.confidence?.validated ?? false;
  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <p style={{ margin: 0, fontSize: 15, fontWeight: 500, marginRight: "auto" }}>Decide</p>
        <GhostButton onClick={() => nav("records")} disabled={!saved}>
          {saved ? "Saved as a record" : "Not persisted"}
        </GhostButton>
        <InDev label="DECISION APPEND — PENDING" />
      </div>
      <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45, lineHeight: 1.6 }}>
        {saved
          ? "this verification is saved as an immutable cost-decision record. Tagging the outcome make / route-outside appends to that record — engine surface pending."
          : "persistence is off for this decision (COST_PERSIST_ENABLED) — it computed, but was not saved."}
      </p>
      <div style={{ marginTop: 16, borderTop: `1px solid #efeff2`, paddingTop: 14, display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{ flex: 1 }}>
          <ConfidenceBand validated={validated} pointFraction={0.5} />
          <p style={{ margin: "7px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink45, lineHeight: 1.6 }}>
            {validated
              ? "this verdict ships solid — validated against your actuals."
              : "this verdict ships hatched — assumption band, not shop-validated · n=0. It flips solid only when your actuals come back."}
          </p>
        </div>
        <GhostButton onClick={() => nav("calibration")}>See how truth arrives →</GhostButton>
      </div>
    </Card>
  );
}

/* ── driver value formatting — never invents units the engine didn't send ── */
function formatDriverValue(d: DriverView): string {
  if (d.unit === "usd") return USD(d.value);
  if (d.unit === "count" || Number.isInteger(d.value)) return NUM(d.value);
  return d.value.toLocaleString("en-US", { maximumFractionDigits: 3 });
}
function driverUnit(d: DriverView): string {
  if (d.unit === "usd") return "";
  if (d.unit === "count") return "";
  return d.unit;
}

/* ═══════════════════════════════════════════════════════════════════════════
 * ASK-THE-ENGINE DOCK — docked at the foot of the walk.
 *
 * The dock's contract IS the honesty rule: an answer is only ever an
 * ENGINE-COMPUTED ARTIFACT, never generated prose with numbers in it.
 *   • "compare routes [at qty N]"  → the make-now route vs the tooling / next
 *      route, read off THIS part's real CostReport (POST /validate/cost output).
 *   • "should-cost at qty N"       → the should-cost at that qty, off the report.
 *   • "compare saved decisions"    → a LIVE GET /api/v1/cost-decisions/compare
 *      diff of this part's persisted decision vs the org's most-recent other one.
 *   • anything else / free text    → REFUSED. Free-form NL has no engine backend
 *      (IN DEVELOPMENT); the engine never invents an answer.
 * No design fixtures, no fabricated figures — every number is selected from a
 * real response or the ask is refused.
 * ═══════════════════════════════════════════════════════════════════════════ */

type DockState =
  | { t: "idle" }
  | { t: "loading" }
  | { t: "routes"; data: Extract<RouteCompareResult, { status: "ok" }> }
  | { t: "cost"; data: CostAtQtyResult }
  | { t: "saved"; data: CostComparison; otherId: string }
  | { t: "refuse"; title: string; reason: string; nl: boolean };

function AskDock({ cost, running, nav }: { cost: CostReport | null; running: boolean; nav: Nav }) {
  const [text, setText] = useState("");
  const [state, setState] = useState<DockState>({ t: "idle" });
  const canAsk = !!cost && !running;

  function refuse(title: string, reason: string, nl = false) {
    setState({ t: "refuse", title, reason, nl });
  }
  function clear() {
    setState({ t: "idle" });
  }

  function askRoutes(qty: number | null) {
    if (!cost) return;
    const r = compareRoutesAtQty(cost, qty);
    if (r.status === "single") {
      refuse(
        "Nothing to compare — one route.",
        "Only one route was costed for this part, so there is no second route to diff. The should-cost above already carries every driver for that route."
      );
    } else {
      setState({ t: "routes", data: r });
    }
  }

  function askCost(qty: number | null) {
    if (!cost) return;
    setState({ t: "cost", data: computeCostAtQty(cost, qty) });
  }

  async function askSaved() {
    if (!cost) return;
    setState({ t: "loading" });
    const res = await compareSaved(cost.saved?.id ?? null);
    if (res.status === "ok") {
      setState({ t: "saved", data: res.comparison, otherId: res.otherId });
    } else if (res.status === "not_saved") {
      refuse(
        "No saved decision to compare.",
        "This part's decision was not persisted (persistence is off for this run), so there is no record id to diff against. Save a verification, then ask again."
      );
    } else if (res.status === "need_second") {
      refuse(
        "Only one decision on record.",
        "Compare needs a second saved decision — this org has just this one on record. Verify another part (or the same part under a new calibration) and it becomes comparable."
      );
    } else {
      refuse(
        "Compare unavailable.",
        `The compare call did not return (${res.message}). No diff is shown rather than a fabricated one.`
      );
    }
  }

  function submit() {
    const raw = text.trim();
    if (!raw) return;
    if (!cost) {
      refuse("No part loaded.", "Load a part above first — the engine answers only about a part it has actually computed.");
      return;
    }
    const p = parseAsk(raw);
    if (p.kind === "cost_at_qty") askCost(p.qty);
    else if (p.kind === "compare_routes") askRoutes(p.qty);
    else if (p.kind === "compare_saved") void askSaved();
    else refuse("The engine can't compute that.", NL_REFUSAL, true);
  }

  return (
    <div style={{ flexShrink: 0, borderTop: `1px solid ${C.hair2}`, background: C.panel, padding: "10px 30px" }}>
      {/* the answer — an engine artifact, never prose-with-numbers */}
      {state.t === "loading" && (
        <div style={ARTIFACT_STYLE}>
          <Spinner label="asking GET /cost-decisions/compare…" />
        </div>
      )}
      {state.t === "routes" && <RouteCompareArtifact data={state.data} onClose={clear} />}
      {state.t === "cost" && <CostReadoutArtifact data={state.data} onClose={clear} />}
      {state.t === "saved" && <SavedCompareArtifact data={state.data} otherId={state.otherId} onClose={clear} nav={nav} />}
      {state.t === "refuse" && <RefusalArtifact title={state.title} reason={state.reason} nl={state.nl} onClose={clear} />}

      {/* the ask row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, maxWidth: 820, flexWrap: "wrap" }}>
        <div
          style={{
            flex: 1,
            minWidth: 240,
            display: "flex",
            alignItems: "center",
            gap: 10,
            border: `1px solid ${canAsk ? "#dcdce0" : C.hair}`,
            borderRadius: 999,
            padding: "4px 4px 4px 16px",
            background: canAsk ? C.sunken : "#fafafb",
            opacity: canAsk ? 1 : 0.7,
          }}
        >
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            disabled={!canAsk}
            placeholder={
              canAsk
                ? "Ask the engine — “compare routes at qty 1,000” · “should-cost at qty 500”"
                : running
                  ? "computing the walk…"
                  : "Load a part above — the engine answers only about a computed part."
            }
            style={{ flex: 1, minWidth: 0, background: "none", border: "none", outline: "none", fontSize: 13, color: C.ink, fontFamily: "inherit" }}
          />
          <button
            type="button"
            onClick={submit}
            disabled={!canAsk}
            aria-label="Ask"
            title="Ask the engine"
            style={{
              flexShrink: 0,
              width: 30,
              height: 30,
              borderRadius: "50%",
              border: "none",
              background: canAsk ? C.ink : C.ink40,
              color: "#fff",
              cursor: canAsk ? "pointer" : "not-allowed",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m5 12 14 0" />
              <path d="m13 5 7 7-7 7" />
            </svg>
          </button>
        </div>
        <AskChip label="Compare routes @ 1,000" disabled={!canAsk} onClick={() => askRoutes(1000)} />
        <AskChip label="Compare saved decisions →" disabled={!canAsk} onClick={() => void askSaved()} />
        <AskChip
          label="An uncomputable ask"
          disabled={false}
          onClick={() =>
            refuse(
              "The engine can't compute that.",
              NONDETERMINISTIC_REFUSAL
            )
          }
        />
      </div>

      <p style={{ margin: "6px 0 0", display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontFamily: MONO, fontSize: 9, color: C.ink35 }}>
        <span>answers are engine-computed artifacts — only structured asks (compare / should-cost at qty) return numbers</span>
        <InDev label="FREE-FORM NL — IN DEVELOPMENT" />
      </p>
    </div>
  );
}

const ARTIFACT_STYLE: React.CSSProperties = {
  maxWidth: 720,
  marginBottom: 12,
  border: `1px solid ${C.hair}`,
  borderRadius: 14,
  background: "#fafafb",
  padding: "16px 18px",
  animation: "vstepIn 300ms cubic-bezier(0.2,0,0,1) both",
};

function ArtifactHeader({ kicker, onClose }: { kicker: string; onClose: () => void }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
      <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.12em", color: C.ink45 }}>{kicker}</p>
      <button
        type="button"
        onClick={onClose}
        aria-label="Dismiss"
        style={{ marginLeft: "auto", background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 11, color: C.ink40 }}
      >
        ✕
      </button>
    </div>
  );
}

function MonoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontFamily: MONO, fontSize: 12 }}>
      <span style={{ color: C.ink60 }}>{label}</span>
      <span style={{ color: C.ink, textAlign: "right" }}>{value}</span>
    </div>
  );
}

function AskChip({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        flexShrink: 0,
        border: `1px solid ${C.hair}`,
        background: C.panel,
        borderRadius: 999,
        padding: "7px 13px",
        fontSize: 11,
        color: disabled ? C.ink35 : C.ink55,
        cursor: disabled ? "not-allowed" : "pointer",
        fontFamily: "inherit",
        whiteSpace: "nowrap",
        opacity: disabled ? 0.6 : 1,
      }}
    >
      {label}
    </button>
  );
}

/** "compare routes" — two REAL routes off this part's cost report. */
function RouteCompareArtifact({ data, onClose }: { data: Extract<RouteCompareResult, { status: "ok" }>; onClose: () => void }) {
  const deltaColor = data.deltaPct == null ? C.ink45 : data.deltaPct < 0 ? C.pass : C.shop;
  return (
    <div style={ARTIFACT_STYLE}>
      <ArtifactHeader kicker={`ENGINE OUTPUT — COMPUTED, NOT GENERATED · route-vs-route · qty ${NUM(data.snappedQty)}`} onClose={onClose} />
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
        <MonoRow label={`${procLabel(data.a.process)} · make-now`} value={`${USD(data.a.unit)}/unit`} />
        <MonoRow
          label={`${procLabel(data.b.process)}`}
          value={
            <>
              {USD(data.b.unit)}/unit{" "}
              {data.deltaPct != null && (
                <span style={{ color: deltaColor }}>
                  {data.deltaPct >= 0 ? "+" : ""}
                  {data.deltaPct}%
                </span>
              )}
            </>
          }
        />
      </div>
      {data.divergent ? (
        <p style={{ margin: "10px 0 0", display: "flex", alignItems: "baseline", gap: 6, flexWrap: "wrap", fontFamily: MONO, fontSize: 10.5, color: C.ink55 }}>
          <span>
            divergent driver: {data.divergent.name} {data.divergent.a.toLocaleString("en-US", { maximumFractionDigits: 2 })} vs{" "}
            {data.divergent.b.toLocaleString("en-US", { maximumFractionDigits: 2 })}
          </span>
          <ProvChip p={data.divergent.provenance} />
        </p>
      ) : (
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40 }}>
          the two routes share no common driver to diff — unit costs shown, no driver delta invented.
        </p>
      )}
      <p style={{ margin: "8px 0 0", display: "inline-flex", alignItems: "center", gap: 6, fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>
        <ProvChip p="MODEL" />
        <span>
          computed from POST /validate/cost for {data.filename}
          {data.requestedQty != null && data.requestedQty !== data.snappedQty ? ` · nearest computed point to qty ${NUM(data.requestedQty)}` : ""}
        </span>
      </p>
    </div>
  );
}

/** "should-cost at qty N" — the report's make-now (and tooling) route at that qty. */
function CostReadoutArtifact({ data, onClose }: { data: CostAtQtyResult; onClose: () => void }) {
  return (
    <div style={ARTIFACT_STYLE}>
      <ArtifactHeader kicker={`ENGINE OUTPUT — COMPUTED, NOT GENERATED · should-cost · qty ${NUM(data.snappedQty)}`} onClose={onClose} />
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
        {data.makeNow ? (
          <MonoRow label={`${procLabel(data.makeNow.process)} · make-now`} value={`${USD(data.makeNow.unit)}/unit`} />
        ) : (
          <MonoRow label="make-now route" value="withheld — no estimate at this qty" />
        )}
        {data.tooling && <MonoRow label={`${procLabel(data.tooling.process)} · incl. tooling`} value={`${USD(data.tooling.unit)}/unit`} />}
        <MonoRow label="make-vs-buy crossover" value={data.crossover ? `${NUM(data.crossover)} units` : "none computed"} />
      </div>
      <p style={{ margin: "8px 0 0", display: "inline-flex", alignItems: "center", gap: 6, fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>
        <ProvChip p="MODEL" />
        <span>
          computed from POST /validate/cost for {data.filename}
          {data.requestedQty != null && data.requestedQty !== data.snappedQty ? ` · nearest computed point to qty ${NUM(data.requestedQty)}` : ""}
        </span>
      </p>
    </div>
  );
}

/** "compare saved decisions" — a LIVE GET /cost-decisions/compare diff. */
function SavedCompareArtifact({ data, otherId, onClose, nav }: { data: CostComparison; otherId: string; onClose: () => void; nav: Nav }) {
  const rows = data.unit_cost_by_qty.slice(0, 6);
  const nameA = data.a.label || data.a.filename;
  const nameB = data.b.label || data.b.filename;
  return (
    <div style={ARTIFACT_STYLE}>
      <ArtifactHeader kicker="ENGINE OUTPUT — COMPUTED, NOT GENERATED · GET /cost-decisions/compare" onClose={onClose} />
      <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 11, color: C.ink }}>
        <span style={{ color: C.ink70 }}>A</span> {nameA} <span style={{ color: C.ink40 }}>vs</span> <span style={{ color: C.ink70 }}>B</span> {nameB}
      </p>
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
        {rows.map((r) => (
          <MonoRow
            key={r.quantity}
            label={`qty ${NUM(r.quantity)}`}
            value={
              <>
                {USD(r.a?.unit_cost_usd)} vs {USD(r.b?.unit_cost_usd)}
                {r.delta_pct != null && (
                  <span style={{ color: r.delta_pct < 0 ? C.pass : C.shop }}>
                    {" "}
                    {r.delta_pct >= 0 ? "+" : ""}
                    {r.delta_pct}%
                  </span>
                )}
              </>
            }
          />
        ))}
      </div>
      <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink45, lineHeight: 1.6 }}>
        make-now: {procLabel(data.diff.make_now_process[0])} vs {procLabel(data.diff.make_now_process[1])} · crossover{" "}
        {data.diff.crossover_qty[0] ? NUM(data.diff.crossover_qty[0]) : "—"} vs {data.diff.crossover_qty[1] ? NUM(data.diff.crossover_qty[1]) : "—"}
      </p>
      <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 10 }}>
        <GhostButton onClick={() => nav("compare")}>Open in Compare →</GhostButton>
        <span style={{ fontFamily: MONO, fontSize: 9, color: C.ink35 }}>diffed against saved decision {otherId.slice(0, 8)}…</span>
      </div>
    </div>
  );
}

/** The honest refusal — never a fabricated answer. */
function RefusalArtifact({ title, reason, nl, onClose }: { title: string; reason: string; nl: boolean; onClose: () => void }) {
  return (
    <div style={{ maxWidth: 720, marginBottom: 12, border: `1.5px dashed #d3d3d8`, borderRadius: 14, padding: "16px 18px", animation: "vstepIn 300ms cubic-bezier(0.2,0,0,1) both" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <p style={{ margin: 0, fontSize: 14, fontWeight: 500 }}>{title}</p>
        {nl && <InDev label="NL ANSWERING — IN DEVELOPMENT" />}
        <button
          type="button"
          onClick={onClose}
          aria-label="Dismiss"
          style={{ marginLeft: "auto", background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 11, color: C.ink40 }}
        >
          ✕
        </button>
      </div>
      <p style={{ margin: "7px 0 0", fontSize: 12.5, lineHeight: 1.6, color: C.ink55 }}>{reason}</p>
    </div>
  );
}
