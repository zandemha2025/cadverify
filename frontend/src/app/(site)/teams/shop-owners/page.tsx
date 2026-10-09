import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Shop owners — ScaleCad", "description": "Start with the equipment, rates and manufacturing questions that determine whether a part belongs on your floor.", "alternates": {"canonical": "/teams/shop-owners"}};

export default function Page() {
  return <DocumentPage label="Shop owners" title="See whether the incoming job fits your shop." intro="Start with the equipment, rates and manufacturing questions that determine whether a part belongs on your floor." sections={[
  {
    "id": "fit",
    "title": "Check the route before committing capacity.",
    "body": "Review the suggested manufacturing process and its findings. Match the work to your declared equipment and materials.",
    "href": "/sample?view=process",
    "link": "Inspect the process example"
  },
  {
    "id": "rates",
    "title": "Work from your own operating inputs.",
    "body": "Bind machine and labor rates to the review and keep default assumptions visible. Review resource estimates in the context of the equipment you own."
  },
  {
    "id": "quote",
    "title": "Use the evidence to prepare your quote.",
    "body": "Review setup, machine time, material and labor before making a commercial commitment. The estimate supports your quoting work; it does not issue a supplier quote."
  },
  {
    "id": "learn",
    "title": "Compare the estimate with the completed job.",
    "body": "Bring real hours and costs back into the review. Measure where the model matched and where your shop’s experience says it needs work."
  }
]} />;
}
