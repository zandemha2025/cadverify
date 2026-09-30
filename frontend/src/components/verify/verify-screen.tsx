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
import {
  highestPriorityIssue,
  partitionDfmByRoute,
  routeScopedDfmVerdict,
} from "@/lib/dfm-scope";
import { C, MONO, USD, NUM, procLabel, statusColor, normProv } from "@/lib/verify/tokens";
import type { VerifyResult } from "@/lib/verify/run";
import type { CostReport } from "@/lib/api";
import {
  driverViews,
  makeNowEstimate,
  prototypeEstimate,
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
              onReverify={onReverify}
              onRetryCost={onRetryCost}
              onPickFile={onPickFile}
              nav={nav}
            />
          )}
        </div>

      </div>

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
  const firstFix = highestPriorityIssue(fixes)?.issue ?? null;
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


function Walk({
  result,
  scrubFrac,
  setScrubFrac,
  disclose,
  setDisclose,
  onReverify,
  onRetryCost,
  onPickFile,
  nav,
}: {
  result: VerifyResult;
  scrubFrac: number;
  setScrubFrac: (f: number) => void;
  disclose: string | null;
  setDisclose: (s: string | null) => void;
  onReverify: () => void;
  onRetryCost: () => void;
  onPickFile: () => void;
  nav: Nav;
}) {
  const { cost, costGeometryInvalid, machines, verification } = result;

  const bbox = geometryFromResult(result)?.bbox_mm ?? null;
  const makeNow = cost ? prototypeEstimate(cost) : null;
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
      {/* machine alert — shown when no machines declared */}
      {machines.length === 0 && (
        <div style={{ marginBottom: 14, border: `1px solid ${C.cond}`, borderRadius: 10, padding: "10px 14px", background: "rgba(180,120,0,0.04)", display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontFamily: MONO, fontSize: 12, color: C.cond, flexShrink: 0 }}>!</span>
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 11, color: C.ink55, lineHeight: 1.5 }}>
            Add your{" "}
            <button
              type="button"
              onClick={() => nav("machines")}
              style={{ background: "none", border: "none", padding: 0, fontFamily: "inherit", fontSize: "inherit", color: C.measured, cursor: "pointer", textDecoration: "underline" }}
            >
              machine floor
            </button>
            {" "}for accurate cost.
          </p>
        </div>
      )}

      {/* verdict banner */}
      <VerdictBanner
        result={result}
        makeNow={makeNow}
        nav={nav}
        onReverify={onReverify}
        onRetryCost={onRetryCost}
      />

      {/* ── DFM MANUFACTURABILITY ─────────────────────────────────────────── */}
      <div style={{ marginTop: 16 }}>
        <p style={{ margin: "0 0 8px", fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", color: C.ink45 }}>DFM MANUFACTURABILITY</p>

        {/* honest gate stop */}
        {gateStopped ? (
          <div style={{ border: `1.5px dashed rgba(194,69,58,0.4)`, borderRadius: 14, padding: "16px 20px", animation: "vstepIn 400ms cubic-bezier(0.2,0,0,1) 120ms both" }}>
            <p style={{ margin: 0, fontFamily: MONO, fontSize: 11, letterSpacing: "0.1em", color: C.fail }}>GEOMETRY INVALID</p>
            <p style={{ margin: "8px 0 0", fontSize: 13, lineHeight: 1.6, color: C.ink55 }}>
              {costGeometryInvalid?.message || "Geometry is invalid — DFM and cost cannot be computed."}
              {costGeometryInvalid?.geometry && (
                <span style={{ fontFamily: MONO, fontSize: 11, color: C.ink50 }}>
                  {" "}· {NUM(costGeometryInvalid.geometry.face_count)} faces · watertight {String(costGeometryInvalid.geometry.watertight)} · {costGeometryInvalid.geometry.volume_cm3.toFixed(2)} cm³
                </span>
              )}
            </p>
            <div style={{ marginTop: 12 }}>
              <GhostButton onClick={onReverify}>Repair &amp; re-upload →</GhostButton>
            </div>
          </div>
        ) : (
          /* combined materials + process physics card */
          <Card style={{ borderColor: C.hair, padding: "18px 20px" }}>
            {/* materials */}
            <div>
              <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.08em", color: C.ink45 }}>MATERIALS</p>
              <div style={{ marginTop: 10 }}>
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
                    service-condition filtering runs with makeability verification
                  </p>
                )}
              </div>
            </div>

            {/* divider */}
            <div style={{ margin: "18px 0", borderTop: `1px solid ${C.hair}` }} />

            {/* process physics */}
            <div>
              <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.08em", color: C.ink45 }}>PROCESS PHYSICS</p>
              <div style={{ marginTop: 10 }}>
                <ProcessPhysics result={result} />
              </div>
            </div>
          </Card>
        )}
      </div>

      {/* ── COST ANALYSIS ─────────────────────────────────────────────────── */}
      {!gateStopped && cost && (
        <div style={{ marginTop: 20 }}>
          <p style={{ margin: "0 0 8px", fontFamily: MONO, fontSize: 10, letterSpacing: "0.1em", color: C.ink45 }}>COST ANALYSIS</p>

          <Card style={{ borderColor: C.hair, padding: "18px 20px" }}>
            {/* resource cost — always first */}
            <div>
              <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.08em", color: C.ink45 }}>RESOURCE COST</p>
              <div style={{ marginTop: 10 }}>
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
              </div>
            </div>

            {/* what it really takes — below resource cost */}
            {makeNow && (
              <>
                <div style={{ margin: "18px 0", borderTop: `1px solid ${C.hair}` }} />
                <div>
                  <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, letterSpacing: "0.08em", color: C.ink45 }}>
                    COST DRIVERS
                    <span style={{ marginLeft: 10, color: C.ink35 }}>{procLabel(makeNow.process)} · {makeNow.material}</span>
                  </p>
                  <div style={{ marginTop: 10 }}>
                    <TimeAndResources est={makeNow} disclose={disclose} setDisclose={setDisclose} />
                  </div>
                </div>
              </>
            )}
          </Card>
        </div>
      )}

      {/* ── below the fold — identity, evidence, makeability ─────────────── */}
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

      {verification && (
        <div style={{ marginTop: 14 }}>
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
        </div>
      )}

      {/* try another file */}
      <div style={{ marginTop: 28, paddingTop: 20, borderTop: `1px solid ${C.hair}` }}>
        <button
          type="button"
          onClick={onPickFile}
          style={{ background: C.ink, color: "#fff", border: "none", borderRadius: 999, padding: "10px 24px", fontSize: 13.5, fontWeight: 500, cursor: "pointer", fontFamily: "inherit" }}
        >
          Try another file
        </button>
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
          ? "no materials excluded by the declared service conditions."
          : "no service conditions declared — verified at ambient."}
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
      {v.priority_fixes.length > 0 && (
        <p style={{ margin: "10px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40 }}>
          {v.priority_fixes.length} priority fix{v.priority_fixes.length === 1 ? "" : "es"} ·{" "}
          {pickIsMaterialAware ? `route pick: ${procLabel(pick)}` : "geometry pick — declare a material to refine"}
        </p>
      )}
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
          {active.errorBandPct != null && (
            <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 10, color: C.cond }}>
              ±{Math.round(active.errorBandPct)}% [assumption band] · this driver&apos;s honest error, verbatim
            </p>
          )}
        </div>
      )}

      <p style={{ margin: "12px 0 0", fontFamily: MONO, fontSize: 10.5, color: C.ink40, lineHeight: 1.7 }}>
        lead {lead.low_days.toFixed(1)}–{lead.high_days.toFixed(1)} days · tap a driver for its source
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
            {mix.groundedPct}% of drivers grounded · at qty {NUM(snappedQty)}
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

