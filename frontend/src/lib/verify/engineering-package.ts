import { API_BASE } from "@/lib/api-base";

export interface PackageScope { process: string; material: string; machine: string; setup: string; inspection_method: string }
export interface PackageSource {
  id: string; name: string; kind: "model" | "drawing" | "specification" | "evidence" | "comparison";
  revision: string; reference: string; sha256: string | null; filename: string;
  authority: "controlling" | "supporting" | "derivative";
  coverage: "unreviewed" | "partial" | "complete"; coverage_note: string;
}
export const evidenceKinds = ["manufacturing", "inspection", "material", "service", "translation", "cam", "resource", "authorization"] as const;
export type EvidenceKind = typeof evidenceKinds[number];
export interface PackageRequirement {
  id: string; characteristic: string; feature: string;
  kind: "dimension" | "gdt" | "material" | "finish" | "service" | "interface" | "process" | "other";
  value: string; unit: string; lower: number | null; upper: number | null;
  source_id: string; location: string; required_evidence: EvidenceKind[];
}
export interface PackageEvidence {
  id: string; kind: EvidenceKind; source_id: string; location: string; requirement_ids: string[];
  scope: PackageScope; conclusion: "supports" | "fails" | "inconclusive"; rationale: string;
  expires_on: string | null; outcome_ids: string[]; supersedes_evidence_ids: string[];
}
export interface PackageAction {
  id: string; blocker_id: string; title: string; owner: string; required_evidence: string;
  requirement_ids: string[]; closure_evidence_ids: string[]; rationale: string;
}
export interface PackageOutcome {
  id: string; source_id: string; location: string; revision: string; order: string; scope: PackageScope;
  requirement_ids: string[]; samples: number; failures: number; observed_on: string; note: string;
  actual_setup_minutes: number | null; actual_cycle_minutes: number | null; actual_material_kg: number | null;
}
export interface PackageDocument {
  part_number: string; revision: string; order: string; effectivity: string; quantity: number;
  scope: PackageScope; sources: PackageSource[]; requirements: PackageRequirement[];
  evidence: PackageEvidence[]; actions: PackageAction[]; outcomes: PackageOutcome[];
  authorization: { authority: string; reference: string; activity: string; revision: string; order: string; evidence_id: string } | null;
  note: string;
}
export interface PackageBlocker { id: string; kind: string; consequence: string; requirement_ids: string[]; owner: string; required_evidence: string; action_id: string | null }
export interface PackageEvaluation {
  screening: string; qualification: string; authorization: string; boundary: string;
  blockers: PackageBlocker[];
  evidence_status: { id: string; status: string; reason: string; requirement_ids: string[] }[];
  action_status: { id: string; status: string }[];
  changes: { changed_requirements: string[]; added_requirements: string[]; removed_requirements: string[]; unchanged_requirements: string[]; scope_changed: boolean; configuration_changed: boolean };
  alternatives: { process: string; material: string; quantity: number; machine: string | null; screening_verdict: string; conditions: string[]; unit_cost_usd: number | null; basis: string; resources: {name: string; value: number; unit: string; provenance: string; source: string}[] }[];
}
export interface EngineeringPackageSummary {
  id: string; series_id: string; version: number; mesh_hash: string; state: "draft" | "issued"; is_latest: boolean;
  created_at: string; created_by: number; part_number: string; revision: string; order: string;
  screening: string; qualification: string; blocker_count: number;
}
export interface EngineeringPackage extends EngineeringPackageSummary {
  document: PackageDocument; evaluation: PackageEvaluation; decision_id: string;
  reviews: Record<string, {fingerprint: string; user_id: number; reviewed_at: string}>;
  previous_id: string | null; review_note: string; evaluated_on: string;
  current_assessment?: PackageEvaluation & {stale_reason: string | null; assessed_on: string};
}
export interface PackageWrite {
  decision_id: string; document: PackageDocument; previous_id?: string;
  state?: "draft" | "issued"; review_note?: string;
  confirm_sources?: string[]; confirm_requirements?: string[]; review_evidence?: string[]; close_actions?: string[];
}

const base = `${API_BASE}/engineering-packages`;
export async function packageRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(base + path, {cache: "no-store", ...init});
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    const message = typeof problem.detail === "string" ? problem.detail
      : Array.isArray(problem.detail) ? problem.detail.map((p: {loc?: string[]; msg?: string}) => `${p.loc?.slice(1).join(".")}: ${p.msg}`).join("; ")
      : typeof problem.message === "string" ? problem.message
      : `Request failed (${response.status}). Your local edits are still available.`;
    throw new Error(message);
  }
  return response.json();
}
export const saveEngineeringPackage = (body: PackageWrite) => packageRequest<EngineeringPackage>("", {
  method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
});
export const packageExportUrl = (id: string, format: string) => `${base}/${encodeURIComponent(id)}/export.${format}`;
export const packageSourceUrl = (id: string, source: string) => `${base}/${encodeURIComponent(id)}/documents/${encodeURIComponent(source)}`;

export function emptyPackage(partNumber: string, scope: PackageScope, quantity: number): PackageDocument {
  return {part_number: partNumber, revision: "", order: "", effectivity: "", quantity, scope,
    sources: [], requirements: [], evidence: [], actions: [], outcomes: [], authorization: null, note: ""};
}
