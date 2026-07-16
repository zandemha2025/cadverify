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
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { analysisFailureCopy } from "@/lib/verify/failure-copy";
import { partitionDfmByRoute, routeScopedDfmVerdict } from "@/lib/dfm-scope";
import { C, MONO, USD, NUM, procLabel, statusColor, normProv } from "@/lib/verify/tokens";
import type { VerifyResult } from "@/lib/verify/run";
import { fetchCostDecision, setCostDecisionDisposition } from "@/lib/api";
import type { CostReport, CostComparison } from "@/lib/api";
import {
  COST_DISPOSITION_NOTE_MAX_LENGTH,
  COST_DISPOSITIONS,
  costDispositionLabel,
  isCostDisposition,
  type CostDisposition,
} from "@/lib/cost-disposition";
import {
  parseAsk,
  computeCostAtQty,
  compareRoutesAtQty,
  compareSaved,
  explainVerdict,
  materialsForReport,
  driverReadout,
  timeReadout,
  crossoverReadout,
  NL_REFUSAL,
  NONDETERMINISTIC_REFUSAL,
  type CostAtQtyResult,
  type RouteCompareResult,
  type VerdictExplanationResult,
  type MaterialsResult,
  type DriverReadoutResult,
  type TimeReadoutResult,
  type CrossoverReadoutResult,
} from "@/lib/verify/ask";
import {
  driverViews,
  makeNowEstimate,
  routeDfmOutcome,
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
import {
  readIdentity,
  identityCardModel,
  closestUnconfirmedModel,
  noMatchLine,
  runnerUpLabel,
  type IdentityCardModel,
  type ClosestUnconfirmedModel,
} from "@/lib/verify/identity";
import { confirmIdentity } from "@/lib/verify/identity-api";
import { useToast } from "./toast";
import { Card, Kicker, ProvChip, ProvDot, ConfidenceBand, GhostButton, EmptyState, Spinner } from "./primitives";
import { PipelineOverlay } from "./pipeline-overlay";
import { geometryFromResult } from "@/lib/verify/pipeline";

/** Light status colour for a verdict/fit tone. */
function toneColor(t: Tone): string {
  return t === "pass" ? C.pass : t === "cond" ? C.cond : t === "fail" ? C.fail : C.ink45;
}

type Nav = (screen: string) => void;

interface Props {
  result: VerifyResult | null;
  running: boolean;
  guided?: boolean;
  fileName: string | null;
  env: { temp: boolean; sour: boolean; pressure: boolean };
  setEnv: (e: { temp: boolean; sour: boolean; pressure: boolean }) => void;
  materialClass: string;
  materialProvenance: "DEFAULT" | "USER";
  setMaterialClass: (materialClass: string) => void;
  onPickFile: () => void;
  onReverify: () => void;
  onRetryCost: () => void;
  nav: Nav;
}

const ENV_CHIPS: { key: "temp" | "sour" | "pressure"; label: string }[] = [
  { key: "temp", label: "120 °C service" },
  { key: "sour", label: "sour service (H₂S)" },
  { key: "pressure", label: "35 MPa pressure" },
];

const MATERIAL_CLASSES = [
  { key: "polymer", label: "Polymer" },
  { key: "aluminum", label: "Aluminum" },
  { key: "steel", label: "Steel" },
  { key: "stainless", label: "Stainless" },
  { key: "titanium", label: "Titanium" },
];

function StatusChip({ label }: { label: string }) {
  return (
    <span style={{ border: `1px dashed ${C.hair}`, borderRadius: 999, padding: "2px 7px", fontFamily: MONO, fontSize: 9, letterSpacing: "0.08em", color: C.ink45, whiteSpace: "nowrap" }}>
      {label}
    </span>
  );
}

export function VerifyScreen(props: Props) {
  const {
    result,
    running,
    env,
    setEnv,
    materialClass,
    materialProvenance,
    setMaterialClass,
    onPickFile,
    onReverify,
    onRetryCost,
    nav,
  } = props;
  const [scrubFrac, setScrubFrac] = useState(0.5);
  const [disclose, setDisclose] = useState<string | null>(null);
  // The human outcome is loaded from and written to the saved cost-decision.
  // Reset while a new run lands; DecideHallmark then hydrates the new record.
  const [decision, setDecision] = useState<CostDisposition | null>(null);
  useEffect(() => {
    setDecision(null);
  }, [result]);

  return (
    <>
    <div
      className="cv-verify-walk"
      style={{
        animation: "vscreenIn 320ms cubic-bezier(0.2,0,0,1) both",
        flex: 1,
        minWidth: 0,
        minHeight: 0,
        display: "flex",
        flexDirection: "column",
        background: C.bg,
      }}
    >
      <div className="cv-verify-walk-scroll" style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "26px 30px 20px", display: "flex", flexDirection: "column" }}>
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
          materials that survive its service conditions — and what will it really take?
        </p>

        {/* the walk */}
        <div>
          {running && result?.validation ? (
            <FirstInsight result={result} />
          ) : running ? (
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
              onRetryCost={onRetryCost}
              nav={nav}
            />
          )}
        </div>

        <PersonalizationDoor
          result={result}
          running={running}
          env={env}
          setEnv={setEnv}
          materialClass={materialClass}
          materialProvenance={materialProvenance}
          setMaterialClass={setMaterialClass}
        />
      </div>

      {/* ask the engine — a docked row, separate from the scrolling walk. It is a
          front door to what the engine ACTUALLY computed for this part (real slices
          of `result`) plus the honest refusal for anything non-deterministic; it
          never generates a number. */}
      <AskDock cost={result?.cost ?? null} running={running} nav={nav} />
    </div>
    <PipelineOverlay
      running={running}
      result={result}
      fileName={props.fileName}
      guided={props.guided}
    />
    </>
  );
}

function PersonalizationDoor({
  result,
  running,
  env,
  setEnv,
  materialClass,
  materialProvenance,
  setMaterialClass,
}: Pick<
  Props,
  | "result"
  | "running"
  | "env"
  | "setEnv"
  | "materialClass"
  | "materialProvenance"
  | "setMaterialClass"
>) {
  const hostile = env.temp || env.sour || env.pressure;
  // The env door tells the exact truth about the last persistence round-trip.
  const door = envDoorStatus(hostile, running, result);

  return (
    <section
      aria-label="Optional service and material assumptions"
      style={{
        marginTop: 16,
        border: `1px solid ${C.hair}`,
        borderRadius: 16,
        background: C.panel,
        padding: "18px 20px",
      }}
    >
      <div style={{ marginBottom: 15 }}>
        <Kicker>MAKE THIS VERDICT YOURS · OPTIONAL</Kicker>
        <p style={{ margin: "6px 0 0", color: C.ink55, fontSize: 12.5, lineHeight: 1.55 }}>
          {result
            ? "The answer above uses a default material and ambient service until you declare otherwise."
            : "You can start with the defaults. Declare these only when they matter to your part."}
        </p>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <Kicker>SERVICE CONDITIONS</Kicker>
        <span style={{ fontFamily: MONO, fontSize: 10.5, color: door.chipColor }}>{door.chip}</span>
      </div>
      <div
        role="group"
        aria-label="Service conditions"
        style={{ marginTop: 14, display: "flex", flexWrap: "wrap", gap: 8 }}
      >
        {ENV_CHIPS.map((chip) => {
          const on = env[chip.key];
          return (
            <button
              key={chip.key}
              type="button"
              aria-pressed={on}
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
      <div style={{ marginTop: 16, borderTop: `1px solid ${C.hair2}`, paddingTop: 14 }}>
        <Kicker>
          MATERIAL CLASS ·{" "}
          <span style={{ color: materialProvenance === "USER" ? C.user : C.def }}>
            {materialProvenance === "USER" ? "● USER" : "○ DEFAULT"}
          </span>
        </Kicker>
        <div
          role="radiogroup"
          aria-label="Material class"
          style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 8 }}
        >
          {MATERIAL_CLASSES.map((material) => {
            const on = materialClass === material.key;
            return (
              <button
                key={material.key}
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => setMaterialClass(material.key)}
                style={{
                  border: on ? `1px solid ${C.user}` : `1px solid ${C.hair}`,
                  background: on ? "rgba(122,99,201,0.1)" : "#ffffff",
                  color: on ? C.user : C.ink70,
                  borderRadius: 999,
                  padding: "7px 13px",
                  fontSize: 12,
                  cursor: "pointer",
                  fontFamily: MONO,
                  transition: "all 150ms",
                }}
              >
                {material.label}
              </button>
            );
          })}
        </div>
      </div>
    </section>
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
  if (running && hostile) {
    return {
      chip: "capturing…",
      chipColor: C.ink40,
      line: "declaring these service conditions on the part's record, then re-costing against them…",
      color: C.cond,
    };
  }
  if (result && result.envDeclared) {
    if (result.envCaptured) {
      return {
        chip: "● USER · on the record",
        chipColor: C.user,
        line: "service conditions declared — captured on this part's record. The verification below reflects them: materials that can't survive these conditions are struck with their cited standard.",
        color: C.pass,
      };
    }
    return {
      chip: "drives this preview only",
      chipColor: C.cond,
      line:
        "service conditions declared — drives this preview only, NOT captured to the record" +
        (result.envError ? ` (${result.envError})` : "") +
        ".",
      color: C.cond,
    };
  }
  if (result && !result.envDeclared) {
    return {
      chip: "ambient",
      chipColor: C.ink40,
      line: "no service conditions declared — the part is verified at ambient.",
      color: C.ink40,
    };
  }
  if (hostile) {
    return {
      chip: "captured on verify",
      chipColor: C.ink40,
      line: "service conditions declared — they'll be captured on the part's record when you verify, and any material that can't survive them is struck with its cited standard.",
      color: C.cond,
    };
  }
  return {
    chip: "ambient",
    chipColor: C.ink40,
    line: "no service conditions declared — the part will be verified at ambient.",
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
      <Kicker color={C.ink45}>COMPUTING — RUNNING THE GATES</Kicker>
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

/** The first value-bearing state. Validation has landed; costing is deliberately
 * sequential and remains in flight, so the useful DFM answer is no longer hidden
 * behind unrelated setup or a modal progress performance. */
function FirstInsight({ result }: { result: VerifyResult }) {
  const validation = result.validation;
  if (!validation) return <ComputingBanner />;
  const geometry = geometryFromResult(result);
  const route = validation.best_process;
  const partition = partitionDfmByRoute(validation, route);
  const fixes = partition.route;
  const firstFix = fixes[0]?.issue ?? null;
  const verdict = routeScopedDfmVerdict(validation, route);
  const tone = statusColor(verdict);
  return (
    <section
      role="status"
      data-testid="verify-first-insight"
      style={{
        marginTop: 18,
        border: `1px solid ${C.hair}`,
        borderTop: `3px solid ${tone}`,
        borderRadius: 16,
        background: C.panel,
        padding: "21px 22px",
        animation: "vstepIn 180ms cubic-bezier(0.2,0,0,1) both",
      }}
    >
      <Kicker color={tone}>ROUTING + DFM READY · COST CALCULATING</Kicker>
      <p style={{ margin: "10px 0 0", color: C.ink, fontSize: 23, fontWeight: 450, lineHeight: 1.25, letterSpacing: "-0.018em" }}>
        {validation.best_process
          ? `Best preliminary route: ${procLabel(validation.best_process)}`
          : "Geometry measured. Route still unresolved."}
      </p>
      <p style={{ margin: "8px 0 0", color: C.ink60, fontSize: 13, lineHeight: 1.6 }}>
        {firstFix
          ? `${fixes.length} route ${fixes.length === 1 ? "issue" : "issues"}. First: ${firstFix.message}`
          : verdict === "pass"
            ? "No blocking DFM issue was returned. The resource-cost record is still being assembled."
            : "The DFM result is ready. The resource-cost record is still being assembled."}
      </p>
      {geometry ? (
        <div style={{ marginTop: 15, display: "flex", flexWrap: "wrap", gap: 8 }}>
          <StatusChip label={`${geometry.bbox_mm.map((n) => n.toFixed(1)).join(" × ")} mm`} />
          <StatusChip label={`${geometry.volume_cm3.toFixed(2)} cm³`} />
          <StatusChip label={`watertight ${String(geometry.watertight)}`} />
          <span style={{ alignSelf: "center", fontFamily: MONO, fontSize: 9.5, color: C.measured }}>● MEASURED</span>
        </div>
      ) : null}
      <p style={{ margin: "14px 0 0", borderTop: `1px solid ${C.hair2}`, paddingTop: 12, fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>
        DFM {verdict.toUpperCase()} · analysis {NUM(validation.analysis_time_ms)} ms · cost continues without rerunning DFM
      </p>
    </section>
  );
}

function DropPrompt({ onPickFile }: { onPickFile: () => void }) {
  return (
    <div style={{ marginTop: 18 }}>
      <EmptyState
        title="Drop a part to begin the walk."
        body="STL, STEP or IGES. It's parsed in-process and the mesh is discarded — the engine keeps the decision, never your CAD. Nothing on this page is shown until the engine computes it."
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
  right?: ReactNode;
  children: ReactNode;
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
  onRetryCost,
  nav,
}: {
  result: VerifyResult;
  scrubFrac: number;
  setScrubFrac: (f: number) => void;
  disclose: string | null;
  setDisclose: (s: string | null) => void;
  decision: CostDisposition | null;
  setDecision: (d: CostDisposition | null) => void;
  onReverify: () => void;
  onRetryCost: () => void;
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
      <VerdictBanner
        result={result}
        makeNow={makeNow}
        nav={nav}
        onReverify={onReverify}
        onRetryCost={onRetryCost}
      />

      {/* retrieval-grounded IDENTITY — the org's closest PRIOR part, a SUGGESTION
          to confirm (rendered only when the engine grounded one; empty/anonymous
          corpus renders nothing). */}
      <IdentitySuggestion cost={cost} meshHash={result.meshHash} />

      <p
        data-testid="verify-evidence-hash"
        style={{
          margin: "12px 0 0",
          fontFamily: MONO,
          fontSize: 10.5,
          color: C.ink45,
          overflowWrap: "anywhere",
        }}
      >
        Evidence hash · {result.meshHash ?? "unavailable"}
      </p>

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
                  Your machine floor is the baseline every makeability verdict is measured against. Declare it once — a CSV or five minutes of typing.
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
                    <StatusChip label="MAKEABILITY NOT EVALUATED" /> — the floor is declared; no fit is faked here.
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
            <StepShell n={2} title="Materials that survive these service conditions" delayMs={120} right={cost?.material_class ?? undefined}>
              <div style={{ marginTop: 12 }}>
                {cost ? (
                  <p style={{ margin: 0, fontFamily: MONO, fontSize: 11.5, color: C.ink60, lineHeight: 1.7 }}>
                    material class <span style={{ color: C.ink }}>{cost.material_class}</span>
                    {cost.routing?.material_hint ? ` · route hint ${cost.routing.material_hint}` : ""}{" "}
                    <ProvChip p={normProv(cost.assumptions?.find((a) => a.name === "material_class")?.provenance)} />
                  </p>
                ) : (
                  <p style={{ margin: 0, fontFamily: MONO, fontSize: 11.5, color: C.ink50 }}>material class withheld — costing unavailable</p>
                )}
                {verification ? (
                  <EnvStrikesBlock verification={verification} envDeclared={result.envDeclared} />
                ) : (
                  <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40, lineHeight: 1.6 }}>
                    environment-driven survival filtering (NACE MR0175 / HDT tables) is part of the makeability verification —{" "}
                    <StatusChip label="DECLARE A WORLD TO EVALUATE" />. Invalid materials are filtered out visibly, never silently.
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

/** Bucket → the light status tone used across the Verify instrument. */
function identityTone(bucket: string): string {
  if (bucket === "HIGH") return C.pass;
  if (bucket === "MEDIUM") return C.cond;
  return C.ink45;
}

/**
 * The retrieval-grounded IDENTITY suggestion, near the TOP of the result. It is
 * ALWAYS a suggestion the user confirms — the matched designation, its REAL
 * confidence % + bucket, a provenance chip (RETRIEVED · your part library), the
 * honest caveat, and the runner-up matches (transparency, not a black box).
 *
 * Honesty rails: renders the card ONLY when `identity.grounded === true` AND the
 * top match carries a declared identity; a non-grounded result over a non-empty
 * corpus shows a QUIET one-liner; a null / empty-corpus identity renders NOTHING.
 * Confirm → POST /identity/confirm (this part's mesh_hash + the matched identity);
 * "Not this" dismisses and reveals a minimal "declare manually" field that also
 * confirms. Nothing here asserts an identity as fact.
 */
function IdentitySuggestion({ cost, meshHash }: { cost: CostReport | null; meshHash: string | null }) {
  const toast = useToast();
  const id = useMemo(() => readIdentity(cost), [cost]);
  const model = useMemo(() => identityCardModel(id), [id]);
  // Lever 2 — the honest LOW-confidence "closest in your library" candidate (only
  // present when NOT grounded and the backend surfaced a well-separated closest).
  const lowModel = useMemo(() => closestUnconfirmedModel(id), [id]);

  const [dismissed, setDismissed] = useState(false);
  const [confirmed, setConfirmed] = useState<string | null>(null); // the confirmed designation
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualPart, setManualPart] = useState("");

  // Grounded card path.
  if (model) {
    if (dismissed && !manualOpen && !confirmed) {
      // fall through to the quiet dismissed state below
    } else {
      return (
        <div style={{ marginTop: 12 }}>
          <IdentityCard
            model={model}
            meshHash={meshHash}
            confirmed={confirmed}
            busy={busy}
            err={err}
            manualOpen={manualOpen}
            manualPart={manualPart}
            setManualPart={setManualPart}
            onConfirm={async (input, label) => {
              if (!meshHash) {
                setErr("this part's mesh hash isn't available — re-verify to confirm");
                return;
              }
              setBusy(true);
              setErr(null);
              const res = await confirmIdentity({ mesh_hash: meshHash, ...input });
              setBusy(false);
              if (res.ok) {
                setConfirmed(label);
                setManualOpen(false);
                toast("Identity confirmed — saved to your part library");
              } else {
                setErr(res.error);
              }
            }}
            onNotThis={() => setDismissed(true)}
            onDeclareManually={() => setManualOpen(true)}
          />
        </div>
      );
    }
  }

  // Dismissed the grounded card → a quiet acknowledgement (no noise, reversible).
  if (model && dismissed) {
    return (
      <p style={{ margin: "12px 2px 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40 }}>
        identity suggestion dismissed —{" "}
        <button
          type="button"
          onClick={() => setDismissed(false)}
          style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 10.5, color: C.user }}
        >
          show again
        </button>
      </p>
    );
  }

  // Lever 2 — a real-but-below-MEDIUM closest part: a distinct, SOFTER low-confidence
  // card the user confirms. Never auto-asserted; an unrelated part (torus) never
  // reaches here (backend leaves closest_unconfirmed null → lowModel null).
  if (lowModel) {
    if (dismissed && !confirmed) {
      return (
        <p style={{ margin: "12px 2px 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40 }}>
          closest-match suggestion dismissed —{" "}
          <button
            type="button"
            onClick={() => setDismissed(false)}
            style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 10.5, color: C.user }}
          >
            show again
          </button>
        </p>
      );
    }
    return (
      <div style={{ marginTop: 12 }}>
        <ClosestUnconfirmedCard
          model={lowModel}
          meshHash={meshHash}
          confirmed={confirmed}
          busy={busy}
          err={err}
          onConfirm={async (input, label) => {
            if (!meshHash) {
              setErr("this part's mesh hash isn't available — re-verify to confirm");
              return;
            }
            setBusy(true);
            setErr(null);
            const res = await confirmIdentity({ mesh_hash: meshHash, ...input });
            setBusy(false);
            if (res.ok) {
              setConfirmed(label);
              toast("Identity confirmed — saved to your part library");
            } else {
              setErr(res.error);
            }
          }}
          onNotThis={() => setDismissed(true)}
        />
      </div>
    );
  }

  // Not grounded but the org HAS a library → a quiet, non-intrusive one-liner.
  const quiet = noMatchLine(id);
  if (quiet) {
    return (
      <p style={{ margin: "12px 2px 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40 }}>
        {quiet} — geometry retrieved {id?.corpus_size ?? 0} prior part
        {(id?.corpus_size ?? 0) === 1 ? "" : "s"}, none confident enough to suggest.
      </p>
    );
  }

  // null / empty corpus → render NOTHING (the honest empty; no fabricated identity).
  return null;
}

/** The grounded identity card — reuses the light-instrument idiom (Kicker / mono
 *  evidence / provenance chip) from the other Verify cards. */
function IdentityCard({
  model,
  meshHash,
  confirmed,
  busy,
  err,
  manualOpen,
  manualPart,
  setManualPart,
  onConfirm,
  onNotThis,
  onDeclareManually,
}: {
  model: IdentityCardModel;
  meshHash: string | null;
  confirmed: string | null;
  busy: boolean;
  err: string | null;
  manualOpen: boolean;
  manualPart: string;
  setManualPart: (s: string) => void;
  onConfirm: (input: { declared_part_id?: string; declared_name?: string; program?: string }, label: string) => void;
  onNotThis: () => void;
  onDeclareManually: () => void;
}) {
  const tone = identityTone(model.bucket);
  const m = model.match;
  return (
    <div
      data-testid="identity-card"
      style={{
        border: `1px solid ${C.hair}`,
        borderLeft: `3px solid ${tone}`,
        borderRadius: 14,
        background: C.panel,
        padding: "16px 18px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <Kicker>PART IDENTITY · RETRIEVED FROM YOUR LIBRARY</Kicker>
        {/* provenance chip — a retrieved suggestion from the org's own corpus */}
        <span
          data-testid="identity-prov"
          title={m.provenance}
          style={{
            display: "inline-flex", alignItems: "center", gap: 6, fontFamily: MONO,
            fontSize: 9.5, letterSpacing: "0.04em", color: C.user,
            border: `1px solid ${C.hair}`, borderRadius: 999, padding: "2px 9px",
          }}
        >
          <span aria-hidden style={{ color: C.user }}>◆</span>
          RETRIEVED · your part library
        </span>
      </div>

      {confirmed ? (
        <>
          <p data-testid="identity-confirmed" style={{ margin: "10px 0 0", fontSize: 15, fontWeight: 500, color: C.ink }}>
            ✓ Identity confirmed — {confirmed}
          </p>
          <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>
            saved to your part library as{" "}
            <span style={{ color: C.user }}>● USER</span> — future look-alike parts will carry it.
          </p>
        </>
      ) : (
        <>
          {/* Lead: the matched designation — a SUGGESTION, never asserted. */}
          <p data-testid="identity-lead" style={{ margin: "10px 0 0", fontSize: 15, lineHeight: 1.35, color: C.ink, fontWeight: 500 }}>
            {model.lead}
            {model.program && (
              <span style={{ fontFamily: MONO, fontSize: 11, fontWeight: 400, color: C.ink55 }}>{" "}· {model.program}</span>
            )}
          </p>

          {/* Confidence % + bucket pill (real fields). */}
          <div style={{ margin: "9px 0 0", display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
            <span
              data-testid="identity-confidence"
              style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.06em", color: tone, border: `1px solid ${tone}`, borderRadius: 999, padding: "2px 9px" }}
            >
              {model.pct}% · {model.bucket} CONFIDENCE
            </span>
            <span style={{ fontFamily: MONO, fontSize: 9.5, color: C.ink45 }}>
              geometry {(m.geometry_similarity * 100).toFixed(0)}%
              {m.name_similarity != null ? ` · name ${(m.name_similarity * 100).toFixed(0)}%` : " · name n/a"}
            </span>
          </div>

          {/* Honest caveat — verbatim from the engine when present. */}
          <p style={{ margin: "9px 0 0", fontSize: 11.5, lineHeight: 1.5, color: C.ink55 }}>
            {model.caveat}
          </p>

          {/* Runner-ups — transparency, not a black box. */}
          {model.runners.length > 0 && (
            <p data-testid="identity-runners" style={{ margin: "7px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40 }}>
              other near matches: {model.runners.map(runnerUpLabel).join(" · ")}
            </p>
          )}

          {err && (
            <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.fail }}>{err}</p>
          )}

          {/* Actions */}
          <div style={{ marginTop: 13, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <GhostButton
              primary
              disabled={busy || !meshHash}
              title={meshHash ? "Confirm this identity onto your part library" : "mesh hash unavailable"}
              onClick={() =>
                onConfirm(
                  {
                    declared_part_id: m.declared_part_id ?? undefined,
                    declared_name: m.declared_name ?? undefined,
                    program: m.program ?? undefined,
                  },
                  model.lead.replace(/^Looks like your /, "")
                )
              }
            >
              {busy ? "Confirming…" : "Confirm"}
            </GhostButton>
            <GhostButton disabled={busy} onClick={onNotThis}>Not this</GhostButton>
            {!manualOpen && (
              <button
                type="button"
                onClick={onDeclareManually}
                style={{ background: "none", border: "none", padding: 0, cursor: "pointer", fontFamily: MONO, fontSize: 10.5, color: C.user }}
              >
                declare manually →
              </button>
            )}
          </div>

          {/* Minimal "declare manually" affordance — type the real part #, also confirms. */}
          {manualOpen && (
            <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <input
                data-testid="identity-manual-input"
                value={manualPart}
                onChange={(e) => setManualPart(e.target.value)}
                placeholder="real part # / name"
                style={{
                  fontFamily: MONO, fontSize: 12, color: C.ink, background: C.sunken,
                  border: `1px solid ${C.hair}`, borderRadius: 8, padding: "7px 10px", minWidth: 200,
                }}
              />
              <GhostButton
                primary
                disabled={busy || !meshHash || manualPart.trim().length === 0}
                onClick={() => onConfirm({ declared_part_id: manualPart.trim() }, manualPart.trim())}
              >
                {busy ? "Saving…" : "Save identity"}
              </GhostButton>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** The Lever-2 LOW-confidence "closest in your library" card — a deliberately
 *  SOFTER, visually-distinct variant of IdentityCard (dashed border, muted tone, an
 *  explicit "LOW CONFIDENCE" label and honest caveat). It reuses the same tokens and
 *  provenance idiom, but never reads as a confident assertion: it asks "is this it?"
 *  and the user decides (Confirm / Not this). Shown ONLY when the backend surfaced a
 *  well-separated closest candidate below the MEDIUM bar; an unrelated part never
 *  reaches here. */
function ClosestUnconfirmedCard({
  model,
  meshHash,
  confirmed,
  busy,
  err,
  onConfirm,
  onNotThis,
}: {
  model: ClosestUnconfirmedModel;
  meshHash: string | null;
  confirmed: string | null;
  busy: boolean;
  err: string | null;
  onConfirm: (input: { declared_part_id?: string; declared_name?: string; program?: string }, label: string) => void;
  onNotThis: () => void;
}) {
  const m = model.match;
  return (
    <div
      data-testid="identity-closest-card"
      style={{
        border: `1px dashed ${C.hair}`,
        borderLeft: `3px dashed ${C.ink45}`,
        borderRadius: 14,
        background: C.sunken,
        padding: "16px 18px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <Kicker color={C.ink45}>CLOSEST IN YOUR LIBRARY · LOW CONFIDENCE</Kicker>
        <span
          data-testid="identity-closest-prov"
          title={m.provenance}
          style={{
            display: "inline-flex", alignItems: "center", gap: 6, fontFamily: MONO,
            fontSize: 9.5, letterSpacing: "0.04em", color: C.ink45,
            border: `1px dashed ${C.hair}`, borderRadius: 999, padding: "2px 9px",
          }}
        >
          <span aria-hidden style={{ color: C.user }}>◆</span>
          RETRIEVED · your part library
        </span>
      </div>

      {confirmed ? (
        <>
          <p data-testid="identity-closest-confirmed" style={{ margin: "10px 0 0", fontSize: 15, fontWeight: 500, color: C.ink }}>
            ✓ Identity confirmed — {confirmed}
          </p>
          <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45 }}>
            saved to your part library as{" "}
            <span style={{ color: C.user }}>● USER</span> — future look-alike parts will carry it.
          </p>
        </>
      ) : (
        <>
          {/* Lead: the closest designation — phrased as a QUESTION, never asserted. */}
          <p data-testid="identity-closest-lead" style={{ margin: "10px 0 0", fontSize: 15, lineHeight: 1.35, color: C.ink70, fontWeight: 500 }}>
            {model.lead}
            {model.program && (
              <span style={{ fontFamily: MONO, fontSize: 11, fontWeight: 400, color: C.ink55 }}>{" "}· {model.program}</span>
            )}
          </p>

          {/* Confidence % + explicit low-confidence pill (real fields). */}
          <div style={{ margin: "9px 0 0", display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
            <span
              data-testid="identity-closest-confidence"
              style={{ fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.06em", color: C.ink45, border: `1px dashed ${C.ink45}`, borderRadius: 999, padding: "2px 9px" }}
            >
              {model.pct}% · LOW CONFIDENCE
            </span>
            <span style={{ fontFamily: MONO, fontSize: 9.5, color: C.ink45 }}>
              geometry {(m.geometry_similarity * 100).toFixed(0)}%
              {m.name_similarity != null ? ` · name ${(m.name_similarity * 100).toFixed(0)}%` : " · name n/a"}
            </span>
          </div>

          {/* Honest caveat — this is a hint, not a confident match. */}
          <p style={{ margin: "9px 0 0", fontSize: 11.5, lineHeight: 1.5, color: C.ink55 }}>
            {model.caveat}
          </p>

          {err && (
            <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.fail }}>{err}</p>
          )}

          {/* Actions — the user decides; the system never asserts. */}
          <div style={{ marginTop: 13, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <GhostButton
              disabled={busy || !meshHash}
              title={meshHash ? "Confirm this identity onto your part library" : "mesh hash unavailable"}
              onClick={() =>
                onConfirm(
                  {
                    declared_part_id: m.declared_part_id ?? undefined,
                    declared_name: m.declared_name ?? undefined,
                    program: m.program ?? undefined,
                  },
                  model.lead.replace(/^Closest in your library: /, "")
                )
              }
            >
              {busy ? "Confirming…" : "Yes, confirm this"}
            </GhostButton>
            <GhostButton disabled={busy} onClick={onNotThis}>Not this</GhostButton>
          </div>
        </>
      )}
    </div>
  );
}

function VerdictBanner({
  result,
  makeNow,
  nav,
  onReverify,
  onRetryCost,
}: {
  result: VerifyResult;
  makeNow: ReturnType<typeof makeNowEstimate>;
  nav: Nav;
  onReverify: () => void;
  onRetryCost: () => void;
}) {
  const { validation, validationError, cost, costError, costGeometryInvalid, verification } = result;

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

  // No makeability block (no inventory + no declared world). The banner now branches
  // on what the engine ACTUALLY returned — it never claims a computation that did not
  // happen. Three honest states:
  //   1. NOTHING computed (parse/tessellation failed) → "COULD NOT ANALYZE".
  //   2. routing + DFM computed but NO should-cost      → "SHOULD-COST UNAVAILABLE".
  //   3. a real should-cost record                      → "SHOULD-COST COMPUTED".
  const routeDfm = routeDfmOutcome(
    routeScopedDfmVerdict(validation, proc),
    makeNow,
  );
  const dfm = routeDfm.verdict;

  // 1 · The engine returned nothing — no routing, no DFM, no cost. This is the part
  //     that failed to tessellate. Say EXACTLY that; never a fabricated "computed".
  if (!validation && !cost) {
    const reason = costError || validationError || null;
    const failure = analysisFailureCopy(reason);
    return (
      <BannerFrame borderColor={C.cond} bg="rgba(150,102,20,0.045)">
        <Kicker color={C.cond}>ANALYSIS INTERRUPTED · NO VERDICT PRODUCED</Kicker>
        <p style={{ margin: "10px 0 0", fontSize: 24, fontWeight: 400, letterSpacing: "-0.015em", lineHeight: 1.25 }}>
          {failure.title}
        </p>
        <p style={{ margin: "8px 0 0", fontSize: 14, lineHeight: 1.6, color: C.ink60, maxWidth: 560 }}>
          {reason ? (
            <><span style={{ fontFamily: MONO, fontSize: 12, color: C.ink55 }}>{reason}</span>{" "}</>
          ) : (
            <>{failure.explanation} </>
          )}
          No routing, DFM, or should-cost verdict was produced, and nothing here is estimated.{" "}
          {failure.action}
        </p>
        <div style={{ marginTop: 14 }}>
          <GhostButton onClick={onReverify}>Retry verification →</GhostButton>
        </div>
      </BannerFrame>
    );
  }

  // 2 · Routing + DFM ran, but the should-cost record is unavailable. The kicker does
  //     NOT claim SHOULD-COST COMPUTED, and the body names only what actually ran.
  if (!cost) {
    const color = dfm === "fail" ? C.fail : C.cond;
    const makeabilityReason = result.machinesError
      ? `The machine floor could not be loaded (${result.machinesError}).`
      : result.machines.length === 0 && !result.envDeclared
        ? "Machine fit was not evaluated because no machines or service conditions are declared."
        : "Machine fit was not returned with this partial result.";
    return (
      <BannerFrame borderColor={color} bg="rgba(23,24,26,0.015)">
        <Kicker color={color}>DFM {dfm.toUpperCase()} · RESOURCE COST INTERRUPTED</Kicker>
        <p style={{ margin: "10px 0 0", fontSize: 24, fontWeight: 400, letterSpacing: "-0.015em", lineHeight: 1.25 }}>
          Routing and DFM are ready. Cost needs another try.
        </p>
        <p style={{ margin: "8px 0 0", fontSize: 14, lineHeight: 1.6, color: C.ink60, maxWidth: 560 }}>
          Your successful geometry and DFM analysis is preserved. The resource-cost service did not return a record
          {costError ? <> (<span style={{ fontFamily: MONO, fontSize: 12, color: C.ink55 }}>{costError}</span>)</> : null}.{" "}
          {makeabilityReason} Existing saved data is unchanged.
        </p>
        <div style={{ marginTop: 14, display: "flex", gap: 9, flexWrap: "wrap" }}>
          <GhostButton primary onClick={onRetryCost}>Retry cost only →</GhostButton>
          <GhostButton onClick={onReverify}>Rerun full verification</GhostButton>
        </div>
        {savedCta}
      </BannerFrame>
    );
  }

  // 3a · The route has a real cost but fails route-specific DFM. Keep the cost
  //      for comparison/redesign, while making it impossible to read as an
  //      as-is manufacturing recommendation.
  if (routeDfm.blocked) {
    const blocker = routeDfm.primaryBlocker?.replace(/[.!?]+$/, "") ?? null;
    return (
      <BannerFrame borderColor={C.fail} bg="rgba(194,69,58,0.03)">
        <Kicker color={C.fail}>VERDICT · ROUTE DFM BLOCKED · SHOULD-COST CONDITIONAL</Kicker>
        <p style={{ margin: "10px 0 0", fontSize: 24, fontWeight: 400, letterSpacing: "-0.015em", lineHeight: 1.25 }}>
          {proc && unit != null ? (
            <>
              Conditional should-cost {USD(unit)}/unit on {procLabel(proc)}
              {makeNow ? <span style={{ fontSize: 14, color: C.ink45 }}> at qty {NUM(makeNow.quantity)}</span> : null}
            </>
          ) : (
            <>Route blocked as modeled</>
          )}
        </p>
        <p style={{ margin: "8px 0 0", fontSize: 14, lineHeight: 1.6, color: C.ink60, maxWidth: 620 }}>
          This route has a computed comparison cost, but it is not makeable as modeled.
          {blocker ? <> <span style={{ fontWeight: 500 }}>{blocker}.</span></> : null}{" "}
          Keep the cost for route comparison or redesign; do not treat it as an as-is manufacturing recommendation.
        </p>
        {savedCta}
      </BannerFrame>
    );
  }

  // 3b · A real should-cost record whose selected route is not blocked.
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
        ) : (
          <>Should-cost computed</>
        )}
      </p>
      <p style={{ margin: "8px 0 0", fontSize: 14, lineHeight: 1.6, color: C.ink60, maxWidth: 560 }}>
        The engine returned routing, route DFM, and a glass-box should-cost.{dfm === "issues" ? " This route carries DFM advisories; review them before release." : ""} Whether it&apos;s makeable{" "}
        <span style={{ fontWeight: 500 }}>on your machines</span> is the makeability verification — not evaluated here
        because no machines and no service conditions are declared. Declare your floor or the service conditions to resolve it, never assumed.
      </p>
      {savedCta}
    </BannerFrame>
  );
}

function BannerFrame({ children, borderColor, bg }: { children: ReactNode; borderColor: string; bg: string }) {
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
          ? "the declared service conditions were applied — no candidate material on the shortlisted routes is excluded by them."
          : "no service conditions declared — materials are verified at ambient. Use ‘Make this verdict yours’ below to gate them by NACE MR0175 / HDT."}
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
  // Reconcile the pick with the MATERIAL-AWARE route. `v.best_process` is a pure
  // geometry-manufacturability ranking (resins float to the top for having the fewest
  // DFM constraints) and must never masquerade as "the" pick for, say, a steel part —
  // that contradicts the cost panel on the same screen. When the cost route has run
  // with a declared material, its make-now / recommended process is the true route
  // pick; only fall back to the geometry pick when no material-aware route exists.
  const materialAwarePick =
    result.cost?.decision?.make_now_process ??
    result.cost?.routing?.recommended_process ??
    null;
  const pick = materialAwarePick ?? v.best_process;
  const pickIsMaterialAware = materialAwarePick != null;
  const sorted = [...v.process_scores].sort((a, b) => b.score - a.score);
  const rows = sorted.slice(0, 6);
  // Guarantee the actual route pick is visible even if geometry ranks it outside top-6.
  if (pick && !rows.some((p) => p.process === pick)) {
    const pickRow = sorted.find((p) => p.process === pick);
    if (pickRow) rows.push(pickRow);
  }
  return (
    <div style={{ marginTop: 12, display: "flex", flexDirection: "column" }}>
      {rows.map((ps) => {
        const isPick = ps.process === pick;
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
                  {pickIsMaterialAware ? "ROUTE PICK" : "GEOMETRY PICK"}
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
        overall {v.overall_verdict} · DFM scores from POST /validate ·{" "}
        {pickIsMaterialAware
          ? `pick reconciled to the material-aware route (${procLabel(pick)})`
          : "pick is geometry-only — declare a material for the material-aware route"}
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

function DecideHallmark({
  result,
  decision,
  setDecision,
  nav,
}: {
  result: VerifyResult;
  decision: CostDisposition | null;
  setDecision: (d: CostDisposition | null) => void;
  nav: Nav;
}) {
  const toast = useToast();
  const saved = result.cost?.saved;
  const est = result.cost ? makeNowEstimate(result.cost) : null;
  const inhouseBlocked = routeDfmOutcome(
    result.validation?.overall_verdict,
    est,
  ).blocked;
  const validated = est?.confidence?.validated ?? false;
  const decidedLabel = costDispositionLabel(decision);
  const [loadingSaved, setLoadingSaved] = useState(Boolean(saved?.id));
  const [saving, setSaving] = useState<
    CostDisposition | "withdraw" | "note" | null
  >(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [loadVersion, setLoadVersion] = useState(0);
  const [persistedAt, setPersistedAt] = useState<string | null>(null);
  const [dispositionNote, setDispositionNote] = useState("");
  const [persistedDispositionNote, setPersistedDispositionNote] = useState("");
  // Real, verbatim id of the persisted cost-decision artifact (never the design's
  // fixture "V-0117"). A short handle for the line; the full record opens in Records.
  const shortId = saved?.id ? `#${saved.id.slice(0, 8)}` : null;
  const recordedDate = new Date(persistedAt ?? Date.now()).toLocaleDateString(
    "en-US",
    { month: "short", day: "numeric", year: "numeric" }
  );

  useEffect(() => {
    if (!saved?.id) {
      setLoadingSaved(false);
      setSaveError(null);
      setPersistedAt(null);
      setDispositionNote("");
      setPersistedDispositionNote("");
      return;
    }

    let alive = true;
    setLoadingSaved(true);
    setSaveError(null);
    fetchCostDecision(saved.id)
      .then((record) => {
        if (!alive) return;
        const persisted = record.user_disposition;
        if (persisted != null && !isCostDisposition(persisted)) {
          throw new Error("The saved record contains an unsupported outcome");
        }
        setDecision(persisted ?? null);
        setPersistedAt(record.disposition_updated_at ?? null);
        setDispositionNote(record.disposition_note ?? "");
        setPersistedDispositionNote(record.disposition_note ?? "");
      })
      .catch((error) => {
        if (!alive) return;
        setSaveError(
          error instanceof Error ? error.message : "Could not load the saved outcome"
        );
      })
      .finally(() => {
        if (alive) setLoadingSaved(false);
      });
    return () => {
      alive = false;
    };
  }, [loadVersion, saved?.id, setDecision]);

  const choose = async (
    key: CostDisposition,
    label: string,
    action: "select" | "note" | "withdraw" = "select"
  ) => {
    if (loadingSaved || saving) return;
    if (key === "inhouse" && inhouseBlocked && action === "select") {
      toast("Make in-house is unavailable until revised CAD passes route DFM");
      return;
    }
    const noteOnly = action === "note";
    const withdrawing = action === "withdraw";
    const next = withdrawing ? null : key;

    // Honest fallback for an explicitly non-persisted engine run.
    if (!saved?.id) {
      setDecision(next);
      if (withdrawing) {
        setDispositionNote("");
        setPersistedDispositionNote("");
      } else {
        setPersistedDispositionNote(dispositionNote.trim());
      }
      if (withdrawing) toast(`Decision withdrawn — ${label}`);
      else if (noteOnly) toast("Outcome note updated for this verification");
      else toast(`${label} — noted on this verification`);
      if (key === "acquire" && !withdrawing && !noteOnly) nav("acquisition");
      return;
    }

    setSaving(withdrawing ? "withdraw" : noteOnly ? "note" : key);
    setSaveError(null);
    try {
      const updated = await setCostDecisionDisposition(
        saved.id,
        next,
        next ? dispositionNote : undefined
      );
      setDecision(updated.user_disposition);
      setPersistedAt(updated.disposition_updated_at ?? new Date().toISOString());
      setDispositionNote(updated.disposition_note ?? "");
      setPersistedDispositionNote(updated.disposition_note ?? "");
      if (withdrawing) {
        toast(`Decision withdrawn — saved to cost-decision ${shortId}`);
      } else if (noteOnly) {
        toast(`Outcome note saved to cost-decision ${shortId}`);
      } else {
        toast(`${label} — saved to cost-decision ${shortId}`);
        if (key === "acquire") nav("acquisition");
      }
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Could not save this decision";
      setSaveError(message);
      toast(`Decision not saved — ${message}`);
    } finally {
      setSaving(null);
    }
  };

  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <p style={{ margin: 0, fontSize: 15, fontWeight: 500, marginRight: "auto" }}>Decide</p>
        {COST_DISPOSITIONS.map((o) => {
          const on = decision === o.key;
          const blockedOption = o.key === "inhouse" && inhouseBlocked;
          return (
            <button
              key={o.key}
              type="button"
              data-testid={`verify-disposition-${o.key}`}
              aria-pressed={on}
              aria-busy={saving === o.key || (on && saving === "withdraw")}
              disabled={loadingSaved || Boolean(saving) || Boolean(saveError) || blockedOption}
              title={
                blockedOption
                  ? "Revise the CAD and pass route DFM before recording Make in-house"
                  : undefined
              }
              onClick={() => void choose(o.key, o.label)}
              style={{
                background: on ? C.ink : "none",
                border: `1px solid ${on ? C.ink : "#d8d8dc"}`,
                borderRadius: 999,
                color: on ? "#ffffff" : C.ink,
                padding: "9px 16px",
                fontSize: 12.5,
                fontWeight: 500,
                cursor:
                  loadingSaved || saving || saveError || blockedOption ? "not-allowed" : "pointer",
                opacity: loadingSaved || saving || saveError || blockedOption ? 0.55 : 1,
                fontFamily: "inherit",
                transition: "all 150ms",
              }}
            >
              {o.label}
            </button>
          );
        })}
        {decision && (
          <button
            type="button"
            data-testid="verify-disposition-withdraw"
            aria-label={`Withdraw ${decidedLabel ?? "recorded outcome"}`}
            aria-busy={saving === "withdraw"}
            disabled={loadingSaved || Boolean(saving) || Boolean(saveError)}
            onClick={() =>
              void choose(
                decision,
                decidedLabel ?? "recorded outcome",
                "withdraw"
              )
            }
            style={{ background: "none", border: "none", color: C.ink45, padding: "9px 8px", fontSize: 11, cursor: loadingSaved || saving || saveError ? "not-allowed" : "pointer", opacity: loadingSaved || saving || saveError ? 0.55 : 1, fontFamily: MONO, textDecoration: "underline", textUnderlineOffset: 3 }}
          >
            Withdraw
          </button>
        )}
      </div>

      {inhouseBlocked && (
        <p data-testid="verify-disposition-route-block" style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.fail, lineHeight: 1.6 }}>
          Route DFM is blocked · Make in-house is locked until revised CAD passes. Choose Redesign, Make outside, or Acquire capability for this record.
        </p>
      )}

      {loadingSaved ? (
        <p data-testid="verify-disposition-status" style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink45, lineHeight: 1.6 }}>
          loading the saved outcome for cost-decision {shortId}…
        </p>
      ) : saveError ? (
        <div data-testid="verify-disposition-error" style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 10.5, color: C.fail, lineHeight: 1.6 }}>
            Decision controls paused — {saveError}. Nothing was changed.
          </p>
          <GhostButton onClick={() => setLoadVersion((version) => version + 1)}>
            Retry
          </GhostButton>
        </div>
      ) : saving ? (
        <p data-testid="verify-disposition-status" style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink45, lineHeight: 1.6 }}>
          {saving === "withdraw"
            ? "Withdrawing the outcome…"
            : saving === "note"
              ? "Saving the outcome note…"
              : "Saving the outcome…"}
        </p>
      ) : decidedLabel ? (
        <p data-testid="verify-disposition-status" style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.pass, lineHeight: 1.6, animation: "vtraceIn 300ms cubic-bezier(0.2,0,0,1) both" }}>
          ✓ {decidedLabel} — recorded {recordedDate}
          {saved ? (
            <>
              {" "}· saved and auditable on cost-decision <span style={{ color: C.ink }}>{shortId}</span>
            </>
          ) : (
            " · this session only (persistence off)"
          )}
        </p>
      ) : (
        <p data-testid="verify-disposition-status" style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40, lineHeight: 1.6 }}>
          next → pick one above · your choice
          {saved ? " will be saved to this cost-decision record" : " is session-only because record persistence is off"}.
        </p>
      )}

      <div
        data-testid="verify-disposition-note-editor"
        style={{ marginTop: 14, borderTop: `1px solid ${C.hair}`, paddingTop: 12 }}
      >
        <label
          htmlFor="verify-disposition-note"
          style={{ display: "block", fontFamily: MONO, fontSize: 10, color: C.ink45, letterSpacing: "0.08em" }}
        >
          OUTCOME NOTE — OPTIONAL
        </label>
        <textarea
          id="verify-disposition-note"
          data-testid="verify-disposition-note"
          value={dispositionNote}
          maxLength={COST_DISPOSITION_NOTE_MAX_LENGTH}
          disabled={loadingSaved || Boolean(saving) || Boolean(saveError)}
          onChange={(event) => setDispositionNote(event.target.value)}
          placeholder="Why this action was chosen, constraints, owner, or next review point"
          aria-describedby="verify-disposition-note-help verify-disposition-note-count"
          style={{ width: "100%", minHeight: 78, marginTop: 7, resize: "vertical", border: `1px solid ${C.hair}`, borderRadius: 10, padding: "10px 12px", background: "#ffffff", color: C.ink, fontFamily: "inherit", fontSize: 12.5, lineHeight: 1.5 }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginTop: 7 }}>
          <p id="verify-disposition-note-help" style={{ margin: 0, flex: 1, minWidth: 220, fontFamily: MONO, fontSize: 9.5, color: C.ink40, lineHeight: 1.5 }}>
            {saved
              ? "saved beside the immutable cost record and included in governance exports"
              : "session-only because record persistence is off"}
          </p>
          <span id="verify-disposition-note-count" style={{ fontFamily: MONO, fontSize: 9.5, color: C.ink40 }}>
            {dispositionNote.length}/{COST_DISPOSITION_NOTE_MAX_LENGTH}
          </span>
          <button
            type="button"
            data-testid="verify-disposition-note-save"
            aria-busy={saving === "note"}
            disabled={
              !decision ||
              loadingSaved ||
              Boolean(saving) ||
              Boolean(saveError) ||
              dispositionNote.trim() === persistedDispositionNote
            }
            onClick={() =>
              decision &&
              void choose(
                decision,
                costDispositionLabel(decision) ?? "Outcome",
                "note"
              )
            }
            style={{ border: `1px solid ${C.hair}`, borderRadius: 999, padding: "7px 13px", background: "transparent", color: C.ink, fontFamily: "inherit", fontSize: 11.5, cursor: !decision || loadingSaved || saving || saveError || dispositionNote.trim() === persistedDispositionNote ? "not-allowed" : "pointer", opacity: !decision || loadingSaved || saving || saveError || dispositionNote.trim() === persistedDispositionNote ? 0.5 : 1 }}
          >
            Save note
          </button>
        </div>
        {!decision && dispositionNote.length > 0 && (
          <p style={{ margin: "7px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink45 }}>
            choose an outcome above to save this note
          </p>
        )}
      </div>

      <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <GhostButton onClick={() => nav("records")} disabled={!saved}>
          {saved ? "Open the record →" : "Saving is off"}
        </GhostButton>
        <span style={{ fontFamily: MONO, fontSize: 9.5, color: C.ink40, lineHeight: 1.5, flex: 1, minWidth: 180 }}>
          {saved
            ? "the computed evidence stays immutable; the recorded outcome persists across refresh, login, exports, and the Records view."
            : "record-keeping is turned off for this run — the numbers above are live, but nothing was written to your records."}
        </span>
      </div>

      <div style={{ marginTop: 16, borderTop: `1px solid #efeff2`, paddingTop: 14, display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{ flex: 1 }}>
          <ConfidenceBand validated={validated} pointFraction={0.5} />
          <p style={{ margin: "7px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink45, lineHeight: 1.6 }}>
            {validated
              ? "this verdict is validated — checked against your actuals."
              : "this verdict is unvalidated — an assumption band, not yet checked against your actuals · n=0. It firms up once your real costs come back."}
          </p>
        </div>
        <GhostButton onClick={() => nav("calibration")}>How estimates get validated →</GhostButton>
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
 *   • natural phrases for verdict, materials, drivers, time, and crossover map
 *      to deterministic reads of this same report.
 *   • anything outside the grammar → REFUSED; the engine never invents an answer.
 * No design fixtures, no fabricated figures — every number is selected from a
 * real response or the ask is refused.
 * ═══════════════════════════════════════════════════════════════════════════ */

type DockState =
  | { t: "idle" }
  | { t: "loading" }
  | { t: "routes"; data: Extract<RouteCompareResult, { status: "ok" }> }
  | { t: "cost"; data: CostAtQtyResult }
  | { t: "saved"; data: CostComparison; otherId: string }
  | { t: "verdict"; data: VerdictExplanationResult }
  | { t: "materials"; data: MaterialsResult }
  | { t: "drivers"; data: DriverReadoutResult }
  | { t: "time"; data: TimeReadoutResult }
  | { t: "crossover"; data: CrossoverReadoutResult }
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
    else if (p.kind === "explain_verdict") setState({ t: "verdict", data: explainVerdict(cost) });
    else if (p.kind === "materials") setState({ t: "materials", data: materialsForReport(cost) });
    else if (p.kind === "drivers") setState({ t: "drivers", data: driverReadout(cost, p.qty) });
    else if (p.kind === "time") setState({ t: "time", data: timeReadout(cost, p.qty) });
    else if (p.kind === "crossover") setState({ t: "crossover", data: crossoverReadout(cost) });
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
      {state.t === "verdict" && <VerdictArtifact data={state.data} onClose={clear} />}
      {state.t === "materials" && <MaterialsArtifact data={state.data} onClose={clear} />}
      {state.t === "drivers" && <DriversArtifact data={state.data} onClose={clear} />}
      {state.t === "time" && <TimeArtifact data={state.data} onClose={clear} />}
      {state.t === "crossover" && <CrossoverArtifact data={state.data} onClose={clear} />}
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
                ? "Ask the engine — “why can we make it?” · “cost drivers at qty 500”"
                : running
                  ? "computing the walk…"
                  : "Load a part above — the engine answers only about a computed part."
            }
            style={{ flex: 1, minWidth: 0, background: "none", border: "none", fontSize: 13, color: C.ink, fontFamily: "inherit" }}
          />
          <button
            type="button"
            onClick={submit}
            disabled={!canAsk}
            aria-label="Ask"
            title="Ask the engine"
            style={{
              flexShrink: 0,
              width: 44,
              height: 44,
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
        <AskChip label="Why this verdict?" disabled={!canAsk} onClick={() => cost && setState({ t: "verdict", data: explainVerdict(cost) })} />
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
        <span>answers are deterministic engine artifacts — verdict, materials, drivers, hours, cost, routes, and saved records</span>
      </p>
    </div>
  );
}

const ARTIFACT_STYLE: CSSProperties = {
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

function MonoRow({ label, value }: { label: string; value: ReactNode }) {
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

function VerdictArtifact({ data, onClose }: { data: VerdictExplanationResult; onClose: () => void }) {
  const blockers = data.blockers.slice(0, 3);
  return (
    <div style={ARTIFACT_STYLE}>
      <ArtifactHeader kicker="ENGINE OUTPUT — VERDICT EXPLANATION" onClose={onClose} />
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
        <MonoRow label="status" value={data.status} />
        <MonoRow label="make-now route" value={data.makeNowProcess ? procLabel(data.makeNowProcess) : "withheld"} />
        <MonoRow label="material" value={data.makeNowMaterial ?? "withheld"} />
        <MonoRow label="DFM" value={data.dfmReady == null ? "not evaluated" : data.dfmReady ? `ready · ${data.dfmVerdict ?? "pass"}` : `blocked · ${data.dfmVerdict ?? "fail"}`} />
      </div>
      {blockers.length > 0 && (
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.fail, lineHeight: 1.6 }}>
          blockers: {blockers.join(" · ")}
        </p>
      )}
      {data.routingReasoning && (
        <p style={{ margin: "10px 0 0", fontSize: 12, lineHeight: 1.55, color: C.ink55 }}>{data.routingReasoning}</p>
      )}
      {data.note && (
        <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 10, color: C.ink40, lineHeight: 1.55 }}>engine note: {data.note}</p>
      )}
    </div>
  );
}

function MaterialsArtifact({ data, onClose }: { data: MaterialsResult; onClose: () => void }) {
  return (
    <div style={ARTIFACT_STYLE}>
      <ArtifactHeader kicker="ENGINE OUTPUT — MATERIAL SURVIVAL" onClose={onClose} />
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
        <MonoRow label="declared class" value={data.materialClass} />
        <MonoRow label="make-now material" value={data.makeNowMaterial ?? "withheld"} />
        <MonoRow
          label="surviving materials"
          value={data.surviving.length ? data.surviving.map((m) => `${m.material} (${m.processes.map(procLabel).join(", ")})`).join(" · ") : "none in costed routes"}
        />
        <MonoRow
          label="blocked materials"
          value={data.blocked.length ? data.blocked.map((m) => `${m.material} (${m.processes.map(procLabel).join(", ")})`).join(" · ") : "none"}
        />
      </div>
      <p style={{ margin: "8px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink35 }}>
        derived from each estimate&apos;s DFM-ready flag — no material is added client-side
      </p>
    </div>
  );
}

function DriversArtifact({ data, onClose }: { data: DriverReadoutResult; onClose: () => void }) {
  return (
    <div style={ARTIFACT_STYLE}>
      <ArtifactHeader kicker={`ENGINE OUTPUT — COST DRIVERS · qty ${NUM(data.snappedQty)}`} onClose={onClose} />
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
        <MonoRow label="route" value={data.process ? procLabel(data.process) : "withheld"} />
        <MonoRow label="unit cost" value={data.unit != null ? `${USD(data.unit)}/unit` : "withheld"} />
      </div>
      {data.drivers.length === 0 ? (
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40 }}>
          no driver rows on this estimate — none are invented
        </p>
      ) : (
        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
          {data.drivers.map((d) => (
            <p key={`${d.name}-${d.unit}`} style={{ margin: 0, display: "flex", alignItems: "center", gap: 8, fontFamily: MONO, fontSize: 10.5, color: C.ink55 }}>
              <span style={{ flex: 1 }}>{d.name}</span>
              <span style={{ color: C.ink }}>{d.value.toLocaleString("en-US", { maximumFractionDigits: 3 })}{d.unit ? ` ${d.unit}` : ""}</span>
              <ProvChip p={d.provenance} />
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function TimeArtifact({ data, onClose }: { data: TimeReadoutResult; onClose: () => void }) {
  return (
    <div style={ARTIFACT_STYLE}>
      <ArtifactHeader kicker={`ENGINE OUTPUT — HOURS & LEAD TIME · qty ${NUM(data.snappedQty)}`} onClose={onClose} />
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
        <MonoRow label="route" value={data.process ? procLabel(data.process) : "withheld"} />
        <MonoRow
          label="lead time"
          value={data.leadDays ? `${data.leadDays.low}-${data.leadDays.high} days · mid ${data.leadDays.mid}` : "withheld"}
        />
      </div>
      {data.timeDrivers.length > 0 ? (
        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
          {data.timeDrivers.map((d) => (
            <p key={`${d.name}-${d.unit}`} style={{ margin: 0, display: "flex", alignItems: "center", gap: 8, fontFamily: MONO, fontSize: 10.5, color: C.ink55 }}>
              <span style={{ flex: 1 }}>{d.name}</span>
              <span style={{ color: C.ink }}>{d.value.toLocaleString("en-US", { maximumFractionDigits: 3 })} {d.unit}</span>
              <ProvChip p={d.provenance} />
            </p>
          ))}
        </div>
      ) : (
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40 }}>
          this estimate carries lead-time days but no separate hour driver rows
        </p>
      )}
    </div>
  );
}

function CrossoverArtifact({ data, onClose }: { data: CrossoverReadoutResult; onClose: () => void }) {
  return (
    <div style={ARTIFACT_STYLE}>
      <ArtifactHeader kicker="ENGINE OUTPUT — MAKE-VS-BUY CROSSOVER" onClose={onClose} />
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
        <MonoRow label="owned route" value={data.makeNowProcess ? procLabel(data.makeNowProcess) : "withheld"} />
        <MonoRow label="acquire route" value={data.toolingProcess ? procLabel(data.toolingProcess) : "none"} />
        <MonoRow label="crossover" value={data.crossover != null ? `${NUM(data.crossover)} units` : "none computed"} />
        <MonoRow label="tooling DFM" value={data.toolingDfmReady == null ? "not applicable" : data.toolingDfmReady ? "ready" : "conditional redesign"} />
      </div>
      {data.note && (
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40, lineHeight: 1.6 }}>engine note: {data.note}</p>
      )}
    </div>
  );
}

/** The honest refusal — never a fabricated answer. */
function RefusalArtifact({ title, reason, nl, onClose }: { title: string; reason: string; nl: boolean; onClose: () => void }) {
  return (
    <div style={{ maxWidth: 720, marginBottom: 12, border: `1.5px dashed #d3d3d8`, borderRadius: 14, padding: "16px 18px", animation: "vstepIn 300ms cubic-bezier(0.2,0,0,1) both" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <p style={{ margin: 0, fontSize: 14, fontWeight: 500 }}>{title}</p>
        {nl && <span style={{ fontFamily: MONO, fontSize: 9.5, color: C.ink40 }}>DETERMINISTIC REFUSAL</span>}
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
