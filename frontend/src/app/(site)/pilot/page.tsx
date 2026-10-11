import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";
import { PilotForm } from "../company/pilot-form";

export const metadata: Metadata = {
  title: "Pilot — ScaleCad",
  description: "Qualify with 25 representative parts, then scope a $7,500, 4–6 week evaluation of up to 500 parts against your plant’s equipment and actuals.",
  alternates: { canonical: "/pilot" },
};

export default async function PilotPage({ searchParams }: { searchParams: Promise<{ workflow?: string }> }) {
  const { workflow } = await searchParams;
  return <DocumentPage label="Pilot" title="Find out which work belongs on your floor." intro="Start with a free, team-assisted 25-part qualification. If the fit is right, agree on a measured pilot before committing." sections={[
    {
      id: "inputs",
      title: "Start with representative inputs.",
      body: "Bring up to 25 representative STL, STEP or IGES parts, material and tolerance requirements, your equipment list, rates, volumes and current buy prices. Agree on a data boundary before sharing CAD. Missing inputs stay visible as unknowns.",
    },
    {
      id: "scope",
      title: "Agree on the paid evaluation.",
      body: "$7,500 covers 4–6 weeks, one plant, agreed process families and up to 500 supported part numbers. The fee is credited toward your first-year annual agreement if you continue. Schedule and success criteria are agreed in the order form after input readiness is checked.",
      href: "/pricing",
      link: "Review pricing and scope",
    },
    {
      id: "outcome",
      title: "Review a decision brief, including the misses.",
      body: "Review in-house candidates, capability gaps, resource estimates against your supplied buy prices, and validation against held-out actuals. Candidate equipment upgrades need a machine-specific engineering review. Preliminary screening is not a validated make-vs-buy decision; turnaround is agreed after intake.",
    },
  ]} cta={false}><section id="pilot"><h2>Request a 25-part qualification.</h2><PilotForm initialWorkflow={workflow} /></section></DocumentPage>;
}
