// Data from cad-steps.json in the design data, verified against vendor help on 2026-10-19.

export type CadToolId = "solidworks" | "fusion" | "onshape" | "inventor" | "creo" | "nx";
export type CadFix = "draft" | "thicken" | "fillet" | "drain_hole" | "heal" | "export_step";

export interface CadStepSet {
  steps: string[];
  feature: string;
  source: string;
  verified: boolean;
}

export const CAD_TOOL_NAMES: Record<CadToolId, string> = {
  solidworks: "SOLIDWORKS",
  fusion: "Fusion",
  onshape: "Onshape",
  inventor: "Inventor",
  creo: "Creo",
  nx: "NX",
};

const SW = "https://help.solidworks.com/2026/english/SolidWorks/sldworks/";
const FUSION = "https://help.autodesk.com/cloudhelp/ENU/";
const ONSHAPE = "https://cad.onshape.com/help/Content/";
const INVENTOR = "https://help.autodesk.com/cloudhelp/2027/ENU/Inventor-Help/files/";
const CREO = "https://support.ptc.com/help/creo/creo_pma/r13/usascii/";
const NX = "https://docs.sw.siemens.com/en-US/doc/209349590/PL20241101461013487.";

export const CAD_STEPS: Record<CadFix, Record<CadToolId, CadStepSet>> = {
  draft: {
    solidworks: {
      steps: [
        "Insert › Features › Draft, then Manual. Type of Draft: Neutral Plane.",
        "Neutral Plane: the face the part pulls away from. Reverse direction if the preview tapers the wrong way.",
        "Faces to Draft: the outside faces ScaleCAD lit. Draft Angle: the outside angle.",
        "Add a second Draft for inside faces, such as a bore, at the inside angle.",
      ],
      feature: "Draft (Neutral Plane)",
      source: `${SW}t_neutral_plane_draft.htm`,
      verified: true,
    },
    fusion: {
      steps: [
        "Solid › Modify › Draft. Type: Fixed Plane.",
        "Pull Direction: the face the part pulls away from. Flip Pull Direction if the preview tapers the wrong way.",
        "Faces: the outside faces ScaleCAD lit. Angle: the outside angle.",
        "Run Draft again for inside faces, such as a bore, at the inside angle.",
      ],
      feature: "Draft (Fixed Plane)",
      source: `${FUSION}Fusion-Model/files/GUID-83C650C2-E602-4BBC-AC9A-AB9A96F07B72.htm`,
      verified: true,
    },
    onshape: {
      steps: [
        "Draft, type Neutral plane.",
        "Neutral plane: the face the part pulls away from.",
        "Entities to draft: the outside faces ScaleCAD lit; enter the outside angle.",
        "Add a second Draft for inside faces, such as a bore, at the inside angle.",
      ],
      feature: "Draft (Neutral plane)",
      source: `${ONSHAPE}PartStudio/draft.htm`,
      verified: true,
    },
    inventor: {
      steps: [
        "3D Model tab › Modify panel › Draft. Type: Fixed Plane.",
        "Pull direction: the face the part pulls away from. Flip Direction if the arrow points the wrong way.",
        "Faces: the outside faces ScaleCAD lit. Draft Angle: the outside angle.",
        "Add a second Draft for inside faces, such as a bore, at the inside angle.",
      ],
      feature: "Face Draft (Fixed Plane)",
      source: `${INVENTOR}GUID-38133835-2EDB-414E-ACB1-2487A96900F7.htm`,
      verified: true,
    },
    creo: {
      steps: [
        "Model › Draft. Draft surfaces: the outside faces ScaleCAD lit.",
        "Draft hinges and Pull direction: the face the part pulls away from.",
        "Angle 1: the outside angle; click the pull direction arrow to flip it if needed. OK.",
        "Add a second Draft for inside faces, such as a bore, at the inside angle.",
      ],
      feature: "Draft",
      source: `${CREO}part_modeling/part_modeling/To_Create_a_Draft_Feature.html`,
      verified: true,
    },
    nx: {
      steps: [
        "Home tab › Base group › Draft. Type: Face.",
        "Draw direction: the pull direction (+ZC is the default). Stationary face: the face the part pulls away from.",
        "Faces to draft: the outside faces ScaleCAD lit; Angle: the outside angle.",
        "Add a second Draft for inside faces, such as a bore, at the inside angle.",
      ],
      feature: "Draft (Face)",
      source: `${NX}modeling/draft_basic_ht`,
      verified: true,
    },
  },
  thicken: {
    solidworks: {
      steps: [
        "Insert › Face › Move. Choose Offset.",
        "Face(s) to move: the thin wall's face.",
        "Distance: the thickness to add.",
      ],
      feature: "Move Face (Offset)",
      source: `${SW}hidd_dve_feat_move_face.htm`,
      verified: true,
    },
    fusion: {
      steps: [
        "Solid › Modify › Offset Face.",
        "Select the thin wall's face and enter the thickness to add as the offset. OK.",
      ],
      feature: "Offset Face",
      source: `${FUSION}Fusion-Model/files/SLD-OFFSET-FACES.htm`,
      verified: true,
    },
    onshape: {
      steps: [
        "Move face. Type: Offset.",
        "Faces: the thin wall's face. End type Blind; distance: the thickness to add. Flip the arrow if it points inward.",
      ],
      feature: "Move face (Offset)",
      source: `${ONSHAPE}PartStudio/move_face.htm`,
      verified: true,
    },
    inventor: {
      steps: [
        "3D Model tab › Modify panel › Thicken/Offset. Output: Solid.",
        "Select Faces: the thin wall's face. Direction: Outside; Distance: the thickness to add.",
        "Boolean: Join. OK.",
      ],
      feature: "Thicken/Offset",
      source: `${INVENTOR}GUID-A9A4FF6E-9569-4BED-8AC7-EB245E6456F8.htm`,
      verified: true,
    },
    creo: {
      steps: [
        "Select the thin wall's face, then Flexible Modeling › Offset.",
        "Drag the handle or type the offset: the thickness to add. OK.",
      ],
      feature: "Flexible Modeling Offset (Offset Geometry)",
      source: `${CREO}part_modeling/flexible_modeling/to_offset_geometry.html`,
      verified: true,
    },
    nx: {
      steps: [
        "Surface tab › Base group › Offset Face.",
        "Select the thin wall's face; Offset: the thickness to add. OK.",
      ],
      feature: "Offset Face",
      source: `${NX}modeling/create_features_feat_offset_face_ht`,
      verified: true,
    },
  },
  fillet: {
    solidworks: {
      steps: [
        "Insert › Features › Fillet/Round, then Manual. Fillet Type: Constant Size.",
        "Items to Fillet: the sharp inside edges.",
        "Radius: the radius shown.",
      ],
      feature: "Fillet (Constant Size)",
      source: `${SW}c_fillet_propertymanager.htm`,
      verified: true,
    },
    fusion: {
      steps: [
        "Solid › Modify › Fillet. Type: Fillet.",
        "Select the sharp inside edges. Radius Type: Constant; enter the radius. OK.",
      ],
      feature: "Fillet",
      source: `${FUSION}Fusion-Model/files/SLD-FILLET-SOLID.htm`,
      verified: true,
    },
    onshape: {
      steps: [
        "Fillet, type Edge.",
        "Select the sharp inside edges. Measurement: Radius; Control: Distance; enter the radius.",
      ],
      feature: "Fillet (Edge)",
      source: `${ONSHAPE}PartStudio/fillet.htm`,
      verified: true,
    },
    inventor: {
      steps: [
        "3D Model tab › Modify panel › Fillet. The Constant Radius Edge Set is active.",
        "Select the sharp inside edges; enter the radius. OK.",
      ],
      feature: "Fillet (Constant Radius Edge Set)",
      source: `${INVENTOR}GUID-590A8760-FFBB-41C8-8169-6B7002207884.htm`,
      verified: true,
    },
    creo: {
      steps: [
        "Select the sharp inside edges, then Model › Round.",
        "Radius: the radius shown. OK.",
      ],
      feature: "Round",
      source: `${CREO}part_modeling/part_modeling/To_Create_a_Constant_Round.html`,
      verified: true,
    },
    nx: {
      steps: [
        "Home tab › Base group › Edge Blend. Shape: Circular.",
        "Select the sharp inside edges; Radius 1: the radius. OK.",
      ],
      feature: "Edge Blend",
      source: `${NX}modeling/create_features_feat_edgeblend_proc_const_ht`,
      verified: true,
    },
  },
  drain_hole: {
    solidworks: {
      steps: [
        "Select the face, then Insert › Features › Hole › Hole Wizard.",
        "Type tab: Hole Type Hole; set the size. End Condition: Blind, with Blind Hole Depth past the wall into the cavity.",
        "Positions tab: click where the hole goes. OK.",
      ],
      feature: "Hole Wizard",
      source: `${SW}c_hole_wizard_overview.htm`,
      verified: true,
    },
    fusion: {
      steps: [
        "Solid › Create › Hole. Placement: At Point (Single Hole); click the face where the hole goes.",
        "Hole Type: Simple; set the diameter.",
        "Extents: Distance, deeper than the wall so it opens into the cavity. OK.",
      ],
      feature: "Hole",
      source: `${FUSION}Fusion-Model/files/GUID-0DFCBD4F-5130-4CC9-B1A7-23C88147752A.htm`,
      verified: true,
    },
    onshape: {
      steps: [
        "Sketch a point on the face where the hole goes.",
        "Hole, Simple. Select the point; set the diameter; Start from part.",
        "Termination: Blind, deeper than the wall so it opens into the cavity.",
      ],
      feature: "Hole",
      source: `${ONSHAPE}PartStudio/hole.htm`,
      verified: true,
    },
    inventor: {
      steps: [
        "3D Model tab › Modify panel › Hole. Positions: click the face where the hole goes.",
        "Hole Type: Simple hole; Seat Type: None; set the diameter.",
        "Termination: Distance, deeper than the wall so it opens into the cavity. OK.",
      ],
      feature: "Hole",
      source: `${INVENTOR}GUID-94EB6947-0347-4888-870D-4BA22DB144D8.htm`,
      verified: true,
    },
    creo: {
      steps: [
        "Model › Hole, then Simple. Click the hole location on the face.",
        "Diameter: the hole size. Depth: Blind, deeper than the wall so it opens into the cavity. OK.",
      ],
      feature: "Hole (Simple)",
      source: `${CREO}part_modeling/part_modeling/To_Create_a_Simple_Hole.html`,
      verified: true,
    },
    nx: {
      steps: [
        "Home tab › Base group › Hole. Type: Simple; Hole Size: Custom.",
        "Click the face where the hole goes; set the Hole Diameter.",
        "Depth Limit: Value; Hole Depth deeper than the wall so it opens into the cavity. OK.",
      ],
      feature: "Hole (Simple)",
      source: `${NX}modeling/hole_adv_hole_general_ht`,
      verified: true,
    },
  },
  heal: {
    solidworks: {
      steps: [
        "Tools › Evaluate › Import Diagnostics. Attempt to Heal All.",
        "If faults remain, right-click each faulty face (Repair Face), then each gap (Heal Gap).",
        "For loose surfaces: Insert › Surface › Knit, select them, and check Create solid.",
      ],
      feature: "Import Diagnostics; Knit Surface",
      source: `${SW}HIDD_DVE_HEALING.htm`,
      verified: true,
    },
    fusion: {
      steps: [
        "Surface › Modify › Stitch. Select the faces to stitch.",
        "Raise Tolerance until the gaps close; edges within tolerance show green.",
        "OK. A watertight result becomes a solid body.",
      ],
      feature: "Stitch",
      source: `${FUSION}Fusion-Patch/files/SFC-STITCH.htm`,
      verified: true,
    },
    onshape: {
      steps: [
        "Camera and render options › Highlight boundary edges. Red edges are gaps.",
        "Fill: select the red boundary edges to cap each gap.",
        "Enclose, Result New: select the surfaces around the volume to make a solid part.",
      ],
      feature: "Highlight boundary edges; Fill; Enclose",
      source: `${ONSHAPE}Document/working_with_imported_cad.htm`,
      verified: true,
    },
    inventor: {
      steps: [
        "Surface panel › Repair Bodies; select the body.",
        "Find Errors, then Heal Errors with a small Allowable Change. OK.",
        "Repair tab › Modify panel › Stitch. Fill Gaps Smaller Than: the gap size; leave Maintain As Surface off.",
        "Finish. A closed volume becomes a solid.",
      ],
      feature: "Repair Bodies; Stitch",
      source: `${INVENTOR}GUID-B36ABA30-537E-4B15-B4DB-5D23202E1E1F.htm`,
      verified: true,
    },
    creo: {
      steps: [
        "Model Tree: right-click the part › Import Validation › Repair Imported Geometry.",
        "In Import DataDoctor: Heal › Repair for one-sided edges; Heal › Close for gaps.",
        "OK to leave Import DataDoctor, then OK on the Import tab.",
      ],
      feature: "Import DataDoctor (Heal › Repair, Heal › Close)",
      source: `${CREO}data_exchange/interface/To_Access_IDD_and_Repair_Geom_Failing_Validation.html`,
      verified: true,
    },
    nx: {
      steps: [
        "Surface tab › Combine group › Sew. Type: Sheet.",
        "Target: one sheet body; Tool: the others. Raise Tolerance if the gaps are larger.",
        "OK. Sheets that enclose a volume become a solid body.",
      ],
      feature: "Sew",
      source: `${NX}modeling/sew_feat_sew_sheet_ht`,
      verified: true,
    },
  },
  export_step: {
    solidworks: {
      steps: [
        "File › Save As. Save as type: STEP AP214.",
        "Options: Output as Solid/Surface geometry. OK, then Save.",
      ],
      feature: "Save As STEP",
      source: `${SW}HIDD_EXPORT_OPTIONS_STEP.htm`,
      verified: true,
    },
    fusion: {
      steps: [
        "File › Export. Type: STEP files (*.stp, *.step).",
        "Choose the Location, then Export.",
      ],
      feature: "Export",
      source: `${FUSION}Fusion-Designs/files/ASM-EXPORT-DESIGN.htm`,
      verified: true,
    },
    onshape: {
      steps: [
        "Right-click the part in the Parts list › Export.",
        "Format: STEP. Use latest version stays checked unless you need an older STEP version.",
      ],
      feature: "Export",
      source: `${ONSHAPE}File/exporting_files.htm`,
      verified: true,
    },
    inventor: {
      steps: [
        "File › Export › CAD Format. Save as type: STEP.",
        "Options › Application Protocol: 214, or 242 for a single part.",
      ],
      feature: "Export CAD Format (STEP)",
      source: `${INVENTOR}GUID-08D6DD13-3066-4210-9F19-5F7E8DB8AD5D.htm`,
      verified: true,
    },
    creo: {
      steps: [
        "File › Save As › Save a Copy. Type: STEP (*.stp).",
        "Options › Application protocol: ap214_is or ap242; the default is ap203_is. OK.",
      ],
      feature: "Save a Copy as STEP",
      source: `${CREO}data_exchange/interface/To_Export_a_Part_or_Assembly_to_STEP.html`,
      verified: true,
    },
    nx: {
      steps: [
        "File tab › Export › Translators, then the STEP translator.",
        "STEP 214 and STEP 242 are both supported; set the output file and OK.",
      ],
      feature: "Export (STEP translator)",
      source: `${NX}dataexchange/xid458358`,
      verified: true,
    },
  },
};
