import type { Metadata } from "next";
import { DocumentPage } from "@/components/site/document-page";

export const metadata: Metadata = {"title": "How it works — ScaleCAD", "description": "Move from a CAD file to a manufacturing decision with the inputs, assumptions and open questions still attached.", "alternates": {"canonical": "/method"}};

export default function Page() {
  return <DocumentPage label="How it works" title="Know how the answer was reached." intro="Move from a CAD file to a manufacturing decision with the inputs, assumptions and open questions still attached." sections={[
  {
    "id": "part",
    "title": "Start with the part and its requirements.",
    "body": "Upload the geometry and declare the conditions it needs to survive. Dimensions and features tell one part of the story; your material, environment and equipment tell the rest.",
    "href": "/sample",
    "link": "Inspect the sample geometry"
  },
  {
    "id": "route",
    "title": "Find a process worth investigating.",
    "body": "The engine uses geometry to suggest manufacturing routes and checks manufacturability for each process. A suggested route is a starting point for review, not an engineering approval.",
    "bullets": [
      "Check access, draft and other process-specific findings.",
      "Review your available machine envelope and materials.",
      "Investigate alternatives when the preferred route has blockers."
    ]
  },
  {
    "id": "sources",
    "title": "Open the inputs behind the estimate.",
    "body": "Material, machine time, labor and setup make up the resource estimate. Each driver carries its source. Shop inputs and user declarations stay distinct from defaults.",
    "href": "/sample?view=resources",
    "link": "Inspect a source-backed estimate"
  },
  {
    "id": "uncertainty",
    "title": "Keep uncertainty visible.",
    "body": "The recorded sample shows $14.14 per part for MJF at quantity 10, with an $8.49–$19.80 assumption band and zero measured outcomes. That range is not an accuracy claim. Actual results are needed to validate it."
  },
  {
    "id": "repair",
    "title": "Repair a part that isn’t a closed solid.",
    "body": "Every process needs a closed solid, so a file with open edges gets no price. ScaleCAD can try to close it on a copy: it joins faces that touch but were never joined, caps each remaining opening, then checks the copy like an upload. Your file is never changed and the repair doesn’t use a check. Each attempt ends with one of these answers.",
    "bullets": [
      "Repaired: the copy is a closed solid. Closing gaps moves the volume by less than 1%; the before and after are shown, and the copy can be downloaded or opened as a new part linked to yours.",
      "Closed, but the shape changed: a cap filled something that belongs to the design, such as a bore or a pocket. ScaleCAD says so, and by how much, when the volume moves more than 2%. Fix it in your CAD tool to keep the design.",
      "Not repaired, and why: a surface with no thickness has no solid to close, and a missing face can be too large to rebuild. For a STEP or IGES file whose faces aren’t sewn, ScaleCAD can sew them into a solid instead.",
      "In your CAD tool: heal or knit the faces into a solid (Import Diagnostics and Knit Surface in SOLIDWORKS, Stitch in Fusion, Fill and Enclose in Onshape, Repair Bodies and Stitch in Inventor, Import DataDoctor in Creo, Sew in NX), then export the solid body as STEP, not surfaces."
    ]
  },
  {
    "id": "review",
    "title": "Keep a person in the decision.",
    "body": "Your team reviews machine setup, operating conditions, material suitability and the final design. Save the evidence with the decision, then bring real hours and costs back into the next analysis."
  }
]} />;
}
