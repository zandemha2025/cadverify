import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";
import { factSection, servicesSection } from "@/components/site/fact-sections";
import { ACCESS, DELETING, SECTIONS, SHARE_LINKS, TRANSIT, USE, WHERE, WHO, hostingSection } from "@/components/v4/trust/facts";
import { getDeploymentFacts } from "@/lib/deployment-facts";

export const metadata: Metadata = {"title": "Security — ScaleCAD", "description": "Where your CAD files are kept, who can see them, how sign-in works, every outside service that receives data, and what this deployment states about hosting.", "alternates": {"canonical": "/security"}};
export const revalidate = 300;

export default async function Page() {
  const hosting = hostingSection(await getDeploymentFacts());
  const transit = factSection(TRANSIT);
  return <DocumentPage label="Security" title="Where your CAD files go, and who can see them." intro="What ScaleCAD’s software does today, from the same facts as the Files and data page inside the app. Hosting facts come from this deployment’s configuration; anything it doesn’t state is marked as not stated." sections={[
    { id: "in-short", title: "In short", body: "The answers a security review asks first.", bullets: SECTIONS.filter((s) => s.short).map((s) => s.short as string) },
    factSection(WHERE),
    factSection(WHO),
    factSection(SHARE_LINKS),
    factSection(USE),
    factSection(ACCESS),
    { ...transit, id: "hosting", title: "Connections and hosting", body: "From this deployment’s configuration.", bullets: [...(transit.bullets ?? []), ...hosting.rows.map((r) => `${r.k}: ${r.v}`)] },
    factSection(DELETING, { href: "/privacy#retention", link: "Privacy requests" }),
    servicesSection(),
    { id: "contact", title: "Security contact", body: "For security questionnaires, architecture notes, single sign-on and directory sync (SCIM) setup, or a security concern, email nazeem@scalecad.ai. Nothing on this page is a certification.", href: "mailto:nazeem@scalecad.ai", link: "Email the security contact" },
  ]} />;
}
