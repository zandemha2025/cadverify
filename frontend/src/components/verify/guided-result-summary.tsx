"use client";

import { ArrowRight, CheckCircle2, CircleDollarSign, Factory, TriangleAlert } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { makeNowEstimate, routeDfmOutcome } from "@/lib/verify/derive";
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
  const outcome = routeDfmOutcome(result?.validation?.overall_verdict, estimate);
  const priorityFixes = result?.validation?.priority_fixes.length ?? null;
  const machineFitKnown = (result?.machines.length ?? 0) > 0 || result?.verification != null;
  const geometry = result?.cost?.geometry ?? result?.costGeometryInvalid?.geometry ?? null;
  const geometryMeasured = result?.cost != null && result.costGeometryInvalid == null;
  const measuredSize = geometry
    ? geometry.bbox_mm.map((dimension) => NUM(dimension)).join(" × ")
    : null;
  const verdict =
    outcome.verdict === "pass"
      ? "No blocking DFM issues found"
      : outcome.verdict === "issues"
        ? "Possible, with issues to review"
        : outcome.verdict === "fail"
          ? "Not ready as modeled"
          : "Not enough information yet";

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
          <p style={{ margin: 0, fontFamily: MONO, fontSize: 10, fontWeight: 650, letterSpacing: "0.14em", color: C.pass }}>
            EXAMPLE COMPLETE · REAL ENGINE OUTPUT
          </p>
          <DialogTitle style={{ marginTop: 10, color: C.ink, fontSize: 29, fontWeight: 450, lineHeight: 1.15, letterSpacing: "-0.025em" }}>
            Here is the manufacturing answer.
          </DialogTitle>
          <DialogDescription id="guided-result-description" style={{ marginTop: 9, color: C.ink55, fontSize: 13.5, lineHeight: 1.65 }}>
            This sample was parsed and evaluated by the real engine. Start with these
            four answers; open the technical detail only when you want the evidence.
          </DialogDescription>

          <div className="grid gap-3 sm:grid-cols-2" style={{ marginTop: 22 }}>
            <Answer
              number="1"
              icon={<CheckCircle2 size={18} />}
              label="Did ProofShape understand the CAD?"
              value={geometryMeasured ? "Yes — geometry parsed and measured" : verdict}
              detail={
                geometryMeasured && geometry
                  ? `The engine measured a ${geometry.watertight ? "watertight " : ""}${measuredSize} mm solid.`
                  : result?.costError ?? "The engine could not produce usable geometry measurements."
              }
              tone={geometryMeasured ? C.pass : outcome.verdict === "fail" ? C.fail : C.cond}
            />
            <Answer
              number="2"
              icon={<Factory size={18} />}
              label="How would it be made?"
              value={estimate ? procLabel(estimate.process) : "Process withheld"}
              detail={estimate ? `${estimate.material} · selected from the engine's evaluated routes` : "No process was returned for this geometry."}
              tone={C.measured}
            />
            <Answer
              number="3"
              icon={<CircleDollarSign size={18} />}
              label="What should it cost?"
              value={estimate ? `${USD(estimate.unit_cost_usd)} per unit` : "Cost withheld"}
              detail={
                estimate
                  ? `At quantity ${NUM(estimate.quantity)} · assumption-based until you add your rates and actual results.`
                  : result?.costError ?? "The engine did not return a usable estimate."
              }
              tone={C.shop}
            />
            <Answer
              number="4"
              icon={<TriangleAlert size={18} />}
              label="What is still uncertain?"
              value={
                machineFitKnown
                  ? priorityFixes == null
                    ? "Nothing else was returned"
                    : priorityFixes === 0
                      ? "No priority design issues"
                      : `${NUM(priorityFixes)} design advisor${priorityFixes === 1 ? "y" : "ies"}`
                  : "Your shop-specific fit and price"
              }
              detail={
                machineFitKnown
                  ? "The technical report shows each advisory, its evidence, and the suggested fix."
                  : `Add your machines and rates to replace assumptions and check machine fit.${priorityFixes ? ` The detailed report also contains ${NUM(priorityFixes)} design advisories.` : ""}`
              }
              tone={machineFitKnown && !priorityFixes ? C.pass : C.cond}
            />
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

function Answer({
  number,
  icon,
  label,
  value,
  detail,
  tone,
}: {
  number: string;
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
  tone: string;
}) {
  return (
    <section style={{ minHeight: 164, border: `1px solid ${C.hair}`, borderRadius: 15, background: C.sunken, padding: "16px 17px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 9, color: tone }}>
        <span aria-hidden style={{ display: "grid", placeItems: "center" }}>{icon}</span>
        <span style={{ fontFamily: MONO, fontSize: 9.5, fontWeight: 650, letterSpacing: "0.1em" }}>ANSWER {number}</span>
      </div>
      <p style={{ margin: "11px 0 0", color: C.ink55, fontSize: 11.5, lineHeight: 1.45 }}>{label}</p>
      <p style={{ margin: "5px 0 0", color: C.ink, fontSize: 16, fontWeight: 650, lineHeight: 1.35 }}>{value}</p>
      <p style={{ margin: "7px 0 0", color: C.ink55, fontSize: 11.5, lineHeight: 1.5 }}>{detail}</p>
    </section>
  );
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
