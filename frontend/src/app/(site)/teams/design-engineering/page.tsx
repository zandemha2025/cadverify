import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "Design engineering — ScaleCad", "description": "See which features need attention, which process they affect and what to investigate before handing over the design.", "alternates": {"canonical": "/teams/design-engineering"}};

export default function Page() {
  return <DocumentPage label="Design engineering" title="Find the manufacturing issue before the next review." intro="See which features need attention, which process they affect and what to investigate before handing over the design." sections={[
  {
    "id": "findings",
    "title": "Make the finding specific.",
    "body": "A useful finding names a measured feature and a process threshold. The sample identifies a sidewall below the injection-molding draft requirement and faces with restricted 3-axis access.",
    "href": "/sample?view=design",
    "link": "Inspect the design findings"
  },
  {
    "id": "process",
    "title": "Keep the issue tied to its process.",
    "body": "A molding blocker does not automatically make a part unmanufacturable. Compare alternatives and review the constraints that apply to each route."
  },
  {
    "id": "iterate",
    "title": "Change the design, then rerun it.",
    "body": "Use the findings to direct the next engineering review. Submit the revised geometry to check the result; a changed assumption is not a verified design fix."
  },
  {
    "id": "signoff",
    "title": "Keep engineering sign-off with your team.",
    "body": "The analysis supports a design decision. It does not replace operating-condition review, certification or production qualification."
  }
]} />;
}
