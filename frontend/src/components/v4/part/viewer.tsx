"use client";

/**
 * The part in 3D on the v4 stage. The same real analysis mesh the app's
 * CadViewer renders (the GLB from /validate/preview-mesh?purpose=analysis, or a
 * copy kept in this browser), the same face-highlight colouring
 * (computeLayeredHighlightVertexColors) and framing, on a transparent canvas so
 * the stage shows through. Differences the v4 boards need: drag-to-turn with
 * momentum and no zoom, arrow keys turn it a step, a numbered pin on the flagged
 * faces, "turn to it", and X-ray. The canvas sizes from layout (offsetSize), so
 * the lens dial can scale it with a CSS transform without a re-render.
 *
 * Find and fix adds: words next to the pin (a callout), a pin anchored on a real
 * flagged face when the engine's region centre lies inside the part (a hollow
 * part's centre), the mesh's own open edges drawn in red, numbered location
 * markers, and two viewers that turn together (before and after a fix).
 *
 * Orientation (components/v4/orient) adds: the part turned the way a check will
 * place it, with the placed +Z drawn up and the part resting on the floor
 * (animated between orientations), the faces the check's rule marks in that
 * orientation coloured, and a click on a face to lay the part on it.
 */
import * as React from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { ContactShadows, Environment, Html, Lightformer, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { computeLayeredHighlightVertexColors } from "@/lib/highlight-colors";
import { probeWebGlSupport } from "@/lib/site/webgl";
import { shadeFaces, type Shade } from "../orient/orient";

const TARGET = 2;
const BASE = new THREE.Color("#c3c8cf");

export interface ViewerHighlight {
  faces: number[];
  color: string;
  /** Region centre in source CAD coordinates, when the engine reported one. */
  region: [number, number, number] | null;
  label: string;
  kindClass: string;
  /** Words next to the pin, e.g. "0.5 mm here" / "needs 0.8 mm for 3-axis milling". */
  callout?: { main: string; sub?: string } | null;
  /** Draw the mesh's open (boundary) edges in red and pin the most visible one. */
  edges?: boolean;
  /**
   * The engine sends at most a sample of a large finding's faces. For missing draft
   * the rule is exact (side walls 80–100° from the file's +Z whose draft is under
   * `deg`), so every flagged face is found again on this same mesh, and used only
   * when the count equals the engine's own `count`.
   */
  draftRule?: { deg: number; count: number } | null;
}

/** A numbered place on the part (board K4), drawn dim beside the highlighted one. */
export interface ViewerMarker {
  key: string;
  faces: number[];
  region: [number, number, number] | null;
  label: string;
}

/** Where the highlight's pin is: on view, turned away, inside the part (X-ray shows it), or nowhere. */
export type PinState = "visible" | "hidden" | "inside" | "none";

export interface ViewerApi {
  turnBy: (radians: number) => void;
  turnToHighlight: () => boolean;
  /** Face the same way as another viewer (before and after turn together). */
  setAngles: (azimuth: number, polar: number) => void;
}

/** The part as a check will place it: `rotation` (file → placed, row-major 9) with the placed +Z drawn up. */
export interface ViewerOrient {
  rotation: number[];
  /** Colour the faces the check's rule marks in this orientation (support, or walls without draft). */
  shade: (Shade & { color: string }) | null;
}

/** A ref the viewer fills with its turn controls while it is mounted. */
export type ViewerController = React.RefObject<ViewerApi | null>;

export type ViewerState = "loading" | "ready" | "failed" | "nowebgl";

interface Loaded {
  url: string;
  geometry: THREE.BufferGeometry;
  transform: THREE.Matrix4;
  center: THREE.Vector3;
  scale: number;
}

async function loadGeometry(url: string, kind: "glb" | "stl"): Promise<{ geometry: THREE.BufferGeometry; transform: THREE.Matrix4 }> {
  const transform = new THREE.Matrix4();
  if (kind === "stl") {
    const g = await new STLLoader().loadAsync(url);
    return { geometry: g.index ? g.toNonIndexed() : g, transform };
  }
  const gltf = await new GLTFLoader().loadAsync(url);
  gltf.scene.updateMatrixWorld(true);
  let geometry: THREE.BufferGeometry | null = null;
  gltf.scene.traverse((obj) => {
    const mesh = obj as THREE.Mesh;
    if (!mesh.isMesh) return;
    if (!geometry) {
      transform.copy(mesh.matrixWorld);
      geometry = mesh.geometry.index ? mesh.geometry.toNonIndexed() : mesh.geometry.clone();
      geometry.applyMatrix4(transform);
    }
    mesh.geometry.dispose();
    (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach((m) => m.dispose());
  });
  if (!geometry) throw new Error("Empty preview");
  return { geometry, transform };
}

function Part({
  loaded,
  highlight,
  xray,
  meshRef,
  onPick,
}: {
  loaded: Loaded;
  highlight: ViewerHighlight | null;
  xray: boolean;
  meshRef: React.RefObject<THREE.Mesh | null>;
  /** A click (not a drag) on a face: its normal in the file's coordinates. */
  onPick?: (normal: [number, number, number]) => void;
}) {
  const matRef = React.useRef<THREE.MeshStandardMaterial>(null);
  const { invalidate } = useThree();
  const lit = !!highlight && highlight.faces.length > 0;
  React.useEffect(() => {
    const g = loaded.geometry;
    const pos = g.getAttribute("position");
    if (!pos) return;
    if (!lit) {
      g.deleteAttribute("color");
    } else {
      const colors = computeLayeredHighlightVertexColors(pos.count, [{ faces: highlight!.faces, color: new THREE.Color(highlight!.color), priority: 1 }], BASE);
      g.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    }
    if (matRef.current) matRef.current.needsUpdate = true;
    invalidate();
  }, [loaded, lit, highlight, invalidate]);
  return (
    <mesh
      ref={meshRef}
      geometry={loaded.geometry}
      scale={loaded.scale}
      position={loaded.center.clone().multiplyScalar(-loaded.scale)}
      onClick={
        onPick
          ? (e) => {
              if (e.delta > 4 || !e.face) return;
              e.stopPropagation();
              // Geometry space is the GLB's world space; undo its node transform for the file's own axes.
              const n = e.face.normal.clone().transformDirection(loaded.transform.clone().invert());
              onPick([n.x, n.y, n.z]);
            }
          : undefined
      }
    >
      <meshStandardMaterial
        ref={matRef}
        color={lit ? "#ffffff" : "#c6ccd4"}
        vertexColors={lit}
        metalness={xray ? 0.05 : lit ? 0.3 : 0.75}
        roughness={xray ? 0.9 : lit ? 0.55 : 0.42}
        envMapIntensity={lit ? 0.8 : 1.15}
        transparent={xray}
        opacity={xray ? 0.3 : 1}
        depthWrite={!xray}
        side={xray ? THREE.DoubleSide : THREE.FrontSide}
      />
    </mesh>
  );
}

const VIEW = new THREE.Vector3(0.62, 0.42, 0.66).normalize();

/** Placed (+Z up) to the scene's +Y up. */
const Z_UP = new THREE.Matrix4().set(1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1);

interface Pose {
  q: THREE.Quaternion;
  /** Offset that centres the turned part on the origin. */
  offset: THREE.Vector3;
  /** Half its height on screen (the floor sits just below). */
  halfY: number;
}

/** Where the turned part sits: its rotation in the scene, centred, resting on the floor. */
function poseOf(loaded: Loaded, rotation: number[] | null): Pose {
  const m = new THREE.Matrix4();
  if (rotation && rotation.length === 9) {
    const r = rotation;
    m.copy(Z_UP).multiply(new THREE.Matrix4().set(r[0], r[1], r[2], 0, r[3], r[4], r[5], 0, r[6], r[7], r[8], 0, 0, 0, 0, 1));
  }
  const q = new THREE.Quaternion().setFromRotationMatrix(m);
  const pos = loaded.geometry.getAttribute("position");
  const lo = new THREE.Vector3(Infinity, Infinity, Infinity);
  const hi = new THREE.Vector3(-Infinity, -Infinity, -Infinity);
  const v = new THREE.Vector3();
  if (pos) {
    for (let i = 0; i < pos.count; i++) {
      v.fromBufferAttribute(pos, i).sub(loaded.center).multiplyScalar(loaded.scale).applyQuaternion(q);
      lo.min(v);
      hi.max(v);
    }
  }
  if (!Number.isFinite(lo.x)) return { q, offset: new THREE.Vector3(), halfY: 1 };
  const mid = lo.clone().add(hi).multiplyScalar(0.5);
  return { q, offset: mid.negate(), halfY: (hi.y - lo.y) / 2 };
}

/** Turns its children to the pose, smoothly unless reduced motion is asked for. */
function Turned({ pose, reduce, children }: { pose: Pose; reduce: boolean; children: React.ReactNode }) {
  const ref = React.useRef<THREE.Group>(null);
  const anim = React.useRef<{ q0: THREE.Quaternion; p0: THREE.Vector3; t0: number } | null>(null);
  const { invalidate } = useThree();
  React.useEffect(() => {
    const g = ref.current;
    if (!g) return;
    if (reduce || (g.quaternion.equals(pose.q) && g.position.equals(pose.offset))) {
      g.quaternion.copy(pose.q);
      g.position.copy(pose.offset);
      anim.current = null;
    } else {
      anim.current = { q0: g.quaternion.clone(), p0: g.position.clone(), t0: performance.now() };
    }
    invalidate();
  }, [pose, reduce, invalidate]);
  useFrame(() => {
    const g = ref.current;
    const a = anim.current;
    if (!g || !a) return;
    const t = Math.min(1, (performance.now() - a.t0) / 460);
    const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    g.quaternion.copy(a.q0).slerp(pose.q, e);
    g.position.copy(a.p0).lerp(pose.offset, e);
    if (t >= 1) anim.current = null;
    invalidate();
  });
  return <group ref={ref}>{children}</group>;
}

interface Anchor {
  point: THREE.Vector3;
  /** The way to look from to see it: the face's normal, or out from the centre. */
  dir: THREE.Vector3;
  /** Inside the part (a cavity's centre): only X-ray shows it. */
  inside: boolean;
}

function toScene(loaded: Loaded, v: THREE.Vector3): THREE.Vector3 {
  return v.clone().sub(loaded.center).multiplyScalar(loaded.scale);
}

/**
 * Where to pin a finding, in normalised scene space: the engine's region when it
 * sits out on the part; else the flagged face that faces the default view and
 * lies furthest out (a real face of the finding, not an average that can fall in
 * mid-air); else the open edge most in view; else the region inside the part.
 */
function anchorOf(loaded: Loaded, faces: number[], region: [number, number, number] | null, edges: Float32Array | null): Anchor | null {
  const radius = Math.max(1e-6, (loaded.geometry.boundingSphere?.radius ?? 1) * loaded.scale);
  let inner: THREE.Vector3 | null = null;
  if (region) {
    const p = toScene(loaded, new THREE.Vector3(...region).applyMatrix4(loaded.transform));
    if (p.length() > radius * 0.35) return { point: p.clone().multiplyScalar(1.04), dir: p.clone().normalize(), inside: false };
    inner = p;
  }
  const pos = loaded.geometry.getAttribute("position");
  if (faces.length && pos) {
    const a = new THREE.Vector3();
    const b = new THREE.Vector3();
    const c = new THREE.Vector3();
    let best: { score: number; point: THREE.Vector3; n: THREE.Vector3 } | null = null;
    const step = Math.max(1, Math.floor(faces.length / 4000));
    for (let i = 0; i < faces.length; i += step) {
      const f = faces[i];
      if (f * 3 + 2 >= pos.count) continue;
      a.fromBufferAttribute(pos, f * 3);
      b.fromBufferAttribute(pos, f * 3 + 1);
      c.fromBufferAttribute(pos, f * 3 + 2);
      const n = new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3().subVectors(c, a));
      if (n.lengthSq() < 1e-18) continue;
      n.normalize();
      const centroid = toScene(loaded, a.clone().add(b).add(c).multiplyScalar(1 / 3));
      const score = n.dot(VIEW) + 0.6 * (centroid.length() / radius);
      if (!best || score > best.score) best = { score, point: centroid, n };
    }
    if (best) return { point: best.point.clone().addScaledVector(best.n, 0.03), dir: best.n.clone().add(best.point.clone().normalize()).normalize(), inside: false };
  }
  if (edges && edges.length >= 6) {
    let best: { score: number; p: THREE.Vector3 } | null = null;
    const v = new THREE.Vector3();
    for (let i = 0; i < edges.length; i += 6) {
      v.set((edges[i] + edges[i + 3]) / 2, (edges[i + 1] + edges[i + 4]) / 2, (edges[i + 2] + edges[i + 5]) / 2);
      const score = v.clone().normalize().dot(VIEW) + 0.4 * (v.length() / radius);
      if (!best || score > best.score) best = { score, p: v.clone() };
    }
    if (best) return { point: best.p.clone().multiplyScalar(1.04), dir: best.p.clone().normalize(), inside: false };
  }
  if (inner) return { point: inner, dir: VIEW.clone(), inside: true };
  return null;
}

/** Every side-wall face under `deg` of draft along the file's +Z (the check's own rule, checks/check_draft_angles). */
function draftFaces(loaded: Loaded, deg: number): number[] {
  const pos = loaded.geometry.getAttribute("position");
  if (!pos) return [];
  const up = new THREE.Vector3(0, 0, 1).transformDirection(loaded.transform);
  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const c = new THREE.Vector3();
  const n = new THREE.Vector3();
  const e = new THREE.Vector3();
  const out: number[] = [];
  for (let f = 0; f * 3 + 2 < pos.count; f++) {
    a.fromBufferAttribute(pos, f * 3);
    b.fromBufferAttribute(pos, f * 3 + 1);
    c.fromBufferAttribute(pos, f * 3 + 2);
    n.subVectors(b, a).cross(e.subVectors(c, a));
    const len = n.length();
    if (len < 1e-18) continue;
    const ang = (Math.acos(Math.max(-1, Math.min(1, n.dot(up) / len))) * 180) / Math.PI;
    if (ang > 80 && ang < 100 && Math.abs(90 - ang) < deg) out.push(f);
  }
  return out;
}

/** The mesh's open edges (used by one triangle only), as line-segment positions in scene space. */
function openEdgesOf(loaded: Loaded): Float32Array {
  const pos = loaded.geometry.getAttribute("position");
  if (!pos) return new Float32Array(0);
  const ids = new Map<string, number>();
  const pts: number[] = [];
  const q = 1e4 / Math.max(1e-9, loaded.geometry.boundingSphere?.radius ?? 1);
  const vid = (i: number) => {
    const k = `${Math.round(pos.getX(i) * q)},${Math.round(pos.getY(i) * q)},${Math.round(pos.getZ(i) * q)}`;
    let id = ids.get(k);
    if (id == null) {
      id = ids.size;
      ids.set(k, id);
      pts.push(pos.getX(i), pos.getY(i), pos.getZ(i));
    }
    return id;
  };
  const tri = new Uint32Array(pos.count);
  for (let i = 0; i < pos.count; i++) tri[i] = vid(i);
  const n = ids.size + 1;
  const count = new Map<number, number>();
  for (let t = 0; t + 2 < pos.count; t += 3) {
    for (const [x, y] of [[tri[t], tri[t + 1]], [tri[t + 1], tri[t + 2]], [tri[t + 2], tri[t]]]) {
      const key = x < y ? x * n + y : y * n + x;
      count.set(key, (count.get(key) ?? 0) + 1);
    }
  }
  const out: number[] = [];
  const v = new THREE.Vector3();
  for (const [key, c] of count) {
    if (c !== 1) continue;
    const x = Math.floor(key / n);
    const y = key - x * n;
    for (const id of [x, y]) {
      v.set(pts[id * 3], pts[id * 3 + 1], pts[id * 3 + 2]).sub(loaded.center).multiplyScalar(loaded.scale);
      out.push(v.x, v.y, v.z);
    }
  }
  return new Float32Array(out);
}

function OpenEdges({ positions }: { positions: Float32Array }) {
  const geo = React.useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    return g;
  }, [positions]);
  React.useEffect(() => () => geo.dispose(), [geo]);
  return (
    <lineSegments geometry={geo} renderOrder={2}>
      <lineBasicMaterial color="#D92D20" />
    </lineSegments>
  );
}

/** The pin, with its callout on whichever side has room. */
function Pin({
  anchor,
  label,
  cls,
  callout,
  occluder,
  xray,
  onHidden,
}: {
  anchor: Anchor;
  label: string;
  cls: string;
  callout?: { main: string; sub?: string } | null;
  occluder: React.RefObject<THREE.Mesh | null>;
  xray: boolean;
  onHidden?: (hidden: boolean) => void;
}) {
  const { camera } = useThree();
  const [hidden, setHidden] = React.useState(false);
  const [side, setSide] = React.useState<"r" | "l">("r");
  const sideRef = React.useRef<"r" | "l">("r");
  useFrame(() => {
    if (!callout) return;
    const ndc = anchor.point.clone().project(camera);
    const s = ndc.x > 0.2 ? "l" : "r";
    if (s !== sideRef.current) {
      sideRef.current = s;
      setSide(s);
    }
  });
  // Inside the part, only X-ray shows it; a raycast would always call it hidden.
  const occlude = anchor.inside ? false : xray ? false : [occluder as React.RefObject<THREE.Object3D>];
  const shown = anchor.inside ? xray : !hidden;
  React.useEffect(() => {
    onHidden?.(!shown);
  }, [shown, onHidden]);
  return (
    <Html
      position={anchor.point.toArray()}
      zIndexRange={[3, 0]}
      occlude={occlude}
      onOcclude={(h) => setHidden(h)}
      style={{ pointerEvents: "none" }}
    >
      <span className="v4-anchor" aria-hidden="true">
        <span className={`v4-pin ${cls}${shown ? "" : " hid"}`}>{label}</span>
        {callout ? (
          <span className={`kco ${side}${shown ? "" : " hid"}`}>
            <b>{callout.main}</b>
            {callout.sub ? <small>{callout.sub}</small> : null}
          </span>
        ) : null}
      </span>
    </Html>
  );
}

function Rig({
  controllerRef,
  controls,
  anchor,
  reduce,
  syncing,
}: {
  controllerRef: ViewerController;
  controls: React.RefObject<OrbitControlsImpl | null>;
  anchor: Anchor | null;
  reduce: boolean;
  syncing: React.RefObject<boolean>;
}) {
  const { camera, invalidate } = useThree();
  React.useEffect(() => {
    const turnBy = (rad: number) => {
      const c = controls.current;
      if (!c) return;
      c.setAzimuthalAngle(c.getAzimuthalAngle() + rad);
      c.update();
      invalidate();
    };
    const turnToHighlight = () => {
      const c = controls.current;
      if (!c || !anchor || anchor.dir.length() < 1e-6) return false;
      const dist = camera.position.length();
      const from = camera.position.clone().normalize();
      const to = anchor.dir.clone().normalize();
      to.y = Math.max(-0.75, Math.min(0.85, to.y + 0.25));
      to.normalize();
      if (reduce) {
        camera.position.copy(to.multiplyScalar(dist));
        c.update();
        invalidate();
        return true;
      }
      const q0 = new THREE.Quaternion();
      const q1 = new THREE.Quaternion().setFromUnitVectors(from, to);
      const t0 = performance.now();
      const step = () => {
        const t = Math.min(1, (performance.now() - t0) / 520);
        const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
        const q = q0.clone().slerp(q1, e);
        camera.position.copy(from.clone().applyQuaternion(q).multiplyScalar(dist));
        c.update();
        invalidate();
        if (t < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
      return true;
    };
    const setAngles = (azimuth: number, polar: number) => {
      const c = controls.current;
      if (!c) return;
      syncing.current = true;
      c.setAzimuthalAngle(azimuth);
      c.setPolarAngle(polar);
      c.update();
      syncing.current = false;
      invalidate();
    };
    controllerRef.current = { turnBy, turnToHighlight, setAngles };
    return () => {
      controllerRef.current = null;
    };
  }, [controllerRef, controls, anchor, camera, invalidate, reduce, syncing]);
  return null;
}

/** The floor shadow, baked once the part has settled in its pose. */
function Shadow({ y, delay }: { y: number; delay: number }) {
  const [ready, setReady] = React.useState(delay === 0);
  const { invalidate } = useThree();
  React.useEffect(() => {
    if (ready) return;
    const t = window.setTimeout(() => {
      setReady(true);
      invalidate();
    }, delay);
    return () => window.clearTimeout(t);
  }, [ready, delay, invalidate]);
  if (!ready) return null;
  return <ContactShadows position={[0, y, 0]} scale={TARGET * 3.2} far={TARGET * 2} blur={2.6} opacity={0.22} resolution={512} color="#14181f" frames={1} />;
}

function Frame({ loaded }: { loaded: Loaded }) {
  const { camera, size, invalidate } = useThree();
  React.useEffect(() => {
    const persp = camera as THREE.PerspectiveCamera;
    const radius = (loaded.geometry.boundingSphere?.radius ?? 1) * loaded.scale;
    const aspect = size.width / Math.max(1, size.height);
    const half = Math.atan(Math.tan((persp.fov * Math.PI) / 360) * Math.min(1, aspect));
    const dist = Math.max(3.2, (radius * 1.12) / Math.sin(half));
    camera.position.copy(new THREE.Vector3(0.62, 0.42, 0.66).normalize().multiplyScalar(dist));
    camera.lookAt(0, 0, 0);
    persp.updateProjectionMatrix();
    invalidate();
    // Frame once per mesh; a resize keeps the user's turn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded]);
  return null;
}

export default function PartViewer({
  url,
  kind = "glb",
  highlight,
  xray,
  controllerRef,
  onState,
  onPinHidden,
  onPin,
  markers,
  onTurn,
  onLit,
  orient,
  onFacePick,
}: {
  url: string | null;
  kind?: "glb" | "stl";
  highlight: ViewerHighlight | null;
  xray: boolean;
  controllerRef: ViewerController;
  onState: (s: ViewerState) => void;
  onPinHidden?: (hidden: boolean) => void;
  /** Where the highlight's pin is, whenever that changes. */
  onPin?: (state: PinState) => void;
  /** Other numbered places on the part, drawn dim. */
  markers?: ViewerMarker[];
  /** The user turned it (to turn another viewer the same way). */
  onTurn?: (azimuth: number, polar: number) => void;
  /** How many faces are lit (the sample, or every flagged face when the rule found them all). */
  onLit?: (count: number) => void;
  /** Show the part as a check will place it (components/v4/orient); null keeps the file's own view. */
  orient?: ViewerOrient | null;
  /** In orientation mode, a click on a face: its normal in the file's coordinates. */
  onFacePick?: (normal: [number, number, number]) => void;
}) {
  const [loaded, setLoaded] = React.useState<Loaded | null>(null);
  const [webgl, setWebgl] = React.useState<boolean | null>(null);
  const [reduce, setReduce] = React.useState(false);
  const controls = React.useRef<OrbitControlsImpl | null>(null);
  const meshRef = React.useRef<THREE.Mesh | null>(null);
  const syncing = React.useRef(false);

  React.useEffect(() => {
    const ok = probeWebGlSupport();
    setWebgl(ok);
    if (!ok) onState("nowebgl");
    try {
      setReduce(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch {
      setReduce(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    if (!url) return;
    let cancelled = false;
    let made: THREE.BufferGeometry | null = null;
    onState("loading");
    loadGeometry(url, kind)
      .then(({ geometry, transform }) => {
        made = geometry;
        if (cancelled) return geometry.dispose();
        geometry.computeVertexNormals();
        geometry.computeBoundingBox();
        geometry.computeBoundingSphere();
        const center = geometry.boundingBox!.getCenter(new THREE.Vector3());
        const size = geometry.boundingBox!.getSize(new THREE.Vector3());
        const scale = TARGET / (Math.max(size.x, size.y, size.z) || 1);
        setLoaded({ url, geometry, transform, center, scale });
        onState("ready");
      })
      .catch(() => {
        if (!cancelled) onState("failed");
      });
    return () => {
      cancelled = true;
      made?.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, kind]);

  const current = loaded && loaded.url === url ? loaded : null;
  const rule = highlight?.draftRule ?? null;
  const ruleFaces = React.useMemo(() => {
    if (!current || !rule) return null;
    const f = draftFaces(current, rule.deg);
    return f.length === rule.count ? f : null;
  }, [current, rule]);
  const shade = orient?.shade ?? null;
  const orientRot = orient?.rotation ?? null;
  const shadeKey = orient && shade ? `${orientRot?.join(",")}|${shade.kind}|${shade.deg}|${shade.color}` : null;
  const shaded = React.useMemo<ViewerHighlight | null>(() => {
    if (!current || !orientRot || !shade) return null;
    const pos = current.geometry.getAttribute("position");
    if (!pos) return null;
    return { faces: shadeFaces(pos.array, orientRot, shade), color: shade.color, region: null, label: "", kindClass: "" };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, shadeKey]);
  const lit = React.useMemo<ViewerHighlight | null>(
    () => (orient ? shaded : highlight && ruleFaces ? { ...highlight, faces: ruleFaces } : highlight),
    [orient, shaded, highlight, ruleFaces],
  );
  const poseKey = orientRot ? orientRot.join(",") : "file";
  const pose = React.useMemo(
    () => (current ? poseOf(current, orientRot) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [current, poseKey],
  );
  React.useEffect(() => {
    if (current) onLit?.(lit?.faces.length ?? 0);
  }, [current, lit, onLit]);
  const wantEdges = !!highlight?.edges;
  const edges = React.useMemo(() => (current && wantEdges ? openEdgesOf(current) : null), [current, wantEdges]);
  const anchor = React.useMemo(
    () => (current && lit && !orient ? anchorOf(current, lit.faces, lit.region, edges) : null),
    [current, lit, edges, orient],
  );
  const marks = React.useMemo(
    () => (current && markers?.length ? markers.map((m) => ({ m, a: anchorOf(current, m.faces, m.region, null) })).filter((x): x is { m: ViewerMarker; a: Anchor } => !!x.a) : []),
    [current, markers],
  );
  const pinState = React.useRef<PinState | null>(null);
  const report = React.useCallback(
    (hidden: boolean) => {
      const s: PinState = !anchor ? "none" : anchor.inside && !xray ? "inside" : hidden ? "hidden" : "visible";
      onPinHidden?.(hidden);
      if (s !== pinState.current) {
        pinState.current = s;
        onPin?.(s);
      }
    },
    [anchor, xray, onPin, onPinHidden],
  );
  React.useEffect(() => {
    if (current && !anchor && pinState.current !== "none") {
      pinState.current = "none";
      onPin?.("none");
    }
  }, [current, anchor, onPin]);

  // Orientation: support faces always face down, so look from just under the part's
  // centre while they are coloured; otherwise the usual view from above.
  const lookUnder = !!orient && shade?.kind === "overhang" && (shaded?.faces.length ?? 0) > 0;
  React.useEffect(() => {
    if (!orient) return;
    const to = lookUnder ? 1.75 : 1.137;
    let frame = 0;
    let tries = 0;
    let anim: { from: number; t0: number } | null = null;
    const step = () => {
      const c = controls.current;
      if (!c) {
        // The canvas mounts its controls a frame or two after the part loads.
        if (tries++ < 120) frame = requestAnimationFrame(step);
        return;
      }
      if (!anim) {
        anim = { from: c.getPolarAngle(), t0: performance.now() };
        if (Math.abs(anim.from - to) < 1e-3) return;
      }
      const t = reduce ? 1 : Math.min(1, (performance.now() - anim.t0) / 520);
      const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      c.setPolarAngle(anim.from + (to - anim.from) * e);
      c.update();
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lookUnder, poseKey, !!orient, current]);

  if (webgl !== true || !current || !pose) return null;
  const halfY = pose.halfY;
  return (
    <Canvas
      frameloop="demand"
      dpr={[1, 2]}
      resize={{ offsetSize: true }}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      camera={{ fov: 32, near: 0.05, far: 100, position: [2.4, 1.6, 2.6] }}
      style={{ position: "absolute", inset: 0, background: "transparent" }}
    >
      <ambientLight intensity={0.5} />
      <directionalLight position={[6, 9, 5]} intensity={1.5} />
      <directionalLight position={[-6, 3, -5]} intensity={0.55} color="#9fb2c8" />
      <directionalLight position={[0, -4, 3]} intensity={0.25} color="#e8ecf1" />
      <React.Suspense fallback={null}>
        <Turned pose={pose} reduce={reduce}>
          <Part loaded={current} highlight={lit} xray={xray} meshRef={meshRef} onPick={orient && onFacePick ? onFacePick : undefined} />
          {edges && edges.length ? <OpenEdges positions={edges} /> : null}
          {marks.map(({ m, a }) => (
            <Pin key={m.key} anchor={a} label={m.label} cls="mark" occluder={meshRef} xray={xray} />
          ))}
          {anchor && highlight ? <Pin anchor={anchor} label={highlight.label} cls={highlight.kindClass} callout={highlight.callout} occluder={meshRef} xray={xray} onHidden={report} /> : null}
        </Turned>
        <Environment resolution={128} frames={1}>
          <Lightformer form="rect" intensity={2.6} position={[0, 5, 1]} rotation={[-Math.PI / 2, 0, 0]} scale={[10, 6, 1]} color="#ffffff" />
          <Lightformer form="rect" intensity={1.1} position={[-5, 1.5, 3]} scale={[5, 6, 1]} color="#e6ebf1" />
          <Lightformer form="ring" intensity={1.1} position={[3, 4, 2]} scale={2.4} color="#ffffff" />
        </Environment>
        <Shadow key={poseKey} y={-halfY - 0.03} delay={orient && !reduce ? 480 : 0} />
      </React.Suspense>
      <OrbitControls
        ref={controls}
        makeDefault
        enableDamping
        dampingFactor={0.07}
        rotateSpeed={0.85}
        enablePan={false}
        enableZoom={false}
        minPolarAngle={0.3}
        maxPolarAngle={Math.PI - 0.3}
        target={[0, 0, 0]}
        onChange={() => {
          const c = controls.current;
          if (!syncing.current && c && onTurn) onTurn(c.getAzimuthalAngle(), c.getPolarAngle());
        }}
      />
      <Frame loaded={current} />
      <Rig controllerRef={controllerRef} controls={controls} anchor={anchor} reduce={reduce} syncing={syncing} />
    </Canvas>
  );
}
