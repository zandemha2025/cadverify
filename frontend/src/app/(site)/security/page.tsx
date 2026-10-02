import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Security — CadVerify", "description": "Your geometry is valuable intellectual property. Review the deployment, access and data handling that apply to your work before uploading sensitive files.", "alternates": {"canonical": "/security"}};

export default function Page() {
  return <DocumentPage label="Security" title="Understand the boundaries before sharing the CAD." intro="Your geometry is valuable intellectual property. Review the deployment, access and data handling that apply to your work before uploading sensitive files." sections={[
  {
    "id": "deployment",
    "title": "Choose the deployment boundary.",
    "body": "Hosted and self-hosted requirements are part of the pilot discussion. Confirm where files are processed, where records are retained and which external services are involved for your deployment."
  },
  {
    "id": "access",
    "title": "Review access and accountability.",
    "body": "The application uses authenticated accounts and organization access. Review roles, API keys, audit requirements and your team’s onboarding process during the security review."
  },
  {
    "id": "data",
    "title": "Agree on retention and use.",
    "body": "Retention, deletion and any permitted use of customer data belong in the agreement. The privacy summary and data-processing addendum describe the questions to resolve.",
    "href": "/dpa",
    "link": "Read about data processing"
  },
  {
    "id": "assurance",
    "title": "Ask for the evidence available today.",
    "body": "A compliance plan is not a certification. Request the current status and supporting security materials from the team; evaluate the controls for the deployment you intend to use."
  },
  {
    "id": "contact",
    "title": "Bring your security team into the conversation.",
    "body": "For security questionnaires, architecture notes, data-boundary questions or a security concern, contact nazeemahmed2023@gmail.com.",
    "href": "mailto:nazeemahmed2023@gmail.com",
    "link": "Email the security team"
  }
]} />;
}
