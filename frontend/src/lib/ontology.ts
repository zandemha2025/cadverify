// 6-button manufacturing-method ontology (Cycle 4, spec §1.2 / §5.3).
// Mirrors the backend keys exactly so the labeling buttons and
// src.eval.ontology.LABELS agree. Order + hotkeys are fixed (§5.2).

export interface OntologyOption {
  key: string; // canonical label key sent to the backend
  text: string; // button text shown to the human labeler
  hot: string; // keyboard shortcut (1-6)
}

export const ONTOLOGY: OntologyOption[] = [
  { key: "additive", text: "3D Print", hot: "1" },
  { key: "subtractive", text: "CNC Machining", hot: "2" },
  { key: "injection_molding", text: "Injection Molding", hot: "3" },
  { key: "sheet_metal", text: "Sheet Metal / Stamping", hot: "4" },
  { key: "casting", text: "Casting", hot: "5" },
  { key: "unsure_other", text: "Unsure / Other", hot: "6" },
];

export const LABEL_KEYS: string[] = ONTOLOGY.map((o) => o.key);
