type Point = readonly [number, number, number];
type Triangle = readonly [Point, Point, Point];

const p = (x: number, y: number, z: number): Point => [x, y, z];
const v000 = p(0, 0, 0);
const v100 = p(20, 0, 0);
const v010 = p(0, 20, 0);
const v110 = p(20, 20, 0);
const v001 = p(0, 0, 20);
const v101 = p(20, 0, 20);
const v011 = p(0, 20, 20);
const v111 = p(20, 20, 20);

const triangles: Triangle[] = [
  [v000, v100, v101], [v000, v101, v001],
  [v010, v011, v111], [v010, v111, v110],
  [v000, v001, v011], [v000, v011, v010],
  [v100, v110, v111], [v100, v111, v101],
  [v000, v010, v110], [v000, v110, v100],
  [v001, v101, v111], [v001, v111, v011],
];

function vertex(point: Point): string {
  return `      vertex ${point.join(" ")}`;
}

/** A deterministic, watertight 20 mm cube that still runs through the real engine. */
export function sampleCubeFile(): File {
  const facets = triangles
    .map(
      ([a, b, c]) =>
        `  facet normal 0 0 0\n    outer loop\n${vertex(a)}\n${vertex(b)}\n${vertex(c)}\n    endloop\n  endfacet`
    )
    .join("\n");
  const stl = `solid cadverify_sample_cube\n${facets}\nendsolid cadverify_sample_cube\n`;
  return new File([stl], "sample-20mm-cube.stl", { type: "model/stl" });
}
