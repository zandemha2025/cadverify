import type {
  DesignIntelligenceFindingRef,
  PriorityFix,
  ValidationResult,
  DesignIntelligenceResponse,
  OrgPrecedentResponse,
} from "./api";

const STATUSES = new Set(["available", "research_only", "no_match", "unavailable"]);

/** Runtime trust boundary: evidence is discarded unless the server explicitly
 * preserves every non-authoritative invariant. */
export function isSafeDesignIntelligenceResponse(
  value: unknown
): value is DesignIntelligenceResponse {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  const nonnegativeInteger = (item: unknown): item is number =>
    typeof item === "number" && Number.isInteger(item) && item >= 0;
  if (
    !STATUSES.has(String(row.status)) ||
    row.authority !== "ADVISORY_ONLY" ||
    row.engineering_authority !== "NONE" ||
    row.provenance !== "THIRD_PARTY_UNVERIFIED" ||
    row.may_affect_deterministic_verdict !== false ||
    row.is_manufacturing_ground_truth !== false ||
    !nonnegativeInteger(row.eligible_records_scanned) ||
    !nonnegativeInteger(row.indexed_records) ||
    row.indexed_records > row.eligible_records_scanned ||
    typeof row.index_truncated !== "boolean" ||
    row.index_truncated !== (row.indexed_records < row.eligible_records_scanned)
  ) {
    return false;
  }
  if (
    row.status === "no_match" &&
    row.index_truncated &&
    row.reason !== "no_relevant_precedent_in_bounded_index"
  ) {
    return false;
  }
  if (
    !Array.isArray(row.possible_intents) ||
    !Array.isArray(row.relevant_requirements) ||
    !Array.isArray(row.workflow_evidence)
  ) {
    return false;
  }
  const optionalString = (item: unknown) => item == null || typeof item === "string";
  const optionalNumber = (item: unknown) =>
    item == null || (typeof item === "number" && Number.isFinite(item));
  const validIntent = (item: unknown) => {
    if (!item || typeof item !== "object") return false;
    const intent = item as Record<string, unknown>;
    return (
      typeof intent.candidate === "string" &&
      optionalString(intent.workflow_id) &&
      optionalString(intent.source_url) &&
      intent.provenance === "THIRD_PARTY_UNVERIFIED" &&
      typeof intent.license_status === "string" &&
      typeof intent.production_eligible === "boolean"
    );
  };
  const validEvidence = (item: unknown) => {
    if (!item || typeof item !== "object") return false;
    const evidence = item as Record<string, unknown>;
    return (
      typeof evidence.excerpt === "string" &&
      optionalString(evidence.workflow_id) &&
      optionalString(evidence.application) &&
      optionalString(evidence.knowledge_role) &&
      optionalString(evidence.source_url) &&
      evidence.provenance === "THIRD_PARTY_UNVERIFIED" &&
      typeof evidence.license_status === "string" &&
      typeof evidence.production_eligible === "boolean" &&
      optionalNumber(evidence.start_s) &&
      optionalNumber(evidence.end_s)
    );
  };
  const structurallySafe = (
    row.possible_intents.every(validIntent) &&
    row.relevant_requirements.every(validEvidence) &&
    row.workflow_evidence.every(validEvidence)
  );
  if (!structurallySafe) return false;

  const evidenceRows = [
    ...row.possible_intents,
    ...row.relevant_requirements,
    ...row.workflow_evidence,
  ] as Array<Record<string, unknown>>;
  if (row.status === "research_only") return row.research_mode === true;
  if (row.status !== "available") return evidenceRows.length === 0;
  return evidenceRows.every((item) => {
    const license = String(item.license_status).trim().toUpperCase();
    return (
      item.production_eligible === true &&
      !["", "NONE", "NULL", "UNDECLARED", "UNKNOWN"].includes(license)
    );
  });
}

/** Runtime trust boundary for tenant-local precedent memory. */
export function isSafeOrgPrecedentResponse(
  value: unknown
): value is OrgPrecedentResponse {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  const finiteNumber = (item: unknown): item is number =>
    typeof item === "number" && Number.isFinite(item);
  const maxDistance = row.max_distance;
  if (
    !new Set(["available", "no_match", "unavailable"]).has(String(row.status)) ||
    row.authority !== "ADVISORY_ONLY" ||
    row.may_affect_deterministic_verdict !== false ||
    typeof row.analysis_id !== "string" ||
    typeof row.corpus_version !== "string" ||
    typeof row.algorithm_version !== "string" ||
    typeof row.analysis_version !== "string" ||
    typeof row.current_analysis_version !== "string" ||
    !finiteNumber(maxDistance) ||
    maxDistance <= 0 ||
    !Number.isInteger(row.candidate_limit) ||
    Number(row.candidate_limit) < 1 ||
    !Number.isInteger(row.candidates_examined) ||
    Number(row.candidates_examined) < 0 ||
    typeof row.search_truncated !== "boolean" ||
    !Array.isArray(row.cases)
  ) {
    return false;
  }
  const provenance = row.provenance as Record<string, unknown> | null;
  if (
    !provenance ||
    provenance.corpus !== "ACTIVE_ORGANIZATION_SAVED_ANALYSES" ||
    provenance.similarity !== "DETERMINISTIC_DERIVED_FROM_MEASURED_GEOMETRY"
  ) {
    return false;
  }
  const finite = finiteNumber;
  const optionalString = (item: unknown) => item == null || typeof item === "string";
  const vector = (item: unknown) =>
    finite(item) ||
    (Array.isArray(item) && item.length > 0 && item.every(finite));
  const validCase = (item: unknown) => {
    if (!item || typeof item !== "object") return false;
    const precedent = item as Record<string, unknown>;
    return (
      typeof precedent.analysis_id === "string" &&
      typeof precedent.analysis_url === "string" &&
      precedent.analysis_url.startsWith("/analyses/") &&
      typeof precedent.analysis_api_url === "string" &&
      precedent.analysis_api_url.startsWith("/api/v1/analyses/") &&
      typeof precedent.filename === "string" &&
      optionalString(precedent.created_at) &&
      finite(precedent.distance) &&
      precedent.distance >= 0 &&
      precedent.distance <= maxDistance &&
      optionalString(precedent.verdict) &&
      optionalString(precedent.best_process) &&
      optionalString(precedent.recommended_material) &&
      optionalString(precedent.recommended_machine) &&
      typeof precedent.analysis_version === "string" &&
      typeof precedent.stale === "boolean" &&
      Array.isArray(precedent.shared_geometry) &&
      precedent.shared_geometry.every((field) => {
        if (!field || typeof field !== "object") return false;
        const shared = field as Record<string, unknown>;
        return (
          typeof shared.name === "string" &&
          vector(shared.target) &&
          vector(shared.candidate) &&
          (shared.provenance === "MEASURED" ||
            shared.provenance === "MEASURED_DERIVED")
        );
      })
    );
  };
  if (!row.cases.every(validCase)) return false;
  return row.status === "available" ? row.cases.length > 0 : row.cases.length === 0;
}

export function designIntelligenceEnabled(
  value = process.env.NEXT_PUBLIC_DESIGN_INTELLIGENCE
): boolean {
  const normalized = value?.trim().toLowerCase();
  return normalized === "1" || normalized === "true";
}

export function canRecordAnalysisMemory(role: string | null | undefined): boolean {
  return role === "analyst" || role === "admin" || role === "superadmin";
}

export function isResearchOnly(result: DesignIntelligenceResponse): boolean {
  return result.status === "research_only" || result.research_mode === true;
}

export function designIntelligenceEmptyMessage(
  status: DesignIntelligenceResponse["status"],
  reason?: string | null,
  indexTruncated = false
): string | null {
  if (status === "no_match") {
    if (indexTruncated) {
      return "No relevant design precedent was found in the bounded serving index; unindexed eligible records may contain additional context. The deterministic finding above is unchanged.";
    }
    return "No relevant design precedent was found. The deterministic finding above is unchanged.";
  }
  if (status !== "unavailable") return null;
  if (reason === "knowledge_corpus_missing") {
    return "Design context is not installed. The deterministic finding above remains available.";
  }
  if (reason === "no_eligible_knowledge_records") {
    return "No production-eligible design context is available. The deterministic finding above is unchanged.";
  }
  return "Design context is unavailable. The deterministic finding above is unchanged.";
}

function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(whole / 60);
  return `${minutes}:${String(whole % 60).padStart(2, "0")}`;
}

export function evidenceTimeRange(
  start: number | null | undefined,
  end: number | null | undefined
): string | null {
  if (start == null || !Number.isFinite(start)) return null;
  if (end == null || !Number.isFinite(end) || end <= start) return clock(start);
  return `${clock(start)}–${clock(end)}`;
}

/** Dataset URLs are untrusted input even though React escapes their labels. */
export function safeEvidenceUrl(raw: string | null | undefined): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

/** Map the flattened priority-fix row back to the exact saved engine issue.
 * The server rehydrates the finding from this locator; no finding prose or
 * engineering value needs to cross the trust boundary. */
export function findingRefForPriorityFix(
  validation: ValidationResult,
  fix: PriorityFix
): DesignIntelligenceFindingRef | null {
  const scope = fix.process === "all" ? "universal" : "process";
  const issues =
    scope === "universal"
      ? validation.universal_issues
      : validation.process_scores.find((row) => row.process === fix.process)?.issues;
  if (!issues) return null;
  const matching = issues.filter((issue) => issue.code === fix.code);
  const occurrence = matching.findIndex((issue) => issue.message === fix.message);
  if (occurrence < 0) return null;
  return {
    scope,
    code: fix.code,
    occurrence,
    ...(scope === "process" ? { process: fix.process } : {}),
  };
}
