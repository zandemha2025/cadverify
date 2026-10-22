/** Which public share routes the same-origin proxy may reach (app/api/public-share). */
const BASE62_ID = /^[A-Za-z0-9]{12}$/;

/**
 * The public routes a share link may reach: a check (/s/{id}); a part's link
 * (/s/cost/{id}) and its CAD when the sharer included it (/s/cost/{id}/cad);
 * a package's link (/s/pkg/{id}), its ZIP and each part's CAD
 * (/s/pkg/{id}/download.zip, /s/pkg/{id}/cad/{line}).
 */
export function publicSharePath(path: string[]): boolean {
  if (path[0] !== "s") return false;
  if (path.length === 2) return BASE62_ID.test(path[1]);
  if (path[1] === "cost" && BASE62_ID.test(path[2] ?? "")) return path.length === 3 || (path.length === 4 && path[3] === "cad");
  if (path[1] === "pkg" && BASE62_ID.test(path[2] ?? "")) {
    if (path.length === 3) return true;
    if (path.length === 4) return path[3] === "download.zip";
    return path.length === 5 && path[3] === "cad" && /^[1-9]\d{0,2}$/.test(path[4]);
  }
  return false;
}
