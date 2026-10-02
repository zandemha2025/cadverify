import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Pilot report — CadVerify", "description": "A closeout should show where the analysis matched reality, where it missed, and what still needs work. This is the report structure, not a published customer outcome.", "alternates": {"canonical": "/pilot-report"}};

export default function Page() {
  return <DocumentPage label="Pilot report" title="Leave the pilot with evidence your team can use." intro="A closeout should show where the analysis matched reality, where it missed, and what still needs work. This is the report structure, not a published customer outcome." sections={[
  {
    "id": "accuracy",
    "title": "Held-out accuracy.",
    "body": "Compare results on parts that were not used to tune the model. Include residuals and misses, rather than presenting only the best examples."
  },
  {
    "id": "floor",
    "title": "The declared floor.",
    "body": "Document the machines, rates, materials and assumptions used by the analysis. The result is only meaningful in the context of those inputs."
  },
  {
    "id": "decisions",
    "title": "The decision record.",
    "body": "Keep the make, buy, acquire or redesign choices with their supporting evidence and the person who reviewed them."
  },
  {
    "id": "next",
    "title": "The work that remains.",
    "body": "Call out capability gaps, supplier questions and validation work. Agree on what additional inputs would make the next pass more useful.",
    "href": "/company#pilot",
    "link": "Plan an evaluation"
  }
]} />;
}
