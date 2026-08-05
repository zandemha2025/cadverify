type Point = readonly [number, number, number];
type Triangle = readonly [Point, Point, Point];

const point = (x: number, y: number, z: number): Point => [x, y, z];

// A recognizable L-shaped routing bracket: 50 × 40 × 6 mm, watertight, and
// intentionally simple enough to remain a deterministic real-engine fixture.
const outline: readonly (readonly [number, number])[] = [
  [0, 0],
  [50, 0],
  [50, 12],
  [14, 12],
  [14, 40],
  [0, 40],
];
const bottom = outline.map(([x, y]) => point(x, y, 0));
const top = outline.map(([x, y]) => point(x, y, 6));

const triangles: Triangle[] = [
  // Bottom (-Z) and top (+Z), triangulated without filling the L's cutout.
  [bottom[0], bottom[2], bottom[1]],
  [bottom[0], bottom[3], bottom[2]],
  [bottom[0], bottom[5], bottom[3]],
  [bottom[3], bottom[5], bottom[4]],
  [top[0], top[1], top[2]],
  [top[0], top[2], top[3]],
  [top[0], top[3], top[5]],
  [top[3], top[4], top[5]],
];

for (let index = 0; index < outline.length; index += 1) {
  const next = (index + 1) % outline.length;
  triangles.push(
    [bottom[index], bottom[next], top[next]],
    [bottom[index], top[next], top[index]],
  );
}

function vertex(value: Point): string {
  return `      vertex ${value.join(" ")}`;
}

/** A deterministic, watertight sample that still runs through the real engine. */
export function sampleBracketFile(): File {
  const facets = triangles
    .map(
      ([a, b, c]) =>
        `  facet normal 0 0 0\n    outer loop\n${vertex(a)}\n${vertex(b)}\n${vertex(c)}\n    endloop\n  endfacet`,
    )
    .join("\n");
  const stl = `solid proofshape_routing_bracket\n${facets}\nendsolid proofshape_routing_bracket\n`;
  return new File([stl], "sample-routing-bracket.stl", { type: "model/stl" });
}
