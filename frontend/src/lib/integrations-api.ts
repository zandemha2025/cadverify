import { API_BASE } from "@/lib/api-base";

export interface IntegrationConnector {
  id: string;
  label: string;
  source_system: string;
  source_kind: "manifest" | "ground_truth";
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
