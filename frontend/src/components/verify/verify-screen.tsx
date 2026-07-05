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
import { useEffect, useMemo, useState } from "react";
import { C, MONO, USD, NUM, procLabel, statusColor } from "@/lib/verify/tokens";
import type { VerifyResult } from "@/lib/verify/run";
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
import { interpUnitCost, type InterpPoint } from "@/lib/verify/scrub";
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
import { useToast } from "./toast";
import { Card, Kicker, ProvChip, ProvDot, InDev, ConfidenceBand, GhostButton, EmptyState } from "./primitives";

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
  // The user's recorded make/route/acquire/redesign decision for THIS verification.
  // Session state (there is no engine endpoint to append the outcome yet — the
  // Decide card is honest about that). Reset whenever a new run lands.
  const [decision, setDecision] = useState<string | null>(null);
  useEffect(() => {
    setDecision(null);
  }, [result]);

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
      }}
    >
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "26px 30px 20px" }}>
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
            decision={decision}
            setDecision={setDecision}
            onReverify={onReverify}
            nav={nav}
          />
        )}
      </div>

      {/* ask the engine — a docked row, separate from the scrolling walk. It is a
          front door to what the engine ACTUALLY computed for this part (real slices
          of `result`) plus the honest refusal for anything non-deterministic; it
          never generates a number. */}
      <AskDock result={result} nav={nav} />
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
  decision,
  setDecision,
  onReverify,
  nav,
}: {
  result: VerifyResult;
  scrubFrac: number;
  setScrubFrac: (f: number) => void;
  disclose: string | null;
  setDisclose: (s: string | null) => void;
  decision: string | null;
  setDecision: (d: string | null) => void;
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
                  scrubQty={scrubQty}
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
            {cost && <DecideHallmark result={result} decision={decision} setDecision={setDecision} nav={nav} />}
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
  scrubQty,
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
  scrubQty: number;
  scrubFrac: number;
  setScrubFrac: (f: number) => void;
  crossover: number | null;
  toolingProcess: string | null;
  makeProcess: string | null;
  verification: VerificationBlock | null;
  nav: Nav;
}) {
  // The scrub reads the REAL 6-point ladder: at a computed qty it is the engine's
  // own unit cost; between two points it interpolates those two real points along
  // the amortization curve (labelled, never presented as a fresh compute).
  const makeInterp = interpUnitCost(cost, makeProcess, scrubQty);
  const toolInterp = toolingProcess ? interpUnitCost(cost, toolingProcess, scrubQty) : null;
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
          QUANTITY <span style={{ color: C.ink }}>{NUM(scrubQty)}</span>
          <span style={{ color: C.ink40 }}> · {interpNote(makeInterp)}</span>
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
            {USD(makeInterp.unit)} <span style={{ fontSize: 13, color: C.ink45 }}>/unit at this qty</span>
          </p>
          <p style={{ margin: "3px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink40 }}>{interpNote(makeInterp)}</p>
          {marginal && (
            <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10, lineHeight: 1.6, color: C.shop }}>
              {marginal.machine ? `on ${marginal.machine} ` : ""}at {USD(marginal.rateUsd)}/hr · <ProvChip p="SHOP" /> — your machine&apos;s own marginal rate, owned capital sunk
            </p>
          )}
          <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10, lineHeight: 1.7, color: C.ink45 }}>
            hours × your rates + mass × your lot price · {mix.groundedPct}% of drivers grounded (● measured/shop/user)
            <br />band &amp; drivers read at computed qty {NUM(snappedQty)}
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
              {USD(toolInterp?.unit ?? toolAtQty.unit_cost_usd)} <span style={{ fontSize: 13, color: C.ink45 }}>/unit incl. tooling</span>
            </p>
            {toolInterp && <p style={{ margin: "3px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink40 }}>{interpNote(toolInterp)}</p>}
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

const DECIDE_OPTS: { key: string; label: string }[] = [
  { key: "inhouse", label: "Make in-house" },
  { key: "outside", label: "Make outside" },
  { key: "acquire", label: "Acquire capability" },
  { key: "redesign", label: "Redesign" },
];

function DecideHallmark({
  result,
  decision,
  setDecision,
  nav,
}: {
  result: VerifyResult;
  decision: string | null;
  setDecision: (d: string | null) => void;
  nav: Nav;
}) {
  const toast = useToast();
  const saved = result.cost?.saved;
  const est = result.cost ? makeNowEstimate(result.cost) : null;
  const validated = est?.confidence?.validated ?? false;
  const decidedLabel = DECIDE_OPTS.find((o) => o.key === decision)?.label ?? null;
  // Real, verbatim id of the persisted cost-decision artifact (never the design's
  // fixture "V-0117"). A short handle for the line; the full record opens in Records.
  const shortId = saved?.id ? `#${saved.id.slice(0, 8)}` : null;
  const today = new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

  const choose = (key: string, label: string) => {
    const withdrawing = decision === key;
    setDecision(withdrawing ? null : key);
    if (withdrawing) {
      toast(`Decision withdrawn — ${label}`);
      return;
    }
    // Honest: the user's outcome is noted on THIS verification (session). The
    // cost-decision artifact itself is what's persisted (POST /validate/cost); the
    // toast asserts only what actually happened.
    toast(saved ? `${label} — noted · cost-decision ${shortId} is saved` : `${label} — noted on this verification`);
    if (key === "acquire") nav("acquisition");
  };

  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <p style={{ margin: 0, fontSize: 15, fontWeight: 500, marginRight: "auto" }}>Decide</p>
        {DECIDE_OPTS.map((o) => {
          const on = decision === o.key;
          return (
            <button
              key={o.key}
              type="button"
              onClick={() => choose(o.key, o.label)}
              style={{
                background: on ? C.ink : "none",
                border: `1px solid ${on ? C.ink : "#d8d8dc"}`,
                borderRadius: 999,
                color: on ? "#ffffff" : C.ink,
                padding: "9px 16px",
                fontSize: 12.5,
                fontWeight: 500,
                cursor: "pointer",
                fontFamily: "inherit",
                transition: "all 150ms",
              }}
            >
              {o.label}
            </button>
          );
        })}
      </div>

      {decidedLabel ? (
        <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.pass, lineHeight: 1.6, animation: "vtraceIn 300ms cubic-bezier(0.2,0,0,1) both" }}>
          ✓ {decidedLabel} — noted on this verification · {today}
          {saved ? (
            <>
              {" "}· cost-decision <span style={{ color: C.ink }}>{shortId}</span> is the persisted artifact
            </>
          ) : (
            " · this session only (persistence off)"
          )}
        </p>
      ) : (
        <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40, lineHeight: 1.6 }}>
          next → pick one above · your choice is noted on this verification
          {saved ? " beside the saved cost-decision record" : ""}.
        </p>
      )}

      <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <GhostButton onClick={() => nav("records")} disabled={!saved}>
          {saved ? "Open the record →" : "Not persisted"}
        </GhostButton>
        <InDev label="OUTCOME APPEND — IN DEVELOPMENT" />
        <span style={{ fontFamily: MONO, fontSize: 9.5, color: C.ink40, lineHeight: 1.5, flex: 1, minWidth: 180 }}>
          {saved
            ? "the cost-decision is an immutable saved artifact; writing the make/route outcome back onto it is not yet wired."
            : "persistence is off for this decision (COST_PERSIST_ENABLED) — it computed, but was not saved server-side."}
        </span>
      </div>

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

/** Honest label for a scrubbed cost: engine-exact at a computed point, an explicit
 *  interpolation of two real points between them, or a clamp at the ladder's edge. */
function interpNote(p: InterpPoint): string {
  if (p.unit == null) return "no computed estimate on this route";
  if (p.exact) return "engine-exact — a computed point";
  if (p.clamped) return `clamped to the ${p.lo === p.hi ? NUM(p.lo) : ""} computed point — not extrapolated`;
  return `interpolated between computed ${NUM(p.lo)} and ${NUM(p.hi)}`;
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

/* ─── ASK DOCK ────────────────────────────────────────────────────────────────
 * A docked "ask the engine" row. The engine only answers DETERMINISTIC questions,
 * and it answers them from what it ACTUALLY computed for THIS part (real slices of
 * `result`) — never a generated number. The quick asks read the loaded run; the
 * free-text parser is honestly IN DEVELOPMENT; anything non-deterministic gets the
 * honest refusal. No fabricated shop-vs-shop fixture is presented as real.
 */
type AskReply = "cost" | "crossover" | "materials" | "refusal" | "indev";

function AskDock({ result, nav }: { result: VerifyResult | null; nav: Nav }) {
  const [reply, setReply] = useState<AskReply | null>(null);
  const [q, setQ] = useState("");
  const canCompute = !!result?.cost;

  // A new run clears a stale reply so the dock never shows the previous part's answer.
  useEffect(() => {
    setReply(null);
  }, [result]);

  return (
    <div style={{ flexShrink: 0, borderTop: `1px solid ${C.hair2}`, background: C.panel, padding: "10px 30px" }}>
      {reply && <AskReplyCard reply={reply} result={result} nav={nav} onClear={() => setReply(null)} />}
      <div style={{ display: "flex", alignItems: "center", gap: 8, maxWidth: 900, flexWrap: "wrap" }}>
        <div
          style={{
            flex: 1,
            minWidth: 220,
            display: "flex",
            alignItems: "center",
            gap: 10,
            border: `1px solid #dcdce0`,
            borderRadius: 999,
            padding: "4px 4px 4px 16px",
            background: C.bg,
          }}
        >
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") setReply("indev");
            }}
            placeholder="Ask the engine — 'what's the unit cost at 1,000 on my floor?'"
            style={{ flex: 1, minWidth: 0, background: "none", border: "none", outline: "none", fontSize: 13, color: C.ink, fontFamily: "inherit" }}
          />
          <button
            type="button"
            onClick={() => setReply("indev")}
            aria-label="Ask the engine"
            style={{ flexShrink: 0, width: 30, height: 30, borderRadius: "50%", border: "none", background: C.ink, color: "#fff", cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="m5 12 14 0" />
              <path d="m13 5 7 7-7 7" />
            </svg>
          </button>
        </div>
        {canCompute && (
          <>
            <AskChip label="Unit cost @ 1,000" onClick={() => setReply("cost")} />
            <AskChip label="Where's the crossover?" onClick={() => setReply("crossover")} />
            <AskChip label="What survives this world?" onClick={() => setReply("materials")} />
          </>
        )}
        <AskChip label="An uncomputable ask" onClick={() => setReply("refusal")} />
      </div>
      <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 9, color: C.ink35 }}>
        answers are engine-computed artifacts read off this verification — the copilot cannot offer a question the engine can&apos;t compute
      </p>
    </div>
  );
}

function AskChip({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{ flexShrink: 0, border: `1px solid #dcdce0`, background: "#fff", borderRadius: 999, padding: "7px 13px", fontSize: 11, color: C.ink55, cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap" }}
    >
      {label}
    </button>
  );
}

function AskCard({ children, dashed }: { children: React.ReactNode; dashed?: boolean }) {
  return (
    <div
      style={{
        maxWidth: 720,
        marginBottom: 12,
        border: dashed ? `1.5px dashed #d3d3d8` : `1px solid ${C.hair}`,
        borderRadius: 14,
        background: dashed ? "transparent" : "#fafafb",
        padding: "16px 18px",
        animation: "vstepIn 300ms cubic-bezier(0.2,0,0,1) both",
      }}
    >
      {children}
    </div>
  );
}

function AskClearBtn({ onClear }: { onClear: () => void }) {
  return (
    <button
      type="button"
      onClick={onClear}
      aria-label="Dismiss"
      style={{ marginLeft: "auto", background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 11, color: C.ink40 }}
    >
      ✕
    </button>
  );
}

function AskReplyCard({
  reply,
  result,
  nav,
  onClear,
}: {
  reply: AskReply;
  result: VerifyResult | null;
  nav: Nav;
  onClear: () => void;
}) {
  if (reply === "refusal") {
    return (
      <AskCard dashed>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <p style={{ margin: 0, fontSize: 14, fontWeight: 500 }}>The engine can&apos;t compute that.</p>
          <AskClearBtn onClear={onClear} />
        </div>
        <p style={{ margin: "7px 0 0", fontSize: 12.5, lineHeight: 1.6, color: C.ink55 }}>
          Anything that isn&apos;t a deterministic property of geometry, your machines, or your rates has no engine answer — so
          none is invented. It can compute: envelope fit · surviving materials · process physics · hours · resource cost · crossovers.
        </p>
      </AskCard>
    );
  }

  if (reply === "indev") {
    return (
      <AskCard dashed>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <p style={{ margin: 0, fontSize: 14, fontWeight: 500 }}>The free-text copilot is being wired up.</p>
          <InDev label="NL PARSE — IN DEVELOPMENT" />
          <AskClearBtn onClear={onClear} />
        </div>
        <p style={{ margin: "7px 0 0", fontSize: 12.5, lineHeight: 1.6, color: C.ink55 }}>
          It will route a typed question to the engine&apos;s computable outputs — every one of which is already on this page.
          For now use a quick ask below: unit cost, crossover, or surviving materials. No answer is ever generated.
        </p>
      </AskCard>
    );
  }

  const cost = result?.cost ?? null;
  if (!cost) {
    return (
      <AskCard dashed>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <p style={{ margin: 0, fontSize: 14, fontWeight: 500 }}>Nothing is computed yet.</p>
          <AskClearBtn onClear={onClear} />
        </div>
        <p style={{ margin: "7px 0 0", fontSize: 12.5, lineHeight: 1.6, color: C.ink55 }}>
          Drop a part to run the walk — the copilot answers only from what the engine actually computed.
        </p>
      </AskCard>
    );
  }

  const makeProc = cost.decision?.make_now_process ?? null;
  const toolProc = cost.decision?.tooling_process ?? null;

  if (reply === "cost") {
    const mk = interpUnitCost(cost, makeProc, 1000);
    const tl = toolProc ? interpUnitCost(cost, toolProc, 1000) : null;
    return (
      <AskCard>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <Kicker color={C.ink45}>ENGINE OUTPUT — COMPUTED, NOT GENERATED · unit cost · qty 1,000</Kicker>
          <AskClearBtn onClear={onClear} />
        </div>
        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6, fontFamily: MONO, fontSize: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
            <span style={{ color: C.ink60 }}>{procLabel(makeProc)} — make now</span>
            <span>
              {USD(mk.unit)}/unit <span style={{ color: C.ink40 }}>· {interpNote(mk)}</span>
            </span>
          </div>
          {toolProc && tl && (
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span style={{ color: C.ink60 }}>{procLabel(toolProc)} — tooled</span>
              <span>
                {USD(tl.unit)}/unit <span style={{ color: C.ink40 }}>· {interpNote(tl)}</span>
              </span>
            </div>
          )}
        </div>
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>
          read off {result?.file.name} · POST /validate/cost — your rates, not a market&apos;s
        </p>
      </AskCard>
    );
  }

  if (reply === "crossover") {
    const cross = cost.decision?.crossover_qty ?? null;
    return (
      <AskCard>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <Kicker color={C.ink45}>ENGINE OUTPUT — COMPUTED, NOT GENERATED · make-vs-tool crossover</Kicker>
          <AskClearBtn onClear={onClear} />
        </div>
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 13, color: C.ink }}>
          {cross != null ? (
            <>
              crossover ≈ <span style={{ fontSize: 15 }}>{NUM(cross)}</span> units
            </>
          ) : (
            "no crossover — tooling never pays back at these volumes"
          )}
        </p>
        {cross != null && (
          <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink50, lineHeight: 1.6 }}>
            below it: make now on {procLabel(makeProc)} · above it: {toolProc ? procLabel(toolProc) : "a tooled route"} amortizes the tool
          </p>
        )}
        <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>read off {result?.file.name} · POST /validate/cost</p>
      </AskCard>
    );
  }

  // reply === "materials"
  const survivors = Array.from(new Set(cost.estimates.map((e) => e.material).filter((m): m is string => !!m)));
  const strikes = envStrikes(result?.verification ?? null);
  const worldDeclared = !!result?.envDeclared || !!result?.verification?.environment_declared;
  return (
    <AskCard>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <Kicker color={C.ink45}>ENGINE OUTPUT — COMPUTED, NOT GENERATED · materials on the shortlisted routes</Kicker>
        <AskClearBtn onClear={onClear} />
      </div>
      <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 7 }}>
        {survivors.length > 0 ? (
          survivors.map((m) => (
            <span key={m} style={{ display: "inline-flex", alignItems: "center", gap: 7, border: `1px solid ${C.hair}`, borderRadius: 999, padding: "5px 12px", fontFamily: MONO, fontSize: 11.5, color: C.ink }}>
              <ProvDot p="MEASURED" size={6} />
              {m}
            </span>
          ))
        ) : (
          <span style={{ fontFamily: MONO, fontSize: 11, color: C.ink45 }}>material withheld — the engine costed no named material</span>
        )}
      </div>
      {strikes.length > 0 ? (
        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 5 }}>
          {strikes.map((s) => (
            <div key={s.material} style={{ display: "flex", alignItems: "baseline", gap: 8, fontFamily: MONO, fontSize: 11 }}>
              <span style={{ color: C.fail, textDecoration: "line-through", whiteSpace: "nowrap", flexShrink: 0 }}>{s.material}</span>
              <span style={{ color: C.ink55, lineHeight: 1.5 }}>{s.reason}</span>
            </div>
          ))}
        </div>
      ) : (
        <p style={{ margin: "9px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45, lineHeight: 1.6 }}>
          {worldDeclared
            ? "the declared world excluded nothing on these routes — every costed material survives it."
            : "no world declared — these are ambient survivors. Declare a world above to gate them by NACE MR0175 / HDT."}
        </p>
      )}
      <p style={{ margin: "9px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>
        survivors = materials the engine actually costed · excluded ones are struck with their cited standard ·{" "}
        <button type="button" onClick={() => nav("compare")} style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 9.5, color: C.user }}>
          compare routes →
        </button>
      </p>
    </AskCard>
  );
}
