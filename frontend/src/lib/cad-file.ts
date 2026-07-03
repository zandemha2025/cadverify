/**
 * The shared CAD upload contract — the file extensions the cost/DFM engine
 * accepts, in one place so the Dropzone `accept=`, the part door's pre-flight
 * guard, and any future caller all agree on exactly what a "part" is. Pure (no
 * React/DOM) so it is unit-tested with `node --test`.
 *
 * (PartWorkspace keeps its own inline on-submit check as defense-in-depth; this
 * is the front-door guard so an unsupported file never reaches the workspace.)
 */

export const CAD_EXTS = ["stl", "step", "stp"] as const;
export type CadExt = (typeof CAD_EXTS)[number];

/** the `accept=` attribute string for the <input type=file> / Dropzone. */
export const CAD_ACCEPT = ".stl,.step,.stp";

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

/** human-readable list of accepted types, e.g. "STL, STEP or STP". */
export function supportedCadLabel(): string {
  const upper = CAD_EXTS.map((e) => e.toUpperCase());
  return `${upper.slice(0, -1).join(", ")} or ${upper[upper.length - 1]}`;
}
