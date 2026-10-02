import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Terms — CadVerify", "description": "CadVerify provides computational makeability and cost evidence. It does not replace engineering sign-off, supplier qualification, safety certification, export-control review, or a human decision.", "alternates": {"canonical": "/terms"}};

export default function Page() {
  return <DocumentPage label="Terms" title="Use the verdict as evidence, not as blind authority." intro="CadVerify provides computational makeability and cost evidence. It does not replace engineering sign-off, supplier qualification, safety certification, export-control review, or a human decision." sections={[
  {
    "id": "accounts",
    "title": "Accounts",
    "body": "You are responsible for access to your account and organization. Invite links are single-use and must only be shared with the intended recipient."
  },
  {
    "id": "uploads",
    "title": "Uploads",
    "body": "You must have the rights needed to upload CAD and related data. The service may reject files that are unsupported, unsafe to process, or outside configured limits."
  },
  {
    "id": "agreements",
    "title": "Pilots and enterprise terms",
    "body": "Paid pilots and production deployments are governed by their signed order form, security exhibits, and data-processing terms."
  }
]} cta={false} />;
}
