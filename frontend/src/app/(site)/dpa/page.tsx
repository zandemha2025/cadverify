import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";
import { factSection, servicesSection } from "@/components/site/fact-sections";
import { DELETING, USE, hostingSection } from "@/components/v4/trust/facts";
import { getDeploymentFacts } from "@/lib/deployment-facts";

export const metadata: Metadata = {"title": "Data processing — ScaleCAD", "description": "The subprocessors ScaleCAD's code sends data to, the purpose of processing, deletion and return, and what this deployment states about hosting.", "alternates": {"canonical": "/dpa"}};
export const revalidate = 300;

export default async function Page() {
  const hosting = hostingSection(await getDeploymentFacts());
  return <DocumentPage label="Data processing" title="Subprocessors, purpose, deletion." intro="What ScaleCAD’s software does with customer data today. A pilot or enterprise agreement can add terms; a data-processing addendum is available on request." sections={[
    servicesSection({ id: "subprocessors", title: "Subprocessors", body: "Every outside service ScaleCAD’s code sends data to. The hosting provider holds files, results and accounts; it is named under Hosting when this deployment states it." }),
    factSection(hosting),
    factSection(USE, { title: "Purpose of processing" }),
    factSection(DELETING, { title: "Deletion and return", href: "/privacy#retention", link: "Privacy requests" }),
    { id: "review", title: "Security review", body: "Security questionnaires, architecture notes and the addendum itself: nazeem@scalecad.ai.", href: "mailto:nazeem@scalecad.ai", link: "Start a security review" },
  ]} cta={false} />;
}
