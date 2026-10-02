import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Service status — CadVerify", "description": "The public automated incident feed is not connected yet. This page does not claim that any service is currently healthy.", "alternates": {"canonical": "/status"}};

export default function Page() {
  return <DocumentPage label="Service status" title="Service updates, with the limits stated." intro="The public automated incident feed is not connected yet. This page does not claim that any service is currently healthy." sections={[
  {
    "id": "availability",
    "title": "Public metrics are not available.",
    "body": "Hosted app, API and worker uptime are not published here yet. We do not substitute synthetic uptime for a live monitoring feed."
  },
  {
    "id": "support",
    "title": "Use your deployment’s support channel.",
    "body": "Pilot customers receive deployment-specific incident communication. For an access problem or support question, contact the team with the deployment and the issue you are seeing.",
    "href": "mailto:nazeemahmed2023@gmail.com",
    "link": "Contact support"
  }
]} cta={false} />;
}
