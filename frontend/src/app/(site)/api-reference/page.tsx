import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "API reference — ScaleCad", "description": "Use the interactive OpenAPI console for the current endpoint contract. Keep the evidence and its limitations attached when you integrate the result.", "alternates": {"canonical": "/api-reference"}};

export default function Page() {
  return <DocumentPage label="API reference" title="One request. A record you can inspect." intro="Use the interactive OpenAPI console for the current endpoint contract. Keep the evidence and its limitations attached when you integrate the result." sections={[
  {
    "id": "console",
    "title": "Explore the API contract.",
    "body": "The console loads the configured backend’s OpenAPI specification. Your deployed backend is the source of truth for request fields and responses.",
    "href": "/scalar",
    "link": "Open API console"
  },
  {
    "id": "routes",
    "title": "Start with these endpoints.",
    "body": "Requests need credentials for the relevant API and organization. Uploaded files are subject to the backend’s configured limits.",
    "code": "POST /api/v1/validate\nPOST /api/v1/validate/cost\nGET  /api/v1/cost-decisions\nGET  /api/v1/catalog"
  },
  {
    "id": "sample",
    "title": "Inspect a record without connecting a backend.",
    "body": "The public sample includes a downloadable recorded example, its process recommendation and the assumptions behind its estimate.",
    "href": "/sample",
    "link": "Explore the sample record"
  }
]} />;
}
