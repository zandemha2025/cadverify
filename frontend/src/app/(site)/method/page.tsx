import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "How it works — ScaleCad", "description": "Move from a CAD file to a manufacturing decision with the inputs, assumptions and open questions still attached.", "alternates": {"canonical": "/method"}};

export default function Page() {
  return <DocumentPage label="How it works" title="Know how the answer was reached." intro="Move from a CAD file to a manufacturing decision with the inputs, assumptions and open questions still attached." sections={[
  {
    "id": "part",
    "title": "Start with the part and its requirements.",
    "body": "Upload the geometry and declare the conditions it needs to survive. Dimensions and features tell one part of the story; your material, environment and equipment tell the rest.",
    "href": "/sample",
    "link": "Inspect the sample geometry"
  },
  {
    "id": "route",
    "title": "Find a process worth investigating.",
    "body": "The engine uses geometry to suggest manufacturing routes and checks manufacturability for each process. A suggested route is a starting point for review, not an engineering approval.",
    "bullets": [
      "Check access, draft and other process-specific findings.",
      "Review your available machine envelope and materials.",
      "Investigate alternatives when the preferred route has blockers."
    ]
  },
  {
    "id": "sources",
    "title": "Open the inputs behind the estimate.",
    "body": "Material, machine time, labor and setup make up the resource estimate. Each driver carries its source. Shop inputs and user declarations stay distinct from defaults.",
    "href": "/sample?view=resources",
    "link": "Inspect a source-backed estimate"
  },
  {
    "id": "uncertainty",
    "title": "Keep uncertainty visible.",
    "body": "The recorded sample shows $14.14 per part for MJF at quantity 10, with an $8.49–$19.80 assumption band and zero measured outcomes. That range is not an accuracy claim. Actual results are needed to validate it."
  },
  {
    "id": "review",
    "title": "Keep a person in the decision.",
    "body": "Your team reviews machine setup, operating conditions, material suitability and the final design. Save the evidence with the decision, then bring real hours and costs back into the next analysis."
  }
]} />;
}
