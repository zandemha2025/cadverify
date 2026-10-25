import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";
import { factSection, servicesSection } from "@/components/site/fact-sections";
import { ACCOUNT, CHOICES, DELETING, USE, hostingSection } from "@/components/v4/trust/facts";
import { getDeploymentFacts } from "@/lib/deployment-facts";

export const metadata: Metadata = {"title": "Privacy — ScaleCAD", "description": "What ScaleCAD collects at sign-up and where it goes, your three separate privacy choices, every outside service that receives data, and how deleting works.", "alternates": {"canonical": "/privacy"}};
export const revalidate = 300;

export default async function Page() {
  const hosting = hostingSection(await getDeploymentFacts());
  return <DocumentPage label="Privacy" title="What we collect, where it goes, and what you choose." intro="The same facts as the Files and data page inside the app, stated before you sign up. Uploaded CAD files are used only to check, cost and fix your parts for your organization." sections={[
    factSection(ACCOUNT, { id: "collect" }),
    factSection(CHOICES, { id: "analytics" }),
    {
      id: "visitor-identification",
      title: "Business visitor identification",
      body: "Only with business visitor identification turned on in Privacy choices, RB2B uses cookies and public website visits to match business visitors with business contact details for sales follow-up. It never loads inside the app or on supplier share pages, and respects Do Not Track. RB2B also has its own opt-out.",
      href: "https://app.retention.com/optout",
      link: "Opt out with RB2B",
    },
    servicesSection(),
    factSection(USE),
    { ...factSection(DELETING, { id: "retention" }), bullets: [...(factSection(DELETING).bullets ?? []), `Backups (this deployment): ${hosting.rows.find((r) => r.k === "Backups")!.v}`] },
    { id: "contact", title: "Privacy requests", body: "For a copy of your data, a correction, or deletion you can’t do in the app, email nazeem@scalecad.ai from your account’s address.", href: "mailto:nazeem@scalecad.ai", link: "Contact the privacy team" },
  ]} cta={false} />;
}
