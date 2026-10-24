import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {
  title: "Pricing — ScaleCad",
  description: "Start with a free 25-part pilot qualification. A scoped ScaleCad pilot is $7,500 for 4–6 weeks and up to 500 parts, credited toward year one.",
  alternates: { canonical: "/pricing" },
};

export default function PricingPage() {
  return <DocumentPage label="Pricing" title="Start small. Measure the value." intro="Qualify the fit on your parts before committing to a paid evaluation." sections={[
    {
      id: "qualification",
      title: "Free qualification · 25 parts",
      body: "A team-assisted review of up to 25 representative parts from one plant. We check data readiness, supported processes and whether a paid pilot can answer your question. This is separate from the 10 lifetime single-part checks included with a self-service account.",
      href: "/pilot",
      link: "Request a qualification",
    },
    {
      id: "pilot",
      title: "$7,500 pilot · 4–6 weeks · up to 500 parts",
      body: "One plant, an agreed set of process families, and up to 500 supported part numbers. The pilot starts after the agreed inputs are ready. Scope, schedule and acceptance criteria are confirmed in a signed order form.",
      bullets: [
        "Review parts against your declared equipment, materials and rates.",
        "Compare resource estimates with your supplied buy prices and volumes; review capability gaps and candidate upgrades.",
        "Validate a representative held-out subset against actual outcomes, recording misses and unknowns.",
        "Deliver a ranked decision brief with assumptions, limitations and recommended follow-up checks.",
        "Credit the $7,500 pilot fee toward your first-year annual agreement if you continue.",
      ],
      href: "/pilot",
      link: "Scope a pilot",
    },
    {
      id: "annual",
      title: "Annual deployment · quoted to scope",
      body: "Annual pricing is agreed after the pilot, based on sites, part volume, support and deployment requirements. Custom integrations, data cleanup and self-hosted deployment work are scoped separately.",
      href: "/contact",
      link: "Discuss your requirements",
    },
  ]} cta={false} />;
}
