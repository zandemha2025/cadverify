import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Privacy — ScaleCad", "description": "ScaleCad processes uploaded files to create verification records: geometry measurements, manufacturability findings, cost drivers, provenance, and user decisions. The product is built to keep the audit record, not to republish your CAD.", "alternates": {"canonical": "/privacy"}};

export default function Page() {
  return <DocumentPage label="Privacy" title="How your files and account data are handled." intro="ScaleCad processes uploaded files to create verification records: geometry measurements, manufacturability findings, cost drivers, provenance, and user decisions. The product is built to keep the audit record, not to republish your CAD." sections={[
  {
    "id": "collect",
    "title": "What we collect",
    "body": "Account details include your name, email, optional phone number, signup time and browser timezone. We store contact and account details in our Notion CRM for support and pilot follow-up. Passwords, authentication credentials and CAD files are excluded from the CRM. We also process uploaded files, generated reports, machine/rate declarations and authentication events to operate the service."
  },
  {
    "id": "analytics",
    "title": "Analytics preferences",
    "body": "With your analytics permission, PostHog records page and product activity, campaign attribution, browser/device information, performance and sanitized errors. It may infer approximate country, region and city from your connection; this is not precise device location. Masked recordings are limited to public pages. Forms, passwords and CAD content are excluded. Use Analytics preferences on any page to decline or change your choice. Do Not Track is respected."
  },
  {
    "id": "visitor-identification",
    "title": "Business visitor identification",
    "body": "With your analytics permission, RB2B uses cookies and public-page visits to identify business visitors and match them with business contact information for sales follow-up. It loads only on public scalecad.ai pages without query strings or fragments, and respects Do Not Track. You can withdraw permission through Analytics preferences; the page reloads to stop the tracker. RB2B also provides its own opt-out.",
    "href": "https://app.retention.com/optout",
    "link": "Opt out with RB2B"
  },
  {
    "id": "use",
    "title": "How it is used",
    "body": "To authenticate users, compute and store verification records, support pilots, diagnose incidents, prevent abuse, and improve the engine when you have agreed to that use."
  },
  {
    "id": "retention",
    "title": "Retention and deletion",
    "body": "Pilot and customer retention terms are governed by the applicable agreement. For privacy requests, contact nazeem@scalecad.ai.",
    "href": "mailto:nazeem@scalecad.ai",
    "link": "Contact the privacy team"
  }
]} cta={false} />;
}
