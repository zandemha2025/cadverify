export type WorkspaceScreen =
  | "home"
  | "verify"
  | "catalog"
  | "records"
  | "programs"
  | "machines"
  | "triage"
  | "calibration"
  | "compare";

const WORKSPACE_SCREENS = new Set<WorkspaceScreen>([
  "home",
  "verify",
  "catalog",
  "records",
  "programs",
  "machines",
  "triage",
  "calibration",
  "compare",
]);

/**
 * Resolve a public Verify workspace deep link. Only top-level, ID-free screens
 * are accepted here; record/program detail screens must be opened with their
 * normal typed identifiers instead of a query-string cast.
 */
export function workspaceScreenFromSearch(search: string): WorkspaceScreen | null {
  const params = new URLSearchParams(search);
  const values = params.getAll("screen");
  if (values.length !== 1) return null;
  const value = values[0];
  return WORKSPACE_SCREENS.has(value as WorkspaceScreen)
    ? (value as WorkspaceScreen)
    : null;
}
