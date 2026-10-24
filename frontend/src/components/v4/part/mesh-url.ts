/**
 * The part page's 3D view across re-checks (de-17, de-22, np-20).
 *
 * `urlSlot` holds one blob URL at a time and revokes the old one only when a
 * new one replaces it (or the page goes away). Revoking it when a re-check
 * merely starts left the viewer loading a dead URL, which failed, and the page
 * then said "No 3D view on this device" until Retry.
 *
 * `no3dTitle` says why there's no picture without blaming the device unless
 * WebGL really is missing. Pure, for node --test.
 */

export interface UrlSlot {
  /** Make a URL for this blob; the previous one is revoked now that it's replaced. */
  set(blob: Blob): string;
  /** Revoke the current URL (nothing shows it any more). */
  clear(): void;
}

export function urlSlot(create: (b: Blob) => string = (b) => URL.createObjectURL(b), revoke: (u: string) => void = (u) => URL.revokeObjectURL(u)): UrlSlot {
  let current: string | null = null;
  return {
    set(blob) {
      const prev = current;
      current = create(blob);
      if (prev) revoke(prev);
      return current;
    },
    clear() {
      if (current) revoke(current);
      current = null;
    },
  };
}

export type ViewerStateLike = "loading" | "ready" | "failed" | "nowebgl";

export function no3dTitle(viewer: ViewerStateLike, mesh: { url: string | null; origin: string | null; error: string | null }): string {
  if (viewer === "nowebgl") return "No 3D view on this device";
  if (viewer === "failed" && mesh.url) return "The 3D view didn’t load";
  if (mesh.error) return "The 3D view didn’t load";
  return "No 3D view of this part here";
}
