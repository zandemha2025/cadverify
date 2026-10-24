/**
 * The neutral part glyph used where a part's preview would go. The part page
 * keeps a browser-local copy of each preview mesh; until a list can read it,
 * lists show this outline rather than fetch meshes or invent a shape.
 */
export function PartGlyph({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 26 26" fill="none" aria-hidden="true">
      <path d="M13 2.6 22.4 8v10L13 23.4 3.6 18V8L13 2.6Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M3.6 8 13 13.4 22.4 8M13 13.4v10" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  );
}

export function PartThumb({ size = 44, glyph = 22 }: { size?: number; glyph?: number }) {
  return (
    <span className="h-th" style={{ width: size, height: size }} aria-hidden="true">
      <PartGlyph size={glyph} />
    </span>
  );
}
