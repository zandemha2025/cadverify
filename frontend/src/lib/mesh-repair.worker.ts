import { BufferGeometry, Float32BufferAttribute, Mesh } from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { STLExporter } from "three/examples/jsm/exporters/STLExporter.js";
import { repairMesh } from "./mesh-repair";

self.onmessage = (event: MessageEvent<{bytes:ArrayBuffer;scale:number}>) => {
  try {
    self.postMessage({progress:"Reading the STL on your device…"});
    const geometry=new STLLoader().parse(event.data.bytes);
    if (event.data.scale!==1) geometry.scale(event.data.scale,event.data.scale,event.data.scale);
    const result=repairMesh(geometry.getAttribute("position").array as Float32Array, progress=>self.postMessage({progress}));
    geometry.dispose();
    if (result.reason) { self.postMessage({reason:result.reason,actions:result.actions}); return; }
    const out=new BufferGeometry();out.setAttribute("position",new Float32BufferAttribute(result.positions,3));
    const view=new STLExporter().parse(new Mesh(out),{binary:true});out.dispose();
    const bytes=view.buffer.slice(view.byteOffset,view.byteOffset+view.byteLength) as ArrayBuffer;
    self.postMessage({bytes,actions:result.actions}, {transfer:[bytes]});
  } catch {
    self.postMessage({reason:"Your device could not repair this file. The original is unchanged and no check was charged. Close other heavy tabs or repair the part in your CAD editor."});
  }
};
