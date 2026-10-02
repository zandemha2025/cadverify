import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Sourcing — CadVerify", "description": "Understand what drives the resource estimate so you can have a specific conversation about process, capacity and the assumptions behind a supplier’s price.", "alternates": {"canonical": "/teams/sourcing"}};

export default function Page() {
  return <DocumentPage label="Sourcing" title="Ask a better question about the quote." intro="Understand what drives the resource estimate so you can have a specific conversation about process, capacity and the assumptions behind a supplier’s price." sections={[
  {
    "id": "drivers",
    "title": "Start with the driver that needs explaining.",
    "body": "Review material, machine time, labor and setup separately. Use the source record to frame your supplier questions.",
    "href": "/sample?view=resources",
    "link": "Inspect a cost breakdown"
  },
  {
    "id": "comparison",
    "title": "Keep the comparison honest.",
    "body": "Compare the same part, quantity, process and declared context. A cost model is not a supplier offer and does not include every commercial term."
  },
  {
    "id": "handoff",
    "title": "Share the evidence behind the decision.",
    "body": "Bring engineering and manufacturing into the review with the same record, including open design findings and missing information."
  },
  {
    "id": "qualification",
    "title": "Keep supplier qualification in your workflow.",
    "body": "Commercial negotiation, quality approval, delivery commitments and supplier qualification remain with your team."
  }
]} />;
}
