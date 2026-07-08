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
  revoke: () => void;
}

function readNum(res: Response, header: string): number | null {
  const raw = res.headers.get(header);
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

/**
 * Fetch the decimated GLB shell for `file`. Returns null on any failure
 * (network, unauthorized, unparseable) so the stage can fall back to the HONEST
 * bounding-box envelope — we never fabricate geometry.
 */
export async function fetchPreviewMesh(file: File): Promise<PreviewMesh | null> {
  const form = new FormData();
  form.append("file", file);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/validate/preview-mesh`, {
      method: "POST",
      body: form,
    });
  } catch {
    return null;
  }
  if (!res.ok) return null;

  let blob: Blob;
  try {
    blob = await res.blob();
  } catch {
    return null;
  }
  if (!blob.size) return null;

  const url = URL.createObjectURL(blob);
  return {
    url,
    originalFaces: readNum(res, "x-mesh-original-faces"),
    previewFaces: readNum(res, "x-mesh-preview-faces"),
    decimated: res.headers.get("x-mesh-decimated") === "true",
    source: res.headers.get("x-mesh-source"),
    revoke: () => URL.revokeObjectURL(url),
  };
}
