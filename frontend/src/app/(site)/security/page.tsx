import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Security — ScaleCAD", "description": "Your geometry is valuable intellectual property. Review the deployment, access and data handling that apply to your work before uploading sensitive files.", "alternates": {"canonical": "/security"}};

export default function Page() {
  return <DocumentPage label="Security" title="Understand the boundaries before sharing the CAD." intro="Your geometry is valuable intellectual property. Review the deployment, access and data handling that apply to your work before uploading sensitive files." sections={[
  {
    "id": "your-account",
    "title": "Your own account, in plain words.",
    "body": "Only people in your organization can open your files; on a personal account that is just you. ScaleCAD's administrators see account details, file names and check results, but can't open your files in ScaleCAD; people who run the servers can reach the storage, as with any hosted service. Your files aren't used to train any model and are never compared with another organization's parts. They're kept until you delete them: a part from the part's page, your whole account in Account, Security. The full list, with every outside service and what it receives, is on Your files and data once you sign in.",
    "href": "/app/account/data",
    "link": "Your files and data"
  },
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
    "body": "For security questionnaires, architecture notes, data-boundary questions or a security concern, contact nazeem@scalecad.ai.",
    "href": "mailto:nazeem@scalecad.ai",
    "link": "Email the security contact"
  }
]} />;
}
