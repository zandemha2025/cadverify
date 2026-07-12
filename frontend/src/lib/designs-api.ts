import { API_BASE } from "@/lib/api-base";

export type Hole = {
  x_mm: number;
  y_mm: number;
  diameter_mm: number;
};

export type PlatePlan = {
  kind: "plate";
  width_mm: number;
  depth_mm: number;
  thickness_mm: number;
  holes: Hole[];
};

export type BracketPlan = {
  kind: "bracket";
  width_mm: number;
  depth_mm: number;
  height_mm: number;
  thickness_mm: number;
};

export type EnclosurePlan = {
  kind: "enclosure";
  width_mm: number;
  depth_mm: number;
  height_mm: number;
  wall_thickness_mm: number;
};

export type DesignPlan = PlatePlan | BracketPlan | EnclosurePlan;

export type DesignRevision = {
  id: string;
  number: number;
  status: "queued" | "generating" | "ready" | "failed";
  plan: DesignPlan;
  design_note: string | null;
  generation_engine: string;
  geometry_hash: string | null;
  geometry: {
    bbox_mm: number[];
    volume_cm3: number;
    surface_elements: number;
    solid_count: number;
    engine: string;
  } | null;
  step_size_bytes: number | null;
  stl_size_bytes: number | null;
  error: { code: string; message: string } | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  links: {
    preview: string | null;
    download_step: string | null;
    verify: string | null;
  };
};

export type Design = {
  id: string;
  name: string;
  status: "generating" | "ready" | "failed" | "archived";
  source_kind: "template" | "ai_plan";
  current_revision: number;
  created_at: string | null;
  updated_at: string | null;
  revision: DesignRevision | null;
  links: {
    self: string;
    preview: string | null;
    download_step: string | null;
    verify: string | null;
  };
};

export type DesignInput = {
  name: string;
  design_note?: string | null;
  plan: DesignPlan;
};

export type DesignInterpretation =
  | {
      status: "ready";
      kind: DesignPlan["kind"];
      name: string;
      plan: DesignPlan;
      assumptions: string[];
      message: string;
    }
  | {
      status: "needs_input";
      kind: DesignPlan["kind"] | null;
      missing_fields: string[];
      message: string;
      prefill: Partial<{
        width_mm: number;
        depth_mm: number;
        height_mm: number;
        thickness_mm: number;
        wall_thickness_mm: number;
      }>;
    };

export class DesignApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = "DesignApiError";
  }
}

async function apiError(response: Response): Promise<DesignApiError> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return new DesignApiError(`Request failed (${response.status})`, response.status);
  }
  const body = payload as {
    detail?: string | { message?: string; code?: string } | Array<{ msg?: string }>;
    message?: string;
    code?: string;
  };
  const detail = body.detail;
  const message = Array.isArray(detail)
    ? detail[0]?.msg ?? `Request failed (${response.status})`
    : typeof detail === "string"
      ? detail
      : detail?.message ?? body.message ?? `Request failed (${response.status})`;
  const code = detail && !Array.isArray(detail) && typeof detail === "object"
    ? detail.code
    : body.code;
  return new DesignApiError(message, response.status, code);
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    cache: "no-store",
    ...init,
    headers: init?.body
      ? { "content-type": "application/json", ...init.headers }
      : init?.headers,
  });
  if (!response.ok) throw await apiError(response);
  return (await response.json()) as T;
}

export async function listDesigns(): Promise<Design[]> {
  const payload = await json<{ designs: Design[] }>(`${API_BASE}/designs`);
  return payload.designs;
}

export async function getDesign(id: string): Promise<Design> {
  const payload = await json<{ design: Design }>(
    `${API_BASE}/designs/${encodeURIComponent(id)}`,
  );
  return payload.design;
}

export async function createDesign(input: DesignInput): Promise<Design> {
  const payload = await json<{ design: Design }>(`${API_BASE}/designs`, {
    method: "POST",
    body: JSON.stringify(input),
  });
  return payload.design;
}

export function interpretDesignPrompt(prompt: string): Promise<DesignInterpretation> {
  return json<DesignInterpretation>(`${API_BASE}/designs/interpret`, {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}

export async function createDesignRevision(
  id: string,
  input: Omit<DesignInput, "name">,
): Promise<Design> {
  const payload = await json<{ design: Design }>(
    `${API_BASE}/designs/${encodeURIComponent(id)}/revisions`,
    { method: "POST", body: JSON.stringify(input) },
  );
  return payload.design;
}

export async function listDesignRevisions(id: string): Promise<DesignRevision[]> {
  const payload = await json<{ revisions: DesignRevision[] }>(
    `${API_BASE}/designs/${encodeURIComponent(id)}/revisions`,
  );
  return payload.revisions;
}

export async function archiveDesign(id: string): Promise<void> {
  const response = await fetch(`${API_BASE}/designs/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!response.ok) throw await apiError(response);
}

export function designPreviewUrl(design: Design): string | null {
  if (design.status !== "ready" || !design.revision?.geometry_hash) return null;
  return `${API_BASE}/designs/${encodeURIComponent(design.id)}/preview.stl?revision=${design.current_revision}&hash=${design.revision.geometry_hash}`;
}

export function designStepUrl(id: string): string {
  return `${API_BASE}/designs/${encodeURIComponent(id)}/download.step`;
}

export function designRevisionPreviewUrl(
  designId: string,
  revision: DesignRevision,
): string | null {
  if (revision.status !== "ready" || !revision.geometry_hash) return null;
  return `${API_BASE}/designs/${encodeURIComponent(designId)}/revisions/${revision.number}/preview.stl?hash=${revision.geometry_hash}`;
}

export function designRevisionStepUrl(designId: string, revisionNo: number): string {
  return `${API_BASE}/designs/${encodeURIComponent(designId)}/revisions/${revisionNo}/download.step`;
}
