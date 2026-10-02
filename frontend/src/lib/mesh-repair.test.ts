import test from "node:test";
import assert from "node:assert/strict";
import { BoxGeometry } from "three";
import { repairMesh } from "./mesh-repair.ts";

const box = () => new Float32Array(new BoxGeometry(10,20,30).toNonIndexed().getAttribute("position").array);
test("local repair caps a missing triangle and preserves translated vertices",()=>{
  const source=box();for(let i=0;i<source.length;i++) source[i]+=[123,-45,67][i%3];
  const result=repairMesh(source.slice(9));
  assert.equal(result.reason,undefined);
  assert.equal(result.positions.length,source.length);
  assert.ok(result.actions.some(s=>s.includes("Added 1 triangle")));
  const vertices=new Set(Array.from({length:source.length/3},(_,i)=>Array.from(source.slice(i*3,i*3+3)).join(",")));
  for(let i=0;i<result.positions.length;i+=3) assert.ok(vertices.has(Array.from(result.positions.slice(i,i+3)).join(",")));
  assert.match(repairMesh(result.positions).reason??"",/No supported repair was needed/);
});
test("local repair corrects face directions, removes duplicates, and refuses ambiguity",()=>{
  const source=box(), a=source.slice(3,6), b=source.slice(6,9);source.set(b,3);source.set(a,6);
  assert.equal(repairMesh(source).reason,undefined);
  const duplicate=new Float32Array(source.length+9);duplicate.set(source);duplicate.set(source.slice(0,9),source.length);
  assert.ok(repairMesh(duplicate).actions.some(s=>s.includes("duplicate or collapsed")));
  const extra=new Float32Array(source.length+9);extra.set(box());
  extra.set([5,10,15,5,-10,15,9,0,20],source.length);
  assert.match(repairMesh(extra).reason??"",/more than two faces/);
  assert.match(repairMesh(new Float32Array([NaN,0,0,1,0,0,0,1,0])).reason??"",/invalid coordinates/);
});

test("local repair closes a planar face and preserves separate bodies",()=>{
  const source=box();
  const second=box();for(let i=0;i<second.length;i+=3) second[i]+=100;
  const two=new Float32Array(source.length-18+second.length);
  two.set(source.slice(18));two.set(second,source.length-18);
  const result=repairMesh(two);
  assert.equal(result.reason,undefined);
  assert.equal(result.positions.length,source.length*2);
  assert.ok(result.actions.some(s=>s.includes("Retained 2 connected shells")));
  assert.match(repairMesh(result.positions).reason??"",/No supported repair was needed/);
});

test("local repair refuses non-planar holes and ambiguous inward shells",()=>{
  const source=box().slice(18);
  // Displace one corner of the open square across every incident triangle.
  for(let i=0;i<source.length;i+=3) if(source[i]===5 && source[i+1]===10 && source[i+2]===15) source[i]+=2;
  assert.match(repairMesh(source).reason??"",/non-planar or meet ambiguously/);
  const outer=box(), inner=box();
  for(let i=0;i<inner.length;i++) inner[i]*=0.5;
  for(let i=0;i<inner.length;i+=9) {const a=inner.slice(i+3,i+6);inner.set(inner.slice(i+6,i+9),i+3);inner.set(a,i+6);}
  const combined=new Float32Array(outer.length+inner.length);combined.set(outer);combined.set(inner,outer.length);
  assert.match(repairMesh(combined).reason??"",/may be a cavity or an inverted part/);
});
