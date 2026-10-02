import type { Metadata } from "next";
import { backendOrigin } from "@/lib/api-base";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Developers — CadVerify", "description": "Send supported CAD to the API and work with structured geometry, manufacturing findings and source-backed estimates.", "alternates": {"canonical": "/developers"}};

export default function Page() {
  const apiOrigin = backendOrigin();
  return <DocumentPage label="Developers" title="Bring the verification record into your own tools." intro="Send supported CAD to the API and work with structured geometry, manufacturing findings and source-backed estimates." sections={[
  {
    "id": "input",
    "title": "Use the file formats your team already has.",
    "body": "The application supports STL, STEP/STP and IGES/IGS inputs. The live API reference describes request fields, configured limits and response shapes."
  },
  {
    "id": "endpoints",
    "title": "Choose the analysis you need.",
    "body": "Your API key uses the same account allowance as the web app: 10 lifetime single-part checks, then request paid access. Validation and costing can share an X-Part-Check-ID UUID for the same uploaded file; each operation runs once per check. Inspect error responses before interpreting a result.",
    "code": `POST ${apiOrigin}/api/v1/validate
POST ${apiOrigin}/api/v1/validate/cost
GET  ${apiOrigin}/api/v1/cost-decisions
GET  ${apiOrigin}/api/v1/catalog

Authorization: Bearer <api-key>
X-Part-Check-ID: <new-uuid-for-this-check>
Content-Type: multipart/form-data`
  },
  {
    "id": "evidence",
    "title": "Preserve the meaning of the result.",
    "body": "Keep sources, confidence basis, validation status and process-specific findings in your interface. A missing value must not become a zero, and a default must not become a measured input.",
    "href": "/sample?view=resources",
    "link": "Inspect the example record"
  },
  {
    "id": "integrate",
    "title": "Start with the current API contract.",
    "body": "The OpenAPI console is the reference for your deployed backend. For self-hosted installations, check the configuration and deployment requirements with your team.",
    "href": "/api-reference",
    "link": "Open API reference"
  }
]} />;
}
