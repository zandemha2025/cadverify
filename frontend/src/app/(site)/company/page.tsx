import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";
import { PilotForm } from "./pilot-form";

export const metadata: Metadata = {"title": "Company & contact — CadVerify", "description": "CadVerify brings manufacturing evidence into the working conversation: what can be made, what needs attention, and what resources a decision depends on.", "alternates": {"canonical": "/company"}};

export default async function Page({ searchParams }: { searchParams: Promise<{ workflow?: string }> }) {
  const { workflow } = await searchParams;
  return <DocumentPage label="Company & contact" title="Make the decision easier to explain." intro="CadVerify brings manufacturing evidence into the working conversation: what can be made, what needs attention, and what resources a decision depends on." sections={[
  {
    "id": "approach",
    "title": "Built around the questions teams actually ask.",
    "body": "Can we make this on our equipment? Does this process fit the geometry? What drives the estimate? We put those questions before the product catalog."
  },
  {
    "id": "evaluation",
    "title": "Evaluate it on work you recognize.",
    "body": "A pilot starts with your parts, machines, rates and known outcomes. Agree on the questions and success criteria before measuring the result.",
    "bullets": [
      "Choose a representative set of parts and known outcomes.",
      "Declare equipment, materials and rates.",
      "Review results against held-out actuals, including misses.",
      "Record limitations and the next validation work."
    ]
  },
  {
    "id": "human",
    "title": "Talk to the people behind the product.",
    "body": "Discuss the workflow, data requirements and deployment constraints with our team. Reach us at nazeemahmed2023@gmail.com.",
    "href": "mailto:nazeemahmed2023@gmail.com",
    "link": "Email the team"
  }
]}><section id="pilot"><h2>Start with your question.</h2><PilotForm initialWorkflow={workflow} /></section></DocumentPage>;
}
