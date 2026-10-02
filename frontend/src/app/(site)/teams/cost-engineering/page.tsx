import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Cost engineering — CadVerify", "description": "Spend the conversation on the inputs that matter: material, machine time, labor and setup. Keep every source available when the number is challenged.", "alternates": {"canonical": "/teams/cost-engineering"}};

export default function Page() {
  return <DocumentPage label="Cost engineering" title="Bring a defensible estimate to the review." intro="Spend the conversation on the inputs that matter: material, machine time, labor and setup. Keep every source available when the number is challenged." sections={[
  {
    "id": "drivers",
    "title": "Explain the drivers, not just the total.",
    "body": "Open the resource estimate line by line. The sample separates labor, setup, machine and material costs and preserves each source string.",
    "href": "/sample?view=resources",
    "link": "Inspect the resource estimate"
  },
  {
    "id": "basis",
    "title": "Distinguish declared rates from assumptions.",
    "body": "A shop rate can be declared while the cycle-time model still uses a default. Both facts belong beside the result. A precise decimal does not mean the model has been validated."
  },
  {
    "id": "compare",
    "title": "Compare on the same basis.",
    "body": "Keep process, quantity, materials and calibration visible when comparing alternatives. A supplier quote and an internal resource estimate answer different questions."
  },
  {
    "id": "actuals",
    "title": "Bring the actuals back.",
    "body": "Use measured outcomes to examine error and improve the next analysis. Until that evidence exists, the uncertainty remains an assumption band."
  }
]} />;
}
