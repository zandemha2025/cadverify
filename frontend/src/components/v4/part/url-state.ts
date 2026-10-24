/**
 * The open view of a part, kept in its URL: ?lens= (which view) and ?qty= (the
 * quantity it's priced at), next to find and fix's own ?problem= / ?method= /
 * ?problems=. The URL is replaced, not pushed, so changing views doesn't fill
 * the history, and Back from any other page returns to the same view. The part
 * page reads both on open (part-page.tsx).
 *
 * Pure (runs under node --test).
 */

export interface PartView {
  lens: string;
  q: number;
  /** The quantities the record priced; qty is kept only when it is one of them. */
  qs: number[];
}

/** The search string for `view`, keeping every other parameter of `search` as it is. */
export function partSearch(search: string, view: PartView): string {
  const u = new URLSearchParams(search);
  u.set("lens", view.lens);
  if (view.qs.includes(view.q)) u.set("qty", String(view.q));
  else u.delete("qty");
  const s = u.toString();
  return s ? `?${s}` : "";
}
