import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {
  title: "Contact — ScaleCAD",
  description: "Contact ScaleCAD about pilots, product questions, support and security.",
  alternates: { canonical: "/contact" },
};

export default function ContactPage() {
  return <DocumentPage label="Contact" title="Talk through the decision." intro="Tell us about your plant, your parts and the question you need to answer." sections={[
    { id: "general", title: "Product questions and support", body: "For product, access and deployment questions, email nazeem@scalecad.ai.", href: "mailto:nazeem@scalecad.ai", link: "Email ScaleCAD" },
    { id: "pilots", title: "Pilot evaluations", body: "For qualification and pilot scoping, email nazeem@scalecad.ai or use the pilot intake form. Agree on data handling before sharing sensitive CAD.", href: "/pilot", link: "Plan a pilot" },
    { id: "security", title: "Security and privacy", body: "For vulnerabilities, security reviews, privacy requests and data-boundary questions, email nazeem@scalecad.ai.", href: "mailto:nazeem@scalecad.ai", link: "Contact the security point of contact" },
  ]} cta={false} />;
}
