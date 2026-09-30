import { API_BASE } from "@/lib/api-base";

export interface IntegrationConnector {
  id: string;
  label: string;
  source_system: string;
  source_kind: "manifest" | "ground_truth" | "bom";
  file_format: string;
  mode: string;
  description: string;
  template_endpoint: string;
  raw_payload_stored: boolean;
  configured: boolean;
  live_credentials_required: boolean;
}

export interface IntegrationRun {
  id: string;
  connector_id: string;
  source_system: string;
  source_kind: string;
  mode: "dry_run" | "import";
  status: "passed" | "partial" | "failed";
  filename: string | null;
  file_sha256: string;
  file_size_bytes: number;
  rows_total: number;
  rows_valid: number;
  rows_invalid: number;
  imported_count: number;
  updated_count: number;
  skipped_count: number;
  raw_stored: boolean;
  errors: { line?: number | null; index?: number | null; reason: string }[];
  metadata: Record<string, unknown>;
  created_at: string | null;
  completed_at: string | null;
}

export type ConnectorAuthType = "bearer" | "basic" | "oauth2_client_credentials" | "api_key";

export interface ConnectorCredentialProfile {
  id: string;
  connector_id: string;
  label: string;
  base_url: string;
  auth_type: ConnectorAuthType;
  revoked_at: string | null;
}

export interface ConnectorProbe {
  connected: boolean;
  records_read: number;
  checked_at: string;
  reason: string | null;
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail =
      (body && (body.detail?.message || body.detail || body.message)) ||
      `Request failed (${res.status})`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export async function listIntegrationConnectors(): Promise<IntegrationConnector[]> {
  const res = await fetch(`${API_BASE}/integrations/connectors`, {
    cache: "no-store",
  });
  const body = await readJson<{ connectors: IntegrationConnector[] }>(res);
  return body.connectors;
}

export async function listIntegrationRuns(): Promise<IntegrationRun[]> {
  const res = await fetch(`${API_BASE}/integrations/runs?limit=25`, {
    cache: "no-store",
  });
  const body = await readJson<{ runs: IntegrationRun[] }>(res);
  return body.runs;
}

export async function createIntegrationRun({
  connectorId,
  mode,
  file,
}: {
  connectorId: string;
  mode: "dry_run" | "import";
  file: File;
}): Promise<IntegrationRun> {
  const form = new FormData();
  form.set("connector_id", connectorId);
  form.set("mode", mode);
  form.set("file", file);
  const res = await fetch(`${API_BASE}/integrations/runs`, {
    method: "POST",
    body: form,
  });
  const body = await readJson<{ run: IntegrationRun }>(res);
  return body.run;
}

export async function listConnectorCredentials(connectorId: string): Promise<ConnectorCredentialProfile[]> {
  const res = await fetch(`${API_BASE}/integrations/credential-profiles?connector_id=${encodeURIComponent(connectorId)}`, { cache: "no-store" });
  return (await readJson<{ profiles: ConnectorCredentialProfile[] }>(res)).profiles;
}

export async function saveConnectorCredential(input: {
  connector_id: string; label: string; base_url: string;
  auth_type: ConnectorAuthType; secret: Record<string, string>;
}): Promise<ConnectorCredentialProfile> {
  const res = await fetch(`${API_BASE}/integrations/credential-profiles`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
  });
  return (await readJson<{ profile: ConnectorCredentialProfile }>(res)).profile;
}

export async function probeConnectorCredential(id: string): Promise<ConnectorProbe> {
  const res = await fetch(`${API_BASE}/integrations/credential-profiles/${encodeURIComponent(id)}/probe`, { method: "POST" });
  return (await readJson<{ probe: ConnectorProbe }>(res)).probe;
}

export async function revokeConnectorCredential(id: string): Promise<ConnectorCredentialProfile> {
  const res = await fetch(`${API_BASE}/integrations/credential-profiles/${encodeURIComponent(id)}`, { method: "DELETE" });
  return (await readJson<{ profile: ConnectorCredentialProfile }>(res)).profile;
}

export interface ConnectorBomRun extends IntegrationRun {
  metadata: Record<string, unknown> & {
    assembly_key: string;
    preview_edges: { parent_ref: string; child_ref: string; child_name: string; qty_per_parent: number }[];
    preview_truncated: boolean;
  };
}

export async function runConnectorBom(id: string, input: {
  part_id: string; assembly_key: string; mode: "dry_run" | "import";
  navigation_id?: string; expected_sha256?: string;
}): Promise<ConnectorBomRun> {
  const res = await fetch(`${API_BASE}/integrations/credential-profiles/${encodeURIComponent(id)}/bom-runs`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
  });
  return (await readJson<{ run: ConnectorBomRun }>(res)).run;
}
