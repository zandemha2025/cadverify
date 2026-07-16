"use client";

import { ArrowRight, CheckCircle2, TriangleAlert } from "lucide-react";
import type { CSSProperties } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { makeNowEstimate, routeDfmOutcome } from "@/lib/verify/derive";
import { partitionDfmByRoute, routeScopedDfmVerdict } from "@/lib/dfm-scope";
import type { VerifyResult } from "@/lib/verify/run";
import { C, MONO, NUM, procLabel, USD } from "@/lib/verify/tokens";

export function GuidedResultSummary({
  open,
  result,
  onOpenChange,
  onUpload,
  onBack,
}: {
  open: boolean;
  result: VerifyResult | null;
  onOpenChange: (open: boolean) => void;
  onUpload: () => void;
  onBack: () => void;
}) {
  const estimate = result?.cost ? makeNowEstimate(result.cost) : null;
  const recommendedProcess = estimate?.process ?? result?.validation?.best_process ?? null;
  const dfmPartition = result?.validation
    ? partitionDfmByRoute(result.validation, recommendedProcess)
    : null;
  const scopedValidationVerdict = routeScopedDfmVerdict(
    result?.validation,
    recommendedProcess,
  );
  const outcome = routeDfmOutcome(scopedValidationVerdict, estimate);
  const dfmVerdict = outcome.verdict;
  const firstIssue = dfmPartition?.route[0]?.issue ?? null;
  const priorityFixes = dfmPartition?.counts.total ?? null;

  // Cost geometry is preferred when present, but validation geometry is still a
  // real measurement and must survive a partial cost-service failure.
  const costGeometry = result?.cost?.geometry ?? result?.costGeometryInvalid?.geometry ?? null;
  const validationGeometry = result?.validation?.geometry ?? null;
  const measuredSize = costGeometry?.bbox_mm ?? validationGeometry?.bounding_box_mm ?? null;
  const volumeCm3 = costGeometry?.volume_cm3 ?? (
    validationGeometry ? validationGeometry.volume_mm3 / 1_000 : null
  );
  const faceCount = costGeometry?.face_count ?? validationGeometry?.faces ?? null;
  const watertight = costGeometry?.watertight ?? validationGeometry?.is_watertight ?? null;
  const hasMeasuredGeometry = measuredSize != null || volumeCm3 != null || faceCount != null;

  const analysisAvailable = !!(
    result?.validation ||
    result?.cost ||
    result?.costGeometryInvalid
  );
  const resultTone = result?.costGeometryInvalid
    ? C.fail
    : dfmVerdict === "pass"
      ? C.pass
      : dfmVerdict === "fail"
        ? C.fail
        : dfmVerdict === "issues"
          ? C.cond
          : C.def;
  const ResultIcon = resultTone === C.pass ? CheckCircle2 : TriangleAlert;

  const headline = result?.costGeometryInvalid
    ? "Geometry measured. The model needs repair."
    : dfmVerdict === "pass"
      ? "Geometry understood. No blocking DFM issues found."
      : dfmVerdict === "issues"
        ? priorityFixes && priorityFixes > 0
          ? `Geometry understood. ${NUM(priorityFixes)} issue${priorityFixes === 1 ? "" : "s"} need review.`
          : "Geometry understood. DFM issues need review."
        : dfmVerdict === "fail"
          ? "This part is not ready as modeled."
          : result?.validation
            ? "Geometry understood. DFM is incomplete."
            : hasMeasuredGeometry
              ? "Geometry measured. DFM needs another try."
              : "The example could not be analyzed.";

  const resultDetail = result?.costGeometryInvalid
    ? "Costing stopped at the geometry gate. Any routing and measurements that finished remain visible below."
    : result?.validation
      ? "This is the engine's geometry and DFM result. The recommended route and first action follow in decision order."
      : hasMeasuredGeometry
        ? "Measurements finished, but the engine did not return a complete DFM verdict."
        : result?.validationError ?? result?.costError ?? "No analysis record was returned.";

  const issueTitle = firstIssue?.message
    ?? outcome.primaryBlocker
    ?? result?.costGeometryInvalid?.message
    ?? "No priority issue was returned in this result.";
  const issueEvidence = firstIssue
    ? formatIssueEvidence(firstIssue.measured_value ?? null, firstIssue.required_value ?? null)
    : null;
  const issueDetail = firstIssue?.fix_suggestion
    ?? (issueTitle.startsWith("No priority issue")
      ? dfmVerdict === "pass"
        ? "There is no engine-authored first action to take before reviewing the full report."
        : "The analysis is partial, so absence of a returned issue is not a pass."
      : "Open the technical result for the full gate evidence and affected geometry.");
  const issueTone = firstIssue
    ? firstIssue.severity.toLowerCase() === "error" ? C.fail : C.cond
    : outcome.primaryBlocker || result?.costGeometryInvalid
      ? C.fail
      : dfmVerdict === "pass"
        ? C.pass
        : C.def;

  const costTitle = estimate
    ? `${USD(estimate.unit_cost_usd)} per unit`
    : result?.costGeometryInvalid
      ? "Resource cost stopped at the geometry gate."
      : result?.validation
        ? "Routing and DFM are ready. Resource cost needs another try."
        : "No resource cost was produced because analysis did not finish.";
  const costDetail = estimate
    ? `At quantity ${NUM(estimate.quantity)} · engine-computed resource cost, not a supplier quote.`
    : result?.costGeometryInvalid
      ? result.costGeometryInvalid.message
      : result?.validation
        ? `${result.costError ?? "The cost service did not return a record."} Your geometry and DFM result is still available.`
        : result?.costError ?? "The engine did not return a cost record.";

  const shopFit = shopFitSummary(result);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        aria-describedby="guided-result-description"
        className="max-h-[min(92vh,820px)] max-w-[760px] gap-0 overflow-y-auto p-0"
        style={{
          borderColor: C.hair,
          borderRadius: 22,
          background: C.panel,
          color: C.ink,
          boxShadow: "0 34px 100px rgba(23,24,26,0.22)",
        }}
      >
        <div style={{ padding: "30px" }}>
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, fontWeight: 650, letterSpacing: "0.14em", color: analysisAvailable ? C.measured : C.fail }}>
            {analysisAvailable
              ? "EXAMPLE ANALYZED · REAL ENGINE OUTPUT"
              : "EXAMPLE INCOMPLETE · NO VERDICT PRODUCED"}
          </p>
          <DialogTitle style={{ marginTop: 10, color: C.ink, fontSize: 29, fontWeight: 450, lineHeight: 1.15, letterSpacing: "-0.025em" }}>
            The manufacturing answer, in decision order.
          </DialogTitle>
          <DialogDescription id="guided-result-description" style={{ marginTop: 9, color: C.ink55, fontSize: 13.5, lineHeight: 1.65 }}>
            Start with geometry and DFM. Route, first issue, measured evidence,
            resource cost, and shop fit follow without turning missing data into a verdict.
          </DialogDescription>

          <section
            style={{
              marginTop: 22,
              border: `1px solid ${C.hair}`,
              borderTop: `3px solid ${resultTone}`,
              borderRadius: 16,
              background: C.sunken,
              padding: "20px 21px 18px",
            }}
          >
            <div style={{ display: "flex", alignItems: "flex-start", gap: 13 }}>
              <span aria-hidden style={{ display: "grid", placeItems: "center", color: resultTone, paddingTop: 2 }}>
                <ResultIcon size={22} />
              </span>
              <div style={{ minWidth: 0 }}>
                <p style={eyebrow(resultTone)}>GEOMETRY / DFM · PRIMARY RESULT</p>
                <p style={{ margin: "7px 0 0", color: C.ink, fontSize: 23, fontWeight: 650, lineHeight: 1.25, letterSpacing: "-0.018em" }}>
                  {headline}
                </p>
                <p style={{ margin: "8px 0 0", color: C.ink55, fontSize: 12.5, lineHeight: 1.55 }}>
                  {resultDetail}
                </p>
              </div>
            </div>

            <div style={{ marginTop: 18, borderTop: `1px solid ${C.hair}`, paddingTop: 15 }}>
              <p style={eyebrow(C.measured)}>RECOMMENDED ROUTE</p>
              <p style={{ margin: "6px 0 0", color: C.ink, fontSize: 18, fontWeight: 650, lineHeight: 1.35 }}>
                {recommendedProcess ? procLabel(recommendedProcess) : "No manufacturing route returned"}
              </p>
              <p style={{ margin: "5px 0 0", color: C.ink55, fontSize: 11.5, lineHeight: 1.5 }}>
                {estimate
                  ? `${estimate.material} · selected from the engine's evaluated routes`
                  : recommendedProcess
                    ? "Selected by validation. Cost assumptions were not returned."
                    : "The engine did not produce a route for this result."}
              </p>
            </div>
          </section>

          <section style={{ marginTop: 14, borderLeft: `3px solid ${issueTone}`, padding: "5px 4px 5px 16px" }}>
            <p style={eyebrow(issueTone)}>FIRST ISSUE</p>
            <p style={{ margin: "7px 0 0", color: C.ink, fontSize: 15.5, fontWeight: 650, lineHeight: 1.4 }}>
              {issueTitle}
            </p>
            {issueEvidence ? (
              <p style={{ margin: "6px 0 0", color: C.measured, fontFamily: MONO, fontSize: 10.5, lineHeight: 1.5 }}>
                ● MEASURED · {issueEvidence}
              </p>
            ) : null}
            <p style={{ margin: "6px 0 0", color: C.ink55, fontSize: 11.5, lineHeight: 1.5 }}>
              {issueDetail}
            </p>
          </section>

          <section style={{ marginTop: 20, borderTop: `1px solid ${C.hair2}`, borderBottom: `1px solid ${C.hair2}`, padding: "15px 0 14px" }}>
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <p style={eyebrow(C.measured)}>MEASURED EVIDENCE</p>
              <p style={{ margin: 0, color: C.measured, fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.08em" }}>
                ● MEASURED FROM CAD
              </p>
            </div>
            <div className="grid grid-cols-2 gap-x-5 gap-y-4 sm:grid-cols-4" style={{ marginTop: 13 }}>
              <Evidence label="ENVELOPE" value={measuredSize ? `${measuredSize.map(formatMeasure).join(" × ")} mm` : "—"} />
              <Evidence label="VOLUME" value={volumeCm3 != null ? `${formatMeasure(volumeCm3)} cm³` : "—"} />
              <Evidence label="FACES" value={faceCount != null ? NUM(faceCount) : "—"} />
              <Evidence label="WATERTIGHT" value={watertight == null ? "—" : watertight ? "Yes" : "No"} />
            </div>
          </section>

          <div className="grid gap-3 sm:grid-cols-2" style={{ marginTop: 16 }}>
            <section style={{ border: `1px solid ${C.hair}`, borderRadius: 14, background: C.panel, padding: "15px 16px" }}>
              <p style={eyebrow(estimate ? C.shop : C.cond)}>
                RESOURCE COST · {estimate ? "SECONDARY" : "UNAVAILABLE"}
              </p>
              <p style={{ margin: "8px 0 0", color: C.ink, fontSize: 15.5, fontWeight: 650, lineHeight: 1.4 }}>
                {costTitle}
              </p>
              <p style={{ margin: "7px 0 0", color: C.ink55, fontSize: 11.5, lineHeight: 1.5 }}>
                {costDetail}
              </p>
            </section>

            <section style={{ border: `1px solid ${C.hair}`, borderRadius: 14, background: C.sunken, padding: "15px 16px" }}>
              <p style={eyebrow(C.def)}>SHOP FIT / UNCERTAINTY · NEUTRAL</p>
              <p style={{ margin: "8px 0 0", color: C.ink, fontSize: 15.5, fontWeight: 650, lineHeight: 1.4 }}>
                {shopFit.title}
              </p>
              <p style={{ margin: "7px 0 0", color: C.ink55, fontSize: 11.5, lineHeight: 1.5 }}>
                {shopFit.detail}
              </p>
            </section>
          </div>

          <div style={{ marginTop: 22, display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 10, flexWrap: "wrap", borderTop: `1px solid ${C.hair2}`, paddingTop: 18 }}>
            <button type="button" onClick={onBack} style={summaryButton(true)}>
              Back to start
            </button>
            <button type="button" onClick={onUpload} style={summaryButton(true)}>
              Check my own CAD
            </button>
            <button type="button" onClick={() => onOpenChange(false)} style={summaryButton(false)}>
              Show full technical result <ArrowRight aria-hidden size={15} />
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Evidence({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p style={{ margin: 0, color: C.ink45, fontFamily: MONO, fontSize: 9, letterSpacing: "0.1em" }}>{label}</p>
      <p style={{ margin: "5px 0 0", color: C.ink, fontSize: 12.5, fontWeight: 650, lineHeight: 1.35 }}>{value}</p>
    </div>
  );
}

function formatMeasure(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function formatIssueEvidence(measured: number | null, required: number | null): string | null {
  if (measured == null && required == null) return null;
  if (measured != null && required != null) {
    return `measured ${formatMeasure(measured)} · threshold ${formatMeasure(required)}`;
  }
  return measured != null
    ? `measured ${formatMeasure(measured)}`
    : `threshold ${formatMeasure(required as number)}`;
}

function shopFitSummary(result: VerifyResult | null): { title: string; detail: string } {
  if (!result) {
    return {
      title: "Shop fit not checked in this result.",
      detail: "A machine-fit verdict was not returned.",
    };
  }
  if (result.machinesError) {
    return {
      title: "Machine inventory could not be loaded.",
      detail: `${result.machinesError} No shop-fit verdict is inferred from missing inventory.`,
    };
  }

  const verification = result.verification;
  if (verification?.inventory_declared === true) {
    return verification.best_machine
      ? {
          title: `Best declared-machine fit: ${verification.best_machine}`,
          detail: verification.note ?? `Engine verdict: ${humanizeVerdict(verification.verdict)}.`,
        }
      : {
          title: humanizeVerdict(verification.verdict),
          detail: verification.note ?? "The engine evaluated the declared floor but did not name a best machine.",
        };
  }
  if (verification?.inventory_declared === false || verification) {
    return {
      title: "Shop fit not checked — no machines declared.",
      detail: verification?.environment_declared
        ? "Service conditions were evaluated separately; machine fit needs a declared floor."
        : "Declare your machine floor to turn this neutral state into an in-house fit verdict.",
    };
  }
  return {
    title: "Shop fit not checked in this result.",
    detail: "No machine-fit verification block was returned. A partial cost failure is not treated as evidence that the part fits your floor.",
  };
}

function humanizeVerdict(verdict: string): string {
  const labels: Record<string, string> = {
    makeable_in_house: "Machine fit verified in-house",
    makeable_with_secondary_op: "In-house fit needs a secondary operation",
    makeable_not_on_owned: "Not makeable on the declared floor",
    makeable_outsource_only: "Outsource route only",
    environment_excluded: "Excluded by declared service conditions",
    not_makeable: "No makeable route verified",
    unknown: "Shop-fit verdict is incomplete",
  };
  return labels[verdict] ?? "Shop-fit verdict is incomplete";
}

function eyebrow(color: string): CSSProperties {
  return {
    margin: 0,
    color,
    fontFamily: MONO,
    fontSize: 9.5,
    fontWeight: 650,
    letterSpacing: "0.1em",
  };
}

function summaryButton(quiet: boolean): CSSProperties {
  return {
    minHeight: 40,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    border: `1px solid ${quiet ? C.hair : C.ink}`,
    borderRadius: 999,
    background: quiet ? C.panel : C.ink,
    color: quiet ? C.ink : "#fff",
    padding: "9px 15px",
    fontFamily: "inherit",
    fontSize: 11.5,
    fontWeight: 650,
    cursor: "pointer",
  };
}
