import type { Issue } from "../api";

export function geometryIssueTitle(issue: Issue): string {
  return ({
    NON_WATERTIGHT: "Open or non-manifold edges",
    INCONSISTENT_NORMALS: "Inconsistent face directions",
    DEGENERATE_FACES: "Collapsed triangles",
    MULTIPLE_BODIES: "Disconnected mesh pieces",
    NOT_SOLID_VOLUME: "Solid volume could not be confirmed",
  } as Record<string, string>)[issue.code] ?? issue.code.replaceAll("_", " ").toLowerCase();
}

export function geometryIssueLocation(issue: Issue): string {
  const shown = issue.edge_segments?.length ?? 0;
  if (shown) {
    const total = issue.edge_segment_count ?? shown;
    return `${shown.toLocaleString("en-US")} of ${total.toLocaleString("en-US")} affected edges highlighted`;
  }
  return issue.region_center
    ? "Marker shows one detected location"
    : "Whole-model finding; no exact location returned";
}
