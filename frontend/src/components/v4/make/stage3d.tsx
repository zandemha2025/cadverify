"use client";

/**
 * The Make and fit 3D stage: one or more REAL meshes on a transparent canvas,
 * turned by drag (with momentum) or by the arrow keys, never zoomed (boards F1,
 * F2, F4). Sources are the server's own artifacts: a design revision's generated
 * STL, the GLB tessellation /validate/preview-mesh streams for a submitted file,
 * the exact collision shell /validate/fit returns, or a reconstruction's mesh.
 * Nothing is approximated: a layer that fails to load fails the stage.
 *
 * Layers share the source CAD frame (millimetres, Z up). `matrix` places a layer
 * (the fit's seating transform, row-major 4×4). `paint` colours triangles by
 * index, only when the caller knows the indices address this exact mesh.
 */
import * as React from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { ContactShadows, Environment, Lightformer, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { computeLayeredHighlightVertexColors } from "@/lib/highlight-colors";
import { probeWebGlSupport } from "@/lib/site/webgl";

export type StageSource = { kind: "stl-url"; url: string } | { kind: "glb-url"; url: string } | { kind: "glb-b64"; data: string };

export interface StageLayer {
  key: string;
  source: StageSource;
  look: "solid" | "ghost" | "overlap";
  matrix?: number[][] | null;
  paint?: { faces: number[]; color: string } | null;
  /** Leave out of the framing box (default: framed unless an overlap). */
  frame?: boolean;
}

export interface StageMarker {
  key: string;
  at: [number, number, number];
  color: string;
}

/** Filled by the stage: turns the view by `radians` about the vertical axis. */
export type StageController = React.RefObject<((radians: number) => void) | null>;

export type StageState = "loading" | "ready" | "failed" | "nowebgl";

const TARGET = 2;
const BASE = new THREE.Color("#c3c8cf");

/* ---------------- loading (cached per source) ---------------- */

type Loaded = { geometry: THREE.BufferGeometry; meshes: number };
const cache = new Map<string, Promise<Loaded>>();

function sourceKey(s: StageSource): string {
  if (s.kind === "glb-b64") {
    let h = 0;
    for (let i = 0; i < s.data.length; i += 97) h = (h * 31 + s.data.charCodeAt(i)) | 0;
    return `b64:${s.data.length}:${h}`;
  }
  return `${s.kind}:${s.url}`;
}

async function fromGlb(buffer: ArrayBuffer): Promise<Loaded> {
  const gltf = await new GLTFLoader().parseAsync(buffer, "");
  gltf.scene.updateMatrixWorld(true);
  const parts: THREE.BufferGeometry[] = [];
  gltf.scene.traverse((obj) => {
    const mesh = obj as THREE.Mesh;
    if (!mesh.isMesh) return;
    const g = mesh.geometry.index ? mesh.geometry.toNonIndexed() : mesh.geometry.clone();
    g.applyMatrix4(mesh.matrixWorld);
    const only = new THREE.BufferGeometry();
    only.setAttribute("position", g.getAttribute("position"));
    parts.push(only);
    mesh.geometry.dispose();
  });
  if (!parts.length) throw new Error("The mesh is empty.");
  const geometry = parts.length === 1 ? parts[0] : mergeGeometries(parts, false);
  if (!geometry) throw new Error("The mesh couldn’t be read.");
  return { geometry, meshes: parts.length };
}

async function load(s: StageSource): Promise<Loaded> {
  if (s.kind === "glb-b64") {
    const bytes = Uint8Array.from(atob(s.data), (c) => c.charCodeAt(0));
    return fromGlb(bytes.buffer);
  }
  const res = await fetch(s.url, { cache: "no-store" });
  if (!res.ok) throw new Error(`The mesh didn’t load (${res.status}).`);
  const buffer = await res.arrayBuffer();
  if (s.kind === "glb-url") return fromGlb(buffer);
  const g = new STLLoader().parse(buffer);
  const geometry = g.index ? g.toNonIndexed() : g;
  if (!geometry.getAttribute("position")?.count) throw new Error("The mesh is empty.");
  return { geometry, meshes: 1 };
}

function loadCached(s: StageSource): Promise<Loaded> {
  const key = sourceKey(s);
  const hit = cache.get(key);
  if (hit) return hit;
  const p = load(s).then((l) => {
    l.geometry.computeVertexNormals();
    l.geometry.computeBoundingBox();
    l.geometry.computeBoundingSphere();
    return l;
  });
  cache.set(key, p);
  p.catch(() => cache.delete(key));
  // Keep the cache small: old revisions and replaced files fall out first.
  while (cache.size > 16) cache.delete(cache.keys().next().value as string);
  return p;
}

function toMatrix(m: number[][] | null | undefined): THREE.Matrix4 {
  if (!m || m.length !== 4) return new THREE.Matrix4();
  return new THREE.Matrix4().fromArray(m.flat()).transpose();
}

/* ---------------- scene ---------------- */

function Layer({ layer, loaded }: { layer: StageLayer; loaded: Loaded }) {
  const matRef = React.useRef<THREE.MeshStandardMaterial>(null);
  const { invalidate } = useThree();
  const matrix = React.useMemo(() => toMatrix(layer.matrix), [layer.matrix]);
  const lit = layer.look === "solid" && !!layer.paint && layer.paint.faces.length > 0 && loaded.meshes === 1;
  React.useEffect(() => {
    const g = loaded.geometry;
    const pos = g.getAttribute("position");
    if (!pos || layer.look !== "solid") return;
    if (!lit) g.deleteAttribute("color");
    else
      g.setAttribute(
        "color",
        new THREE.BufferAttribute(
          computeLayeredHighlightVertexColors(pos.count, [{ faces: layer.paint!.faces, color: new THREE.Color(layer.paint!.color), priority: 1 }], BASE),
          3,
        ),
      );
    if (matRef.current) matRef.current.needsUpdate = true;
    invalidate();
  }, [loaded, lit, layer.paint, layer.look, invalidate]);

  return (
    <group matrix={matrix} matrixAutoUpdate={false}>
      <mesh geometry={loaded.geometry} renderOrder={layer.look === "overlap" ? 10 : layer.look === "ghost" ? 2 : 0}>
        {layer.look === "solid" ? (
          <meshStandardMaterial
            ref={matRef}
            color={lit ? "#ffffff" : "#c6ccd4"}
            vertexColors={lit}
            metalness={lit ? 0.25 : 0.7}
            roughness={lit ? 0.55 : 0.42}
            envMapIntensity={lit ? 0.8 : 1.1}
          />
        ) : layer.look === "ghost" ? (
          <meshStandardMaterial color="#9aa3ae" transparent opacity={0.17} depthWrite={false} side={THREE.DoubleSide} metalness={0.1} roughness={0.8} />
        ) : (
          <meshStandardMaterial color="#D92D20" emissive="#5b1111" emissiveIntensity={0.45} transparent opacity={0.8} depthTest={false} depthWrite={false} side={THREE.DoubleSide} />
        )}
      </mesh>
    </group>
  );
}

function Frame({ box, signature }: { box: THREE.Box3; signature: string }) {
  const { camera, size, invalidate } = useThree();
  React.useEffect(() => {
    const persp = camera as THREE.PerspectiveCamera;
    const s = box.getSize(new THREE.Vector3());
    const scale = TARGET / (Math.max(s.x, s.y, s.z) || 1);
    const radius = (s.length() / 2) * scale;
    const aspect = size.width / Math.max(1, size.height);
    const half = Math.atan(Math.tan((persp.fov * Math.PI) / 360) * Math.min(1, aspect));
    const dist = Math.max(2.6, (radius * 1.08) / Math.sin(half));
    camera.position.copy(new THREE.Vector3(0.62, 0.46, 0.66).normalize().multiplyScalar(dist));
    camera.lookAt(0, 0, 0);
    persp.updateProjectionMatrix();
    invalidate();
    // Frame once per framed set; resizes keep the user's turn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);
  return null;
}

function Rig({ turnRef, controls }: { turnRef: StageController; controls: React.RefObject<OrbitControlsImpl | null> }) {
  const { invalidate } = useThree();
  React.useEffect(() => {
    turnRef.current = (rad: number) => {
      const c = controls.current;
      if (!c) return;
      c.setAzimuthalAngle(c.getAzimuthalAngle() + rad);
      c.update();
      invalidate();
    };
    return () => {
      turnRef.current = null;
    };
  }, [turnRef, controls, invalidate]);
  return null;
}

export default function Stage3D({
  layers,
  markers = [],
  controller,
  onState,
}: {
  layers: StageLayer[];
  markers?: StageMarker[];
  controller: StageController;
  onState?: (s: StageState, detail?: string) => void;
}) {
  const [webgl, setWebgl] = React.useState<boolean | null>(null);
  const [reduce, setReduce] = React.useState(false);
  const [loaded, setLoaded] = React.useState<Map<string, Loaded>>(new Map());
  const controls = React.useRef<OrbitControlsImpl | null>(null);
  const stateRef = React.useRef(onState);
  React.useEffect(() => {
    stateRef.current = onState;
  }, [onState]);

  React.useEffect(() => {
    const ok = probeWebGlSupport();
    setWebgl(ok);
    if (!ok) stateRef.current?.("nowebgl");
    try {
      setReduce(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch {
      setReduce(false);
    }
  }, []);

  const sourcesKey = layers.map((l) => sourceKey(l.source)).join("|");
  React.useEffect(() => {
    if (webgl !== true || !layers.length) return;
    let live = true;
    stateRef.current?.("loading");
    Promise.all(layers.map((l) => loadCached(l.source).then((g) => [sourceKey(l.source), g] as const)))
      .then((pairs) => {
        if (!live) return;
        setLoaded(new Map(pairs));
        stateRef.current?.("ready");
      })
      .catch((e) => {
        if (live) stateRef.current?.("failed", e instanceof Error ? e.message : undefined);
      });
    return () => {
      live = false;
    };
    // The sources key carries identity; layer objects are rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourcesKey, webgl]);

  const ready = layers.length > 0 && layers.every((l) => loaded.has(sourceKey(l.source)));

  // The framing box: every framed layer, placed by its matrix, in source millimetres.
  const framed = ready ? layers.filter((l) => l.frame ?? l.look !== "overlap") : [];
  const box = React.useMemo(() => {
    const b = new THREE.Box3();
    for (const l of framed) {
      const g = loaded.get(sourceKey(l.source))!.geometry;
      if (g.boundingBox) b.union(g.boundingBox.clone().applyMatrix4(toMatrix(l.matrix)));
    }
    return b;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [framed.map((l) => sourceKey(l.source) + JSON.stringify(l.matrix ?? null)).join("|"), loaded]);

  if (webgl !== true || !ready || box.isEmpty()) return null;
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const scale = TARGET / (Math.max(size.x, size.y, size.z) || 1);
  const halfUp = (size.z * scale) / 2;
  const markerSize = Math.max(size.x, size.y, size.z) * 0.022;
  const signature = `${center.toArray().map((v) => v.toFixed(3)).join(",")}:${size.toArray().map((v) => v.toFixed(3)).join(",")}`;

  return (
    <Canvas
      frameloop="demand"
      dpr={[1, 2]}
      resize={{ offsetSize: true }}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      camera={{ fov: 32, near: 0.05, far: 100, position: [2.4, 1.6, 2.6] }}
      style={{ position: "absolute", inset: 0, background: "transparent" }}
    >
      <ambientLight intensity={0.55} />
      <directionalLight position={[6, 9, 5]} intensity={1.5} />
      <directionalLight position={[-6, 3, -5]} intensity={0.55} color="#9fb2c8" />
      <directionalLight position={[0, -4, 3]} intensity={0.25} color="#e8ecf1" />
      <React.Suspense fallback={null}>
        {/* Z-up CAD frame onto the Y-up stage, centred and scaled to the stage size. */}
        <group rotation={[-Math.PI / 2, 0, 0]}>
          <group scale={scale} position={center.clone().multiplyScalar(-scale).toArray()}>
            {layers.map((l) => (
              <Layer key={l.key} layer={l} loaded={loaded.get(sourceKey(l.source))!} />
            ))}
            {markers.map((m) => (
              <mesh key={m.key} position={m.at} renderOrder={12}>
                <octahedronGeometry args={[markerSize]} />
                <meshStandardMaterial color={m.color} emissive={m.color} emissiveIntensity={0.5} depthTest={false} depthWrite={false} />
              </mesh>
            ))}
          </group>
        </group>
        <Environment resolution={128} frames={1}>
          <Lightformer form="rect" intensity={2.6} position={[0, 5, 1]} rotation={[-Math.PI / 2, 0, 0]} scale={[10, 6, 1]} color="#ffffff" />
          <Lightformer form="rect" intensity={1.1} position={[-5, 1.5, 3]} scale={[5, 6, 1]} color="#e6ebf1" />
          <Lightformer form="ring" intensity={1.1} position={[3, 4, 2]} scale={2.4} color="#ffffff" />
        </Environment>
        <ContactShadows position={[0, -halfUp - 0.03, 0]} scale={TARGET * 3.2} far={TARGET * 2} blur={2.6} opacity={0.2} resolution={512} color="#14181f" frames={1} />
      </React.Suspense>
      <OrbitControls
        ref={controls}
        makeDefault
        enableDamping={!reduce}
        dampingFactor={0.07}
        rotateSpeed={0.85}
        enablePan={false}
        enableZoom={false}
        minPolarAngle={0.3}
        maxPolarAngle={Math.PI - 0.3}
        target={[0, 0, 0]}
      />
      <Frame box={box} signature={signature} />
      <Rig turnRef={controller} controls={controls} />
    </Canvas>
  );
}
