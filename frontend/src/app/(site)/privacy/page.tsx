import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Privacy — ScaleCad", "description": "ScaleCad processes uploaded files to create verification records: geometry measurements, manufacturability findings, cost drivers, provenance, and user decisions. The product is built to keep the audit record, not to republish your CAD.", "alternates": {"canonical": "/privacy"}};

export default function Page() {
  return <DocumentPage label="Privacy" title="How your files and account data are handled." intro="ScaleCad processes uploaded files to create verification records: geometry measurements, manufacturability findings, cost drivers, provenance, and user decisions. The product is built to keep the audit record, not to republish your CAD." sections={[
  {
    "id": "collect",
    "title": "What we collect",
    "body": "Account details, authentication events, uploaded files, generated reports, machine/rate declarations, pilot correspondence, and operational telemetry needed to run and secure the service."
  },
  {
    "id": "use",
    "title": "How it is used",
    "body": "To authenticate users, compute and store verification records, support pilots, diagnose incidents, prevent abuse, and improve the engine when you have agreed to that use."
  },
  {
    "id": "retention",
    "title": "Retention and deletion",
    "body": "Pilot and customer retention terms are governed by the applicable agreement. For privacy requests, contact nazeemahmed2023@gmail.com.",
    "href": "mailto:nazeemahmed2023@gmail.com",
    "link": "Contact the privacy team"
  }
]} cta={false} />;
}
