import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "In-house manufacturing — CadVerify", "description": "A part needs making. Start with whether your equipment can do the job, what resources it needs and what capability is missing.", "alternates": {"canonical": "/teams/in-house-manufacturing"}};

export default function Page() {
  return <DocumentPage label="In-house manufacturing" title="Know which work belongs on your floor." intro="A part needs making. Start with whether your equipment can do the job, what resources it needs and what capability is missing." sections={[
  {
    "id": "equipment",
    "title": "Start with the equipment you own.",
    "body": "Declare machine process families, build envelopes, supported materials and rates. Review the part against that context instead of relying on an anonymous shop assumption."
  },
  {
    "id": "fit",
    "title": "Separate a route from a machine match.",
    "body": "A geometry-led suggestion is only one part of the decision. Confirm envelope fit, material suitability and the operating requirements before planning production.",
    "href": "/sample?view=process",
    "link": "Inspect a suggested process"
  },
  {
    "id": "resources",
    "title": "Understand the resources you would commit.",
    "body": "Review the hours, material and declared rates. Owned-equipment resource cost and acquiring new capability are different decisions; keep them separate."
  },
  {
    "id": "review",
    "title": "Keep the exceptions in view.",
    "body": "Uncertain inputs and missing capability need a person. Save the decision with its evidence and bring actual outcomes back after the work is done."
  }
]} />;
}
