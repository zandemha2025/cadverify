/**
 * Where a page's content starts on desktop, under its page head as it is drawn.
 *
 * The boards place content 132 px down (the head at 20 px, up to 104 px tall,
 * and an 8 px gap). A head that wraps (a long title, its facts or its tools on
 * two rows) is taller than that and would run over the first line of content,
 * so the content starts 8 px under the head's bottom instead; never above the
 * page's own offset. Pure, so `node --test` runs it.
 */
export const DRAWN_CONTENT_TOP = 132;
export const HEAD_GAP = 8;

export function headEnd(headTop: number, headHeight: number, base: number = DRAWN_CONTENT_TOP): number {
  return Math.max(base, Math.ceil(headTop + headHeight + HEAD_GAP));
}
