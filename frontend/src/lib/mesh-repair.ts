import { ShapeUtils, Vector2 } from "three";

type Edge = { a: number; b: number; faces: number[]; directions: number[] };
type Result = { positions: Float32Array; actions: string[]; reason?: string };

/** Conservative repair: exact vertex welding, duplicate/zero-area removal,
 * consistent winding and planar boundary caps. No smoothing, simplification,
 * guessed non-planar surfaces or deletion of disconnected parts. */
export function repairMesh(input: Float32Array, progress: (message: string) => void = () => {}): Result {
  const vertices: number[][] = [], faces: number[][] = [];
  const vertexIds = new Map<string, number>(), uniqueFaces = new Set<string>();
  let removed = 0, reversed = 0, added = 0;
  const actions: string[] = [];
  const failed = (reason: string): Result => ({ positions: new Float32Array(), actions, reason });
  if (!input.length || input.length % 9) return failed("The STL does not contain complete triangles.");
  progress("Removing duplicate and collapsed triangles on your device…");
  for (let i = 0; i < input.length; i += 9) {
    const face: number[] = [];
    for (let j = 0; j < 9; j += 3) {
      const point = [input[i+j], input[i+j+1], input[i+j+2]];
      if (!point.every(Number.isFinite)) return failed("The file contains invalid coordinates. Re-export it from the source CAD.");
      const key = point.join(",");
      let id = vertexIds.get(key);
      if (id === undefined) { id = vertices.length; vertices.push(point); vertexIds.set(key, id); }
      face.push(id);
    }
    const [a,b,c] = face.map(id => vertices[id]);
    const u = b.map((n,k) => n-a[k]), v = c.map((n,k) => n-a[k]);
    const cross = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]];
    const key = [...face].sort((a,b) => a-b).join(",");
    if (cross.every(n => n === 0) || uniqueFaces.has(key)) { removed++; continue; }
    uniqueFaces.add(key); faces.push(face);
  }
  vertexIds.clear(); uniqueFaces.clear();
  if (removed) actions.push(`Removed ${removed.toLocaleString("en-US")} duplicate or collapsed triangles.`);
  if (!faces.length) return failed("No non-degenerate surface remains. Export a solid part from the source CAD.");
  const edgeKey = (a: number, b: number) => a < b ? `${a},${b}` : `${b},${a}`;
  function buildEdges() {
    const edges = new Map<string, Edge>();
    faces.forEach((face, fi) => {
      for (let i=0; i<3; i++) {
        const a=face[i], b=face[(i+1)%3], key=edgeKey(a,b);
        let edge=edges.get(key);
        if (!edge) { edge={a,b,faces:[],directions:[]}; edges.set(key,edge); }
        edge.faces.push(fi); edge.directions.push(a < b ? 1 : -1);
      }
    });
    return edges;
  }
  progress("Checking connected edges and face directions…");
  let edges=buildEdges();
  const nonManifold = [...edges.values()].filter(e => e.faces.length > 2).length;
  if (nonManifold) return failed(`After duplicate and collapsed-triangle cleanup, ${nonManifold.toLocaleString("en-US")} edges still join more than two faces. Fixing these would require choosing which surfaces to remove. The original is unchanged; inspect its highlighted edges to separate overlapping surfaces in your CAD editor.`);
  function orient(): number[][] | null {
    const flips=new Int8Array(faces.length), components: number[][]=[];
    for (let root=0; root<faces.length; root++) {
      if (flips[root]) continue;
      const stack=[root], component:number[]=[]; flips[root]=1;
      while (stack.length) {
        const fi=stack.pop()!; component.push(fi);
        for (let i=0;i<3;i++) {
          const face=faces[fi], edge=edges.get(edgeKey(face[i],face[(i+1)%3]))!;
          if (edge.faces.length!==2) continue;
          const slot=edge.faces[0]===fi ? 0 : 1, other=edge.faces[1-slot];
          const desired=flips[fi]*(edge.directions[slot]===edge.directions[1-slot] ? -1 : 1);
          if (flips[other] && flips[other]!==desired) return null;
          if (!flips[other]) { flips[other]=desired; stack.push(other); }
        }
      }
      // Preserve the majority's orientation while correcting local reversed faces.
      const sign=component.filter(fi=>flips[fi]<0).length > component.length/2 ? -1 : 1;
      for (const fi of component) if (flips[fi]*sign<0) { [faces[fi][1],faces[fi][2]]=[faces[fi][2],faces[fi][1]]; reversed++; }
      components.push(component);
    }
    return components;
  }
  if (!orient()) return failed("This surface cannot be oriented consistently. Repair its overlapping or twisted surfaces in the source CAD.");
  edges=buildEdges();
  progress("Closing planar boundary loops without moving existing vertices…");
  const boundary=[...edges.values()].filter(e=>e.faces.length===1);
  const outgoing=new Map<number,Edge[]>(), incoming=new Map<number,number>();
  for (const edge of boundary) { outgoing.set(edge.a,[...(outgoing.get(edge.a)??[]),edge]); incoming.set(edge.b,(incoming.get(edge.b)??0)+1); }
  const visited=new Set<Edge>();
  for (const start of boundary) {
    if (visited.has(start)) continue;
    const loop:number[]=[]; let edge:Edge|undefined=start;
    while (edge && !visited.has(edge) && outgoing.get(edge.a)?.length===1 && incoming.get(edge.a)===1) {
      visited.add(edge); loop.push(edge.a); edge=outgoing.get(edge.b)?.[0];
    }
    if (edge!==start || loop.length<3) continue;
    const points=loop.map(id=>vertices[id]), normal=[0,0,0], origin=points[0];
    // Newell normal in a local frame keeps translated parts numerically stable.
    for (let i=0;i<points.length;i++) {
      const a=points[i].map((n,k)=>n-origin[k]), b=points[(i+1)%points.length].map((n,k)=>n-origin[k]);
      normal[0]+=(a[1]-b[1])*(a[2]+b[2]); normal[1]+=(a[2]-b[2])*(a[0]+b[0]); normal[2]+=(a[0]-b[0])*(a[1]+b[1]);
    }
    const length=Math.hypot(...normal);
    if (!length) continue;
    const span=points.reduce((max,p)=>Math.max(max,Math.hypot(...p.map((n,k)=>n-origin[k]))),0);
    if (points.some(p=>Math.abs(p.reduce((sum,n,k)=>sum+(n-origin[k])*normal[k],0))/length > span*1e-6)) continue;
    const drop=normal.map(Math.abs).indexOf(Math.max(...normal.map(Math.abs)));
    const axes=[0,1,2].filter(k=>k!==drop);
    const triangles=ShapeUtils.triangulateShape(points.map(p=>new Vector2(p[axes[0]]-origin[axes[0]],p[axes[1]]-origin[axes[1]])),[]);
    if (triangles.length!==loop.length-2) continue;
    for (const tri of triangles) {
      const ids=tri.map(i=>loop[i]), [a,b,c]=ids.map(id=>vertices[id]);
      const u=b.map((n,k)=>n-a[k]), v=c.map((n,k)=>n-a[k]);
      const dot=(u[1]*v[2]-u[2]*v[1])*normal[0]+(u[2]*v[0]-u[0]*v[2])*normal[1]+(u[0]*v[1]-u[1]*v[0])*normal[2];
      if (dot>0) [ids[1],ids[2]]=[ids[2],ids[1]];
      faces.push(ids); added++;
    }
  }
  edges=buildEdges();
  const open=[...edges.values()].filter(e=>e.faces.length!==2).length;
  if (open) return failed(`${open.toLocaleString("en-US")} boundary edges remain. Their loops are non-planar or meet ambiguously; closing them would guess the intended shape. Rebuild those highlighted surfaces in the source CAD. No verification check was charged.`);
  const components=orient();
  if (!components) return failed("The repaired surface still has conflicting face directions. No verification check was charged.");
  for (const component of components) {
    const origin=vertices[faces[component[0]][0]];
    let volume=0;
    for (const fi of component) {
      const [a,b,c]=faces[fi].map(id=>vertices[id].map((n,k)=>n-origin[k]));
      volume+=(a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6;
    }
    if (!Number.isFinite(volume) || volume===0) return failed("A closed shell still has no measurable volume. Check overlapping or collapsed surfaces in the source CAD.");
    if (volume<0) {
      if (components.length>1) return failed("This file has multiple shells with an inward-facing shell. It may be a cavity or an inverted part; confirm that intent in the source CAD before repairing.");
      for (const fi of component) { [faces[fi][1],faces[fi][2]]=[faces[fi][2],faces[fi][1]]; reversed++; }
    }
  }
  if (reversed) actions.push(`Corrected ${reversed.toLocaleString("en-US")} triangle orientations.`);
  if (added) actions.push(`Added ${added.toLocaleString("en-US")} ${added === 1 ? "triangle" : "triangles"} across planar boundary loops.`);
  if (!removed && !reversed && !added) return failed("No supported repair was needed. The original geometry was left unchanged.");
  actions.push(`Retained ${components.length.toLocaleString("en-US")} connected ${components.length === 1 ? "shell" : "shells"}; existing vertex positions were not moved.`);
  const positions=new Float32Array(faces.length*9);
  faces.forEach((face,fi)=>face.forEach((id,j)=>positions.set(vertices[id],fi*9+j*3)));
  return {positions,actions};
}
