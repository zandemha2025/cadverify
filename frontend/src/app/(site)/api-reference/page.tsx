import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";
import { apiDocsServed } from "@/lib/api-docs";
import { publicApiOrigin } from "@/lib/public-api";

export const metadata: Metadata = {"title": "API reference — ScaleCAD", "description": "What a ScaleCAD API key can do, the endpoints to start with, limits and the address to call.", "alternates": {"canonical": "/api-reference"}};

export const dynamic = "force-dynamic";

/**
 * API reference. What a key can do comes from the code that enforces it
 * (backend src/auth/require_api_key.py and keys_api.py): its scope, its owner's
 * role and its organization. The address is the deployment's public API
 * address; the console link shows only when the API serves its docs.
 */
export default async function Page() {
  const origin = publicApiOrigin();
  const docs = origin !== null && (await apiDocsServed());
  return <DocumentPage label="API reference" title="API reference" intro="What an API key can do, the endpoints to start with, and the limits. Make keys in Account, API and keys." sections={[
  {
    "id": "keys",
    "title": "What a key can do",
    "body": "A key acts as the person who made it, in the organization it was made in, and never does more than that person can do there.",
    "bullets": [
      "Read only (the default for new keys): GET requests only, so it lists and opens parts, checks and records. Any other request gets 403 api_key_read_only.",
      "Read and write: also checks parts and changes what its owner may change. Only members and admins can make one.",
      "A viewer's key is always read only, whatever it was made as.",
      "Organization: a key works only in the organization it was made in. Used while its owner has another organization active, it gets 403 api_key_org_mismatch.",
      "Expiry: 30, 90 or 365 days, or none. An expired key gets 401 api_key_expired with the date it stopped working.",
      "Two-step sign-in: in an organization that requires it, a key whose owner hasn't set it up gets 403 api_key_two_step_required. It works again once they have. People who sign in through the organization's single sign-on are exempt, as when they sign in.",
      "A key stops working when it is revoked, when its owner leaves the organization, or when their account is turned off. An org admin sees every key in the organization and can revoke any of them.",
      "Deleting the organization or an account needs a signed-in person in the web app; a key can't do it.",
    ],
  },
  {
    "id": "routes",
    "title": "Endpoints to start with",
    "body": origin ? `Send each request to ${origin} with the header Authorization: Bearer cv_live_… .` : "Send each request to your deployment's API address (shown on API and keys once it is set) with the header Authorization: Bearer cv_live_… .",
    "code": "POST /api/v1/validate          check a part (read and write)\nPOST /api/v1/validate/cost     check and cost a part (read and write)\nGET  /api/v1/cost-decisions    list cost records (read only is enough)\nGET  /api/v1/cost-decisions/{id}  one record",
  },
  {
    "id": "limits",
    "title": "Limits",
    "body": "Checks count against the key owner's plan, the same as in the app. Each key has its own rate limits where the deployment turns them on: 60 checks an hour and 500 a day on /validate and /validate/cost. Responses carry X-RateLimit-Limit, X-RateLimit-Remaining and X-RateLimit-Reset; going over gets 429 with Retry-After. File size limits are the deployment's own.",
  },
  ...(docs ? [{
    "id": "console",
    "title": "Every endpoint",
    "body": "The API console lists every endpoint with its request fields and responses, from the running API.",
    "href": "/scalar",
    "link": "Open API console",
  }] : []),
  {
    "id": "sample",
    "title": "A recorded example",
    "body": "The public sample includes a downloadable recorded example, its process recommendation and the assumptions behind its estimate.",
    "href": "/sample",
    "link": "Explore the sample record"
  }
]} />;
}
