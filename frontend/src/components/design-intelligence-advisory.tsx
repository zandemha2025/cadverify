"use client";

import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { BookOpenText, ChevronDown, ExternalLink, RotateCcw } from "lucide-react";
import {
  fetchAnalysisDesignIntelligence,
  fetchAnalysisFeedback,
  fetchDesignIntelligence,
  recordAnalysisFeedback,
  type AdvisoryFeedbackSignal,
  type DesignIntelligenceEvidence,
  type DesignIntelligenceFinding,
  type DesignIntelligenceFindingRef,
  type DesignIntelligenceResponse,
} from "@/lib/api";
import {
  canRecordAnalysisMemory,
  designIntelligenceEmptyMessage,
  designIntelligenceEnabled,
  evidenceTimeRange,
  isResearchOnly,
  safeEvidenceUrl,
} from "@/lib/design-intelligence";
import { useAuth } from "@/components/ui/auth-provider";
import { C, MONO } from "@/lib/verify/tokens";
import { Spinner } from "@/components/verify/primitives";

export function DesignIntelligenceAdvisory({
  finding,
  analysisId,
  findingRef,
  className,
}: {
  finding: DesignIntelligenceFinding;
  analysisId?: string | null;
  findingRef?: DesignIntelligenceFindingRef | null;
  className?: string;
}) {
  const { user } = useAuth();
  const canRecord = canRecordAnalysisMemory(user?.role);
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DesignIntelligenceResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [feedback, setFeedback] = useState<AdvisoryFeedbackSignal | null>(null);
  const [feedbackSaving, setFeedbackSaving] = useState(false);
  const [feedbackFailed, setFeedbackFailed] = useState(false);
  const findingFingerprint = [
    analysisId ?? "",
    findingRef?.scope ?? "",
    findingRef?.process ?? "",
    findingRef?.code ?? "",
    findingRef?.occurrence ?? "",
    finding.code,
    finding.severity,
    finding.message,
    finding.fix_suggestion ?? "",
    finding.process ?? "",
    finding.measured_value ?? "",
    finding.required_value ?? "",
  ].join("\u001f");
  const activeFingerprint = useRef(findingFingerprint);
  const requestGeneration = useRef(0);
  const feedbackRequestGeneration = useRef(0);
  const feedbackTarget = useRef({ analysisId, findingRef });
  activeFingerprint.current = findingFingerprint;
  feedbackTarget.current = { analysisId, findingRef };

  useEffect(() => {
    requestGeneration.current += 1;
    const generation = ++feedbackRequestGeneration.current;
    setOpen(false);
    setLoading(false);
    setResult(null);
    setFailed(false);
    setFeedback(null);
    setFeedbackSaving(false);
    setFeedbackFailed(false);
    const target = feedbackTarget.current;
    if (designIntelligenceEnabled() && target.analysisId && target.findingRef) {
      void fetchAnalysisFeedback(target.analysisId, target.findingRef)
        .then((saved) => {
          if (
            generation === feedbackRequestGeneration.current &&
            findingFingerprint === activeFingerprint.current
          ) {
            setFeedback(saved.advisory);
          }
        })
        .catch(() => {
          // No saved signal is an ordinary first-view state.
        });
    }
    return () => {
      if (generation === feedbackRequestGeneration.current) {
        feedbackRequestGeneration.current += 1;
      }
    };
  }, [findingFingerprint]);

  if (!designIntelligenceEnabled()) return null;

  async function load() {
    const fingerprint = findingFingerprint;
    const generation = ++requestGeneration.current;
    setLoading(true);
    setFailed(false);
    try {
      const next =
        analysisId && findingRef
          ? await fetchAnalysisDesignIntelligence(analysisId, findingRef)
          : await fetchDesignIntelligence(finding);
      if (
        generation === requestGeneration.current &&
        fingerprint === activeFingerprint.current
      ) {
        setResult(next);
      }
    } catch {
      if (
        generation === requestGeneration.current &&
        fingerprint === activeFingerprint.current
      ) {
        setFailed(true);
      }
    } finally {
      if (
        generation === requestGeneration.current &&
        fingerprint === activeFingerprint.current
      ) {
        setLoading(false);
      }
    }
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !result && !loading && !failed) void load();
  }

  async function saveFeedback(signal: AdvisoryFeedbackSignal) {
    if (!canRecord || !analysisId || !findingRef) return;
    const fingerprint = findingFingerprint;
    const generation = ++feedbackRequestGeneration.current;
    setFeedbackSaving(true);
    setFeedbackFailed(false);
    try {
      const saved = await recordAnalysisFeedback(analysisId, {
        advisory: signal,
        finding_ref: findingRef,
      });
      if (
        generation === feedbackRequestGeneration.current &&
        fingerprint === activeFingerprint.current
      ) {
        setFeedback(saved.advisory);
      }
    } catch {
      if (
        generation === feedbackRequestGeneration.current &&
        fingerprint === activeFingerprint.current
      ) {
        setFeedbackFailed(true);
      }
    } finally {
      if (
        generation === feedbackRequestGeneration.current &&
        fingerprint === activeFingerprint.current
      ) {
        setFeedbackSaving(false);
      }
    }
  }

  const empty = result
    ? designIntelligenceEmptyMessage(
        result.status,
        result.reason,
        result.index_truncated
      )
    : null;
  const researchOnly = result ? isResearchOnly(result) : false;
  const evidenceCount = result
    ? (result.possible_intents?.length ?? 0) +
      (result.relevant_requirements?.length ?? 0) +
      (result.workflow_evidence?.length ?? 0)
    : 0;
  const announcement = !open
    ? ""
    : loading
      ? "Finding relevant design context."
      : failed
        ? "Design context unavailable. The engine finding is unchanged."
        : result
          ? `Design context loaded with ${evidenceCount} evidence item${evidenceCount === 1 ? "" : "s"}.`
          : "";

  return (
    <div
      className={className}
      style={{
        marginTop: 8,
        border: `1px dashed ${C.hair}`,
        borderRadius: 10,
        background: C.sunken,
        color: C.ink,
      }}
    >
      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {announcement}
      </p>
      <button
        type="button"
        aria-label={`Design intent context for ${finding.code}: ${finding.message}`}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={toggle}
        style={{
          display: "flex",
          width: "100%",
          minHeight: 44,
          alignItems: "center",
          gap: 8,
          border: 0,
          borderRadius: 10,
          padding: "8px 12px",
          background: "transparent",
          color: C.ink,
          fontFamily: "inherit",
          fontSize: 12,
          textAlign: "left",
          cursor: "pointer",
        }}
      >
        <BookOpenText size={14} color={C.ink45} aria-hidden />
        <span style={{ fontWeight: 500 }}>Design intent context</span>
        <Pill style={{ marginLeft: "auto" }}>ADVISORY_ONLY</Pill>
        <ChevronDown
          size={14}
          color={C.ink45}
          style={{ transform: open ? "rotate(180deg)" : undefined }}
          aria-hidden
        />
      </button>

      {open && (
        <div
          id={panelId}
          style={{ borderTop: `1px solid ${C.hair}`, padding: 12 }}
        >
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            <Pill>ENGINEERING AUTHORITY · NONE</Pill>
            {researchOnly && (
              <Pill style={{ color: C.cond, borderColor: C.cond }}>
                RESEARCH_ONLY · UNLICENSED CORPUS
              </Pill>
            )}
          </div>
          <p style={{ margin: "10px 0 0", fontSize: 12, lineHeight: 1.6, color: C.ink55 }}>
            Third-party design precedent only. It cannot change this deterministic finding,
            threshold, or verdict.
          </p>
          {result?.index_truncated && (
            <p style={{ margin: "6px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink45 }}>
              BOUNDED SEARCH · {result.indexed_records} OF {result.eligible_records_scanned} ELIGIBLE RECORDS INDEXED
            </p>
          )}

          {loading ? (
            <div style={{ padding: "10px 0 2px" }} role="status">
              <Spinner label="Finding relevant design context…" />
            </div>
          ) : failed ? (
            <div style={{ marginTop: 10 }}>
              <p role="alert" style={{ margin: 0, fontSize: 12, color: C.ink55 }}>
                Design context is unavailable. The deterministic finding above is unchanged.
              </p>
              <button
                type="button"
                onClick={() => void load()}
                style={LINK_BUTTON_STYLE}
              >
                <RotateCcw size={12} aria-hidden />
                Retry
              </button>
            </div>
          ) : empty ? (
            <p style={{ margin: "10px 0 0", fontSize: 12, color: C.ink55 }}>{empty}</p>
          ) : result ? (
            <AdvisoryResults result={result} />
          ) : null}
          {result && analysisId && findingRef && (
            <div style={{ marginTop: 14, borderTop: `1px solid ${C.hair}`, paddingTop: 10 }}>
              <p style={{ margin: 0, fontFamily: MONO, fontSize: 9.5, color: C.ink45 }}>
                WAS THIS ADVISORY CONTEXT USEFUL?
              </p>
              {canRecord ? (
                <div style={{ marginTop: 7, display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {([
                    ["helpful", "Helpful"],
                    ["not_relevant", "Not relevant"],
                    ["incorrect", "Incorrect"],
                  ] as const).map(([signal, label]) => (
                    <button
                      key={signal}
                      type="button"
                      disabled={feedbackSaving}
                      aria-pressed={feedback === signal}
                      onClick={() => void saveFeedback(signal)}
                      style={{
                        border: `1px solid ${feedback === signal ? C.ink : C.hair}`,
                        borderRadius: 999,
                        background: feedback === signal ? C.ink : C.panel,
                        color: feedback === signal ? "#fff" : C.ink55,
                        padding: "5px 9px",
                        fontFamily: "inherit",
                        fontSize: 10.5,
                        cursor: feedbackSaving ? "wait" : "pointer",
                      }}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              ) : (
                <p style={{ margin: "7px 0 0", fontFamily: MONO, fontSize: 9.5, color: C.ink45 }}>
                  READ ONLY · analyst role required to record feedback
                </p>
              )}
              {(feedback || feedbackFailed) && (
                <p role={feedbackFailed ? "alert" : "status"} style={{ margin: "7px 0 0", fontFamily: MONO, fontSize: 9.5, color: feedbackFailed ? C.fail : C.pass }}>
                  {feedbackFailed
                    ? "feedback was not saved — the advisory and engine verdict are unchanged"
                    : `recorded feedback · ${feedback?.replace("_", " ")}`}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AdvisoryResults({ result }: { result: DesignIntelligenceResponse }) {
  const intents = result.possible_intents ?? [];
  const requirements = result.relevant_requirements ?? [];
  const evidence = result.workflow_evidence ?? [];

  if (intents.length + requirements.length + evidence.length === 0) {
    return (
      <p style={{ margin: "10px 0 0", fontSize: 12, color: C.ink55 }}>
        No relevant design precedent was found. The deterministic finding above is unchanged.
      </p>
    );
  }

  return (
    <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 16 }}>
      {intents.length > 0 && (
        <section aria-label="Possible design intent">
          <Eyebrow>Possible intent · hypothesis</Eyebrow>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {intents.map((intent, index) => {
              const href = safeEvidenceUrl(intent.source_url);
              return (
                <li
                  key={`${intent.workflow_id ?? "intent"}-${index}`}
                  style={{ marginTop: index ? 6 : 0, fontSize: 12, lineHeight: 1.6, color: C.ink }}
                >
                  {intent.candidate}
                  {href && <SourceLink href={href} label={`Source for possible intent: ${intent.candidate}`} />}
                </li>
              );
            })}
          </ul>
        </section>
      )}
      <EvidenceSection title="Comparable requirements" rows={requirements} />
      <EvidenceSection title="Workflow evidence" rows={evidence} />
    </div>
  );
}

function EvidenceSection({
  title,
  rows,
}: {
  title: string;
  rows: DesignIntelligenceEvidence[];
}) {
  if (rows.length === 0) return null;
  return (
    <section aria-label={title}>
      <Eyebrow>{title}</Eyebrow>
      <ul style={{ margin: "6px 0 0", padding: 0, listStyle: "none" }}>
        {rows.map((row, index) => {
          const time = evidenceTimeRange(row.start_s, row.end_s);
          const href = safeEvidenceUrl(row.source_url);
          return (
            <li
              key={`${row.workflow_id ?? row.knowledge_role ?? "evidence"}-${index}`}
              style={{
                marginTop: index ? 8 : 0,
                border: `1px solid ${C.hair}`,
                borderRadius: 8,
                background: C.panel,
                padding: 10,
              }}
            >
              <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 8px", fontFamily: MONO, fontSize: 10, color: C.ink45 }}>
                {row.application && <span>{row.application}</span>}
                {time && <span>{time}</span>}
                <span>{row.provenance}</span>
                {row.license_status !== "LICENSED" && <span>{row.license_status}</span>}
              </div>
              <p style={{ margin: "5px 0 0", fontSize: 12, lineHeight: 1.6, color: C.ink }}>{row.excerpt}</p>
              {href && (
                <SourceLink
                  href={href}
                  label={`Source for ${title.toLowerCase()}${row.application ? ` in ${row.application}` : ""}${time ? ` at ${time}` : ""}`}
                />
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function SourceLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      aria-label={label}
      style={{
        marginLeft: 8,
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        color: C.measured,
        fontSize: 11,
        fontWeight: 500,
      }}
    >
      source
      <ExternalLink size={10} aria-hidden />
    </a>
  );
}

function Pill({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        minHeight: 22,
        border: `1px solid ${C.hair}`,
        borderRadius: 999,
        padding: "2px 7px",
        color: C.ink45,
        background: C.panel,
        fontFamily: MONO,
        fontSize: 9,
        letterSpacing: "0.04em",
        whiteSpace: "nowrap",
        ...style,
      }}
    >
      {children}
    </span>
  );
}

function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p style={{ margin: 0, color: C.ink45, fontFamily: MONO, fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase" }}>
      {children}
    </p>
  );
}

const LINK_BUTTON_STYLE: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  marginTop: 8,
  border: 0,
  padding: 0,
  background: "transparent",
  color: C.measured,
  fontFamily: "inherit",
  fontSize: 12,
  fontWeight: 500,
  cursor: "pointer",
};
