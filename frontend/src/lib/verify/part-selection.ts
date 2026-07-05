/**
 * A tiny in-memory selection hand-off for the Part standing page.
 *
 * The shell's `nav(screen)` carries no payload, and the shell holds no
 * `partSel`. So a surface that wants to open a SPECIFIC part's standing
 * (the catalog row, a records link, a machine's routed-parts list) sets the
 * selected part's `mesh_hash` here, then navigates to the `part` screen, which
 * reads it on mount. Absent a selection, the standing page defaults to the
 * org's most-recently-updated part (and offers a switcher).
 *
 * Deliberately NOT persisted — it is a transient UI hand-off, never a source of
 * truth. The real identity always comes back from the catalog row.
 */
let selected: string | null = null;

/** Remember which part (by mesh_hash / catalog part_key) to open next. */
export function setSelectedPart(meshHash: string | null): void {
  selected = meshHash;
}

/** The pending selection, or null to let the standing page pick the default. */
export function getSelectedPart(): string | null {
  return selected;
}
