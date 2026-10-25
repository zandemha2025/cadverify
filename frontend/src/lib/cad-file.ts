/**
 * The shared CAD upload contract — the file extensions the cost/DFM engine
 * accepts, in one place so the Dropzone `accept=`, the part door's pre-flight
 * guard, and any future caller all agree on exactly what a "part" is. Pure (no
 * React/DOM) so it is unit-tested with `node --test`.
 *
 * (PartWorkspace keeps its own inline on-submit check as defense-in-depth; this
 * is the front-door guard so an unsupported file never reaches the workspace.)
 */

export const CAD_EXTS = ["stl", "step", "stp", "iges", "igs"] as const;
export type CadExt = (typeof CAD_EXTS)[number];

/** the `accept=` attribute string for the <input type=file> / Dropzone. */
export const CAD_ACCEPT = CAD_EXTS.map((ext) => `.${ext}`).join(",");

/** the lowercased extension of a filename, or null when it has none. */
export function fileExt(name: string): string | null {
  const dot = name.lastIndexOf(".");
  if (dot < 0 || dot === name.length - 1) return null;
  return name.slice(dot + 1).toLowerCase();
}

/** true when `name` ends in an engine-supported CAD extension. */
export function isSupportedCad(name: string): boolean {
  const ext = fileExt(name);
  return ext != null && (CAD_EXTS as readonly string[]).includes(ext);
}

/**
 * A single part compressed for upload: any CAD extension plus `.gz`
 * (bracket.step.gz), or a `.zip` holding one part. The worker unpacks it
 * (backend `services/part_archive.py`); a ZIP of many parts is a catalog run.
 */
export function isCompressedCad(name: string): boolean {
  const lower = name.toLowerCase();
  if (lower.endsWith(".zip")) return lower.length > 4;
  if (!lower.endsWith(".gz")) return false;
  return isSupportedCad(lower.slice(0, -3));
}

/** What a single-part check takes: a CAD file, gzipped or not, or a one-part ZIP. */
export function isUploadableCad(name: string): boolean {
  return isSupportedCad(name) || isCompressedCad(name);
}

/** `accept=` for a single-part pick that also takes compressed parts. */
export const CAD_UPLOAD_ACCEPT = `${CAD_ACCEPT},.gz,.zip`;

/** human-readable list of accepted types, e.g. "STL, STEP or STP". */
export function supportedCadLabel(): string {
  const upper = CAD_EXTS.map((e) => e.toUpperCase());
  return `${upper.slice(0, -1).join(", ")} or ${upper[upper.length - 1]}`;
}

export interface UnsupportedCadGuidance {
  title: string;
  action: string;
}

/** Actionable, truthful recovery copy for a file the engine cannot ingest. */
export function unsupportedCadGuidance(name: string): UnsupportedCadGuidance {
  const ext = fileExt(name);
  if (ext === "sldprt" || ext === "sldasm") {
    return {
      title: "SolidWorks files need a STEP export",
      action: "Open the model in SolidWorks, export it as STEP AP242 (.step or .stp), then upload that exported file.",
    };
  }
  return {
    title: "This CAD format cannot be verified directly",
    action: `Export the model as ${supportedCadLabel()}, then upload the exported file.`,
  };
}
