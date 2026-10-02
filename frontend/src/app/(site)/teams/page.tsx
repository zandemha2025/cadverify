import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Workflows — CadVerify", "description": "One part can raise different questions for engineering, manufacturing and sourcing. Choose the decision on your desk; the relevant evidence follows.", "alternates": {"canonical": "/teams"}};

export default function Page() {
  return <DocumentPage label="Workflows" title="Start with the work you need to move forward." intro="One part can raise different questions for engineering, manufacturing and sourcing. Choose the decision on your desk; the relevant evidence follows." sections={[
  {
    "id": "in-house-manufacturing",
    "title": "Know which work belongs on your floor.",
    "body": "A part needs making. Start with whether your equipment can do the job, what resources it needs and what capability is missing.",
    "href": "/teams/in-house-manufacturing",
    "link": "Explore in-house manufacturing"
  },
  {
    "id": "design-engineering",
    "title": "Find the manufacturing issue before the next review.",
    "body": "See which features need attention, which process they affect and what to investigate before handing over the design.",
    "href": "/teams/design-engineering",
    "link": "Explore design engineering"
  },
  {
    "id": "cost-engineering",
    "title": "Bring a defensible estimate to the review.",
    "body": "Spend the conversation on the inputs that matter: material, machine time, labor and setup. Keep every source available when the number is challenged.",
    "href": "/teams/cost-engineering",
    "link": "Explore cost engineering"
  },
  {
    "id": "sourcing",
    "title": "Ask a better question about the quote.",
    "body": "Understand what drives the resource estimate so you can have a specific conversation about process, capacity and the assumptions behind a supplier’s price.",
    "href": "/teams/sourcing",
    "link": "Explore sourcing"
  },
  {
    "id": "shop-owners",
    "title": "See whether the incoming job fits your shop.",
    "body": "Start with the equipment, rates and manufacturing questions that determine whether a part belongs on your floor.",
    "href": "/teams/shop-owners",
    "link": "Explore shop owners"
  }
]} />;
}
