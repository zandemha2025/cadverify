/**
 * This deployment's own statement of where data lives (SERVER ONLY), from the
 * API's GET /api/v1/deployment: file storage from the object-store settings the
 * code uses, and hosting facts only when the operator configured them. Null
 * when the API can't be reached; the pages then say the facts aren't stated.
 */
import "server-only";
import { backendUrl } from "./api-base";
import type { DeploymentFacts } from "@/components/v4/trust/facts";

export async function getDeploymentFacts(): Promise<DeploymentFacts | null> {
  try {
    const res = await fetch(backendUrl("/api/v1/deployment"), {
      next: { revalidate: 300 },
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    const body = (await res.json()) as DeploymentFacts;
    return body && body.file_storage && body.declared ? body : null;
  } catch {
    return null;
  }
}
