import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Data processing — CadVerify", "description": "A data-processing addendum is available for pilots and enterprise deployments. It covers processing purpose, confidentiality, assistance with data-subject requests, deletion/return, and subprocessor notice.", "alternates": {"canonical": "/dpa"}};

export default function Page() {
  return <DocumentPage label="Data processing" title="Data terms travel with the pilot." intro="A data-processing addendum is available for pilots and enterprise deployments. It covers processing purpose, confidentiality, assistance with data-subject requests, deletion/return, and subprocessor notice." sections={[
  {
    "id": "subprocessors",
    "title": "Subprocessors",
    "body": "The exact list depends on deployment model. Hosted pilots may use cloud infrastructure, email delivery, observability, and support tooling. Self-hosted deployments can remove most hosted subprocessors."
  },
  {
    "id": "review",
    "title": "Security review",
    "body": "Security questionnaires, architecture notes, and deployment boundaries are handled during pilot intake. Contact nazeemahmed2023@gmail.com.",
    "href": "mailto:nazeemahmed2023@gmail.com",
    "link": "Start a security review"
  }
]} cta={false} />;
}
