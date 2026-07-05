import type { Metadata } from "next";
import CostEngineeringCinematic from "./cost-engineering-cinematic";

/**
 * /teams/cost-engineering — "For Cost Engineering" persona journey.
 *
 * Server shell: owns per-page metadata, then renders the client cinematic
 * (the WebGL choreography + scroll acts live in the "use client" component).
 * The dark-theater register + `.site-theater` scope come from the (site) group
 * layout; the shared chrome (SiteNav / SiteFooterTagline / PartStage / evidence
 * primitives) comes from `@/components/site`.
 */

export const metadata: Metadata = {
  title: "For Cost Engineering — CadVerify",
  description:
    "You sign the number. You should be able to open it. From a CAD file to a resource-cost record you can defend line-by-line — every driver sourced, the ±40% band honest about being assumption-based, and eventually validated against your own invoices.",
};

export default function CostEngineeringPage() {
  return <CostEngineeringCinematic />;
}
