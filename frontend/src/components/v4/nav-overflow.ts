/** Which edges of a sideways-scrolling tab row have more tabs past them (a 2 px slack for rounding). */
export function navOverflow(scrollLeft: number, clientWidth: number, scrollWidth: number): { left: boolean; right: boolean } {
  if (scrollWidth <= clientWidth + 2) return { left: false, right: false };
  return { left: scrollLeft > 2, right: scrollLeft + clientWidth < scrollWidth - 2 };
}
