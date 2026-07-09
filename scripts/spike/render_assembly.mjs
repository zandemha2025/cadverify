// SPIKE render: prove we can show a REAL part inside its REAL assembly.
// Serves the per-part world-space OBJs (from probe_assembly.py) + three.js,
// loads them all into a headless three.js scene, and screenshots:
//   01-full-assembly.png              -> whole assembly, per-part colors
//   02-part-highlighted-in-context.png-> ONE part bright, the rest dimmed
// Positions come straight from gmsh's baked world coords (OBJs untransformed).
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";

const require = createRequire("/home/user/cadverify/frontend/package.json");
const pw = require("playwright-core");
const threeRoot = path.dirname(path.dirname(require.resolve("three")));

const extractDir = "/home/user/cadverify/.claude/worktrees/agent-a72a691632fa055ce/outputs/human-sim/assembly-real/extract";
const outDir = "/home/user/cadverify/.claude/worktrees/agent-a72a691632fa055ce/outputs/human-sim/assembly-real";
const manifest = JSON.parse(readFileSync(path.join(extractDir, "extraction.json"), "utf8"));

// Focus part = the "handle": highlight one L-BRACKET (tag 10) seated among plate/rod/bolts.
const FOCUS_TAG = 10;

function shortName(label) {
  // last path segment, strip " & & 256"
  const seg = label.split("/").filter(Boolean).pop() || label;
  return seg.replace(/\s*&\s*&\s*\d+\s*$/, "").trim();
}

const parts = manifest.parts.map((p) => ({
  tag: p.tag,
  obj: p.obj,
  name: shortName(p.occ_label),
  fullpath: p.occ_label,
}));

const ctype = (f) =>
  f.endsWith(".js") || f.endsWith(".mjs") ? "text/javascript; charset=utf-8"
  : f.endsWith(".json") ? "application/json; charset=utf-8"
  : f.endsWith(".obj") ? "text/plain; charset=utf-8"
  : "application/octet-stream";

const html = `<!doctype html><html><head><meta charset="utf-8"/>
<style>html,body{margin:0;background:#0d1117;overflow:hidden}#c{display:block}</style>
<script type="importmap">{"imports":{
  "three":"/three/build/three.module.js",
  "three/addons/":"/three/examples/jsm/"
}}</script></head>
<body><canvas id="c"></canvas>
<script type="module">
import * as THREE from "three";
import { OBJLoader } from "three/addons/loaders/OBJLoader.js";
const W=1400,H=1000;
const parts = ${JSON.stringify(parts)};
const FOCUS = ${FOCUS_TAG};
const renderer=new THREE.WebGLRenderer({canvas:document.getElementById("c"),antialias:true,preserveDrawingBuffer:true});
renderer.setSize(W,H); renderer.setPixelRatio(1);
const scene=new THREE.Scene(); scene.background=new THREE.Color(0x0d1117);
const cam=new THREE.PerspectiveCamera(38,W/H,0.1,5000);
scene.add(new THREE.AmbientLight(0xffffff,0.55));
const d1=new THREE.DirectionalLight(0xffffff,0.9); d1.position.set(1,1.3,1.6); scene.add(d1);
const d2=new THREE.DirectionalLight(0xffffff,0.4); d2.position.set(-1,-0.5,-1); scene.add(d2);

const loader=new OBJLoader();
const palette=[0x5aa0ff,0xffb347,0x8bd17c,0xff7b9c,0xb08bff,0x54d1c4,0xe6c84f];
const group=new THREE.Group();
const meshesByTag={};
let done=0;
window.__ready=false;
function bboxOfGroup(g){const b=new THREE.Box3().setFromObject(g);return b;}

parts.forEach((p,i)=>{
  loader.load("/obj/"+p.obj,(o)=>{
    o.traverse((ch)=>{ if(ch.isMesh){
      ch.userData.tag=p.tag;
      ch.material=new THREE.MeshStandardMaterial({color:palette[i%palette.length],metalness:0.25,roughness:0.6});
      meshesByTag[p.tag]=meshesByTag[p.tag]||[]; meshesByTag[p.tag].push(ch);
    }});
    group.add(o);
    done++;
    if(done===parts.length){ finish(); }
  },undefined,(e)=>{done++; if(done===parts.length)finish();});
});

function frameCamera(){
  const b=bboxOfGroup(group); const c=b.getCenter(new THREE.Vector3()); const s=b.getSize(new THREE.Vector3());
  const r=Math.max(s.x,s.y,s.z);
  cam.position.set(c.x + r*1.1, c.y - r*1.35, c.z + r*1.25);
  cam.up.set(0,0,1);
  cam.lookAt(c);
}
function finish(){ scene.add(group); frameCamera(); renderer.render(scene,cam); window.__ready=true; }

// mode switch called from node
window.__setMode=(mode)=>{
  for(const tag in meshesByTag){
    const focus = (Number(tag)===FOCUS);
    meshesByTag[tag].forEach((m)=>{
      if(mode==="full"){
        m.material.opacity=1; m.material.transparent=false; m.material.emissive=new THREE.Color(0x000000);
      } else {
        if(focus){ m.material.color=new THREE.Color(0xff5a3c); m.material.emissive=new THREE.Color(0x5a1400); m.material.emissiveIntensity=0.6; m.material.opacity=1; m.material.transparent=false; }
        else { m.material.color=new THREE.Color(0x8892a0); m.material.opacity=0.14; m.material.transparent=true; m.material.emissive=new THREE.Color(0x000000);}
      }
    });
  }
  renderer.render(scene,cam);
};
</script></body></html>`;

const server = createServer(async (req, res) => {
  const u = new URL(req.url, "http://x");
  try {
    if (u.pathname === "/" ) { res.setHeader("content-type","text/html"); return res.end(html); }
    if (u.pathname.startsWith("/three/")) {
      const fp = path.resolve(threeRoot, decodeURIComponent(u.pathname.replace("/three/","")));
      if (!fp.startsWith(threeRoot) || !existsSync(fp)) { res.writeHead(404); return res.end("no"); }
      res.setHeader("content-type", ctype(fp)); return res.end(await readFile(fp));
    }
    if (u.pathname.startsWith("/obj/")) {
      const fp = path.resolve(extractDir, decodeURIComponent(u.pathname.replace("/obj/","")));
      if (!fp.startsWith(extractDir) || !existsSync(fp)) { res.writeHead(404); return res.end("no"); }
      res.setHeader("content-type","text/plain"); return res.end(await readFile(fp));
    }
    res.writeHead(404); res.end("no");
  } catch(e){ res.writeHead(500); res.end(String(e)); }
});

await new Promise((r)=>server.listen(0,r));
const port = server.address().port;

const browser = await pw.chromium.launch({
  executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  headless: true,
  args: ["--no-sandbox","--disable-dev-shm-usage","--use-angle=swiftshader","--use-gl=angle"],
});
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
page.on("pageerror",(e)=>console.log("PAGEERR",e.message));
await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "load" });
await page.waitForFunction("window.__ready===true", { timeout: 30000 });

await page.evaluate('window.__setMode("full")');
await page.waitForTimeout(300);
await page.screenshot({ path: path.join(outDir, "01-full-assembly.png") });

await page.evaluate('window.__setMode("highlight")');
await page.waitForTimeout(300);
await page.screenshot({ path: path.join(outDir, "02-part-highlighted-in-context.png") });

console.log("focus part:", parts.find(p=>p.tag===FOCUS_TAG)?.fullpath);
console.log("rendered", parts.length, "parts");
await browser.close();
server.close();
