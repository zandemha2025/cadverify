import { partCheckHeaders } from "./check-id.ts";
/**
 * Preview-mesh client for the Verify stage.
 *
 * A dropped STL is parsed in the browser (STLLoader) and rendered from its real
 * geometry. A STEP/IGES part CANNOT be parsed client-side, so the stage used to
 * fall back to a bounding-BOX envelope — "my part became a box", a real trust
 * hit. This fetches the part's REAL tessellated shell from our own backend
 * (POST /validate/preview-mesh) as a decimated GLB and hands it to three.js so
 * the part looks like itself.
 *
 * Zero-egress: the request goes SAME-ORIGIN through the Next authed proxy
 * (`/api/proxy/*` → backend `/api/v1/*` with the httpOnly session cookie). The
 * CAD is tessellated in OUR backend and the GLB is streamed straight back; the
 * bytes never touch a third party. This is a MESH-LEVEL preview (triangulated
 * shell), NOT B-rep / GD&T / PMI — it makes the part LOOK right, it asserts no
 * analytic-surface semantics.
 */
import { API_BASE } from "@/lib/api-base";
import { apiQuotaMessage } from "../api-recovery.ts";

export interface PreviewMesh {
  /** object URL for the GLB blob (caller revokes via `revoke`). */
  url: string;
  /** triangle count of the full tessellated shell, if the backend reported it. */
  originalFaces: number | null;
  /** triangle count actually streamed (≤ browser budget). */
  previewFaces: number | null;
  /** true when the shell was decimated to fit the browser budget. */
  decimated: boolean;
  /** parsed source suffix (step/stp/iges/igs/stl), if reported. */
  source: string | null;
  /** Only analysis-space meshes preserve the DFM result's face indices. */
  faceSpace: "analysis" | "preview";
  faceHash: string | null;
  revoke: () => void;
}

function readNum(res: Response, header: string): number | null {
  const raw = res.headers.get(header);
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

type PreviewData = Omit<PreviewMesh, "url" | "revoke"> & { blob: Blob };
// Keep completed previews and join concurrent viewers. A remount must not spend
// another operation; each consumer owns its URL, while File lifetime bounds memory.
const previews = new WeakMap<File, Map<string, Promise<PreviewData | null>>>();

export async function fetchPreviewMesh(file: File, options?: { forAnalysis?: boolean; units?: "mm" | "inch" }): Promise<PreviewMesh | null> {
  const query = options?.forAnalysis ? `?purpose=analysis&units=${options.units ?? "mm"}` : options?.units ? `?units=${options.units}` : "";
  let byQuery = previews.get(file);
  if (!byQuery) { byQuery = new Map(); previews.set(file, byQuery); }
  let pending = byQuery.get(query);
  if (!pending) { pending = fetchPreviewData(file, query); byQuery.set(query, pending); }
  let data: PreviewData | null;
  try { data = await pending; }
  catch (error) { byQuery.delete(query); throw error; }
  if (!data) { byQuery.delete(query); return null; }
  const { blob, ...metadata } = data;
  const url = URL.createObjectURL(blob);
  return { ...metadata, url, revoke: () => URL.revokeObjectURL(url) };
}

async function fetchPreviewData(file: File, query: string): Promise<PreviewData | null> {
  const form = new FormData();
  form.append("file", file);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/validate/preview-mesh${query}`, {
      method: "POST",
      headers: partCheckHeaders(file),
      body: form,
    });
  } catch {
    return null;
  }
  if (!res.ok) {
    if (res.status === 403 || res.status === 429) {
      const quota = apiQuotaMessage(await res.json().catch(() => null));
      if (quota) throw new Error(quota);
    }
    return null;
  }

  let blob: Blob;
  try {
    blob = await res.blob();
  } catch {
    return null;
  }
  if (!blob.size) return null;

  return {
    blob,
    originalFaces: readNum(res, "x-mesh-original-faces"),
    previewFaces: readNum(res, "x-mesh-preview-faces"),
    decimated: res.headers.get("x-mesh-decimated") === "true",
    source: res.headers.get("x-mesh-source"),
    faceSpace: res.headers.get("x-mesh-face-space") === "analysis" ? "analysis" : "preview",
    faceHash: res.headers.get("x-mesh-face-hash"),
  };
}
