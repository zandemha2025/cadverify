import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Platform — CadVerify", "description": "Give engineering, manufacturing and sourcing a shared record to work from, with a clear view of what is known and what still needs review.", "alternates": {"canonical": "/platform"}};

export default function Page() {
  return <DocumentPage label="Platform" title="Keep the part, the decision and the evidence together." intro="Give engineering, manufacturing and sourcing a shared record to work from, with a clear view of what is known and what still needs review." sections={[
  {
    "id": "verify",
    "title": "Review one part.",
    "body": "Start with geometry, manufacturing routes, process-specific findings and the resources required. Inspect the supporting inputs before choosing what happens next.",
    "href": "/sample",
    "link": "Explore a recorded verification"
  },
  {
    "id": "floor",
    "title": "Bring your own manufacturing context.",
    "body": "Declare machines, materials and rates so the analysis reflects your equipment. Missing capability is a question to resolve, not an implied machine purchase.",
    "href": "/teams/in-house-manufacturing",
    "link": "Explore in-house manufacturing"
  },
  {
    "id": "catalog",
    "title": "Carry that context across your catalog.",
    "body": "Use part records, batch analysis and triage to organize a broader review. Failed or incomplete analyses remain visible so the team can decide what needs attention."
  },
  {
    "id": "record",
    "title": "Keep the decision reviewable.",
    "body": "Saved records and comparisons preserve the evidence behind a choice. Share a result with its assumptions, rather than copying a number out of context."
  },
  {
    "id": "fit",
    "title": "Fit the system to your workflow.",
    "body": "Use the web application for interactive reviews or the API for your own tools. Discuss data boundaries and deployment requirements before introducing sensitive files.",
    "href": "/developers",
    "link": "Explore the API"
  }
]} />;
}
