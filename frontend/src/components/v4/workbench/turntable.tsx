"use client";

/**
 * The part on a turntable (boards F5, F6): drag with momentum, or the arrow
 * keys, to turn it; no zoom. Renders the part's REAL tessellated shell from the
 * analysis-aligned preview mesh (POST /validate/preview-mesh?purpose=analysis,
 * the same path as components/ui/cad-viewer.tsx), so a finding's face indices
 * light the faces the analyzer flagged. When the preview's face fingerprint
 * doesn't match the analysis, faces aren't painted and the card says so.
 *
 * The pin marks one real flagged face (or the finding's region centre), tracked
 * every frame; it hides when the part turns it away.
 */
import * as React from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Environment, Lightformer } from "@react-three/drei";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { fetchPreviewMesh } from "@/lib/verify/preview-mesh";
import { computeHighlightVertexColors } from "@/lib/highlight-colors";
import { probeWebGlSupport } from "@/lib/site/webgl";
import { perspectiveFramingDistance } from "@/lib/camera-framing";
import { cx } from "../ui";

type Loaded = { geometry: THREE.BufferGeometry; faceHash: string | null; aligned: boolean; transform: THREE.Matrix4 };

// Parsed shells, per File and units. The File's lifetime bounds the memory.
const parsed = new WeakMap<File, Map<string, Promise<Loaded>>>();

function loadShell(file: File, units: "mm" | "inch"): Promise<Loaded> {
  let byUnits = parsed.get(file);
  if (!byUnits) {
    byUnits = new Map();
    parsed.set(file, byUnits);
  }
  const hit = byUnits.get(units);
  if (hit) return hit;
  const p = (async () => {
    const preview = await fetchPreviewMesh(file, { forAnalysis: true, units });
    if (!preview) throw new Error("Preview unavailable");
    try {
      const gltf = await new GLTFLoader().loadAsync(preview.url);
      gltf.scene.updateMatrixWorld(true);
      let geometry: THREE.BufferGeometry | null = null;
      const transform = new THREE.Matrix4();
      gltf.scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (!mesh.isMesh) return;
        if (!geometry) {
          transform.copy(mesh.matrixWorld);
          geometry = mesh.geometry.index ? mesh.geometry.toNonIndexed() : mesh.geometry.clone();
          geometry.applyMatrix4(transform);
        }
        mesh.geometry.dispose();
      });
      const g = geometry as THREE.BufferGeometry | null;
      if (!g?.getAttribute("position")?.count) throw new Error("Empty preview");
      g.computeVertexNormals();
      g.computeBoundingBox();
      return { geometry: g, faceHash: preview.faceSpace === "analysis" ? preview.faceHash : null, aligned: preview.faceSpace === "analysis", transform };
    } finally {
      preview.revoke();
    }
  })();
  byUnits.set(units, p);
  p.catch(() => byUnits!.delete(units));
  return p;
}

export interface PinSpec {
  faces: number[];
  region: [number, number, number] | null;
  kind: string;
}

const KIND_COLOR: Record<string, string> = { thin: "#E5482A", support: "#2E6BE6", reach: "#B97F0C", draft: "#7A4FD6", none: "#5F656E" };
const BASE = new THREE.Color("#D3D7DD");

/** A real point on the flagged faces: the face whose centre is nearest the faces' mean centre. */
function anchorPoint(geometry: THREE.BufferGeometry, faces: number[]): THREE.Vector3 | null {
  const pos = geometry.getAttribute("position");
  if (!pos || !faces.length) return null;
  const n = pos.count / 3;
  const cs: THREE.Vector3[] = [];
  const mean = new THREE.Vector3();
  for (const f of faces) {
    if (f < 0 || f >= n) continue;
    const c = new THREE.Vector3(
      (pos.getX(3 * f) + pos.getX(3 * f + 1) + pos.getX(3 * f + 2)) / 3,
      (pos.getY(3 * f) + pos.getY(3 * f + 1) + pos.getY(3 * f + 2)) / 3,
      (pos.getZ(3 * f) + pos.getZ(3 * f + 1) + pos.getZ(3 * f + 2)) / 3,
    );
    cs.push(c);
    mean.add(c);
  }
  if (!cs.length) return null;
  mean.divideScalar(cs.length);
  return cs.reduce((best, c) => (c.distanceToSquared(mean) < best.distanceToSquared(mean) ? c : best), cs[0]);
}

/** Turn state shared by the pointer handlers and the render loop (mutable, outside React). */
class Spin {
  yaw = -0.6;
  v = 0;
  dragging = false;
  grab() {
    this.dragging = true;
    this.v = 0;
  }
  drag(dyaw: number, dt: number) {
    this.yaw += dyaw;
    this.v = (dyaw / Math.max(1, dt)) * 16;
  }
  release(reduce: boolean) {
    this.dragging = false;
    this.v = reduce ? 0 : Math.max(-0.12, Math.min(0.12, this.v));
  }
  step(by: number | null) {
    this.v = 0;
    this.yaw = by == null ? -0.6 : this.yaw + by;
  }
  /** Advance momentum one frame; true while still turning. */
  tick(): boolean {
    if (this.dragging || Math.abs(this.v) <= 0.0004) return false;
    this.yaw += this.v;
    this.v *= 0.93;
    return true;
  }
  degrees(): number {
    return Math.round(((((this.yaw * 180) / Math.PI) % 360) + 360) % 360);
  }
}

function Model({
  loaded,
  spin,
  highlight,
  pin,
  onPin,
  setInvalidate,
}: {
  loaded: Loaded;
  spin: Spin;
  highlight: { faces: number[]; color: string } | null;
  pin: PinSpec | null;
  onPin: (p: { x: number; y: number; hidden: boolean } | null) => void;
  setInvalidate: (fn: () => void) => void;
}) {
  const { geometry, transform } = loaded;
  const group = React.useRef<THREE.Group>(null);
  const mesh = React.useRef<THREE.Mesh>(null);
  const material = React.useRef<THREE.MeshStandardMaterial>(null);
  const { camera, size, invalidate } = useThree();
  React.useEffect(() => setInvalidate(invalidate), [invalidate, setInvalidate]);

  const norm = React.useMemo(() => {
    const box = geometry.boundingBox ?? new THREE.Box3().setFromBufferAttribute(geometry.getAttribute("position") as THREE.BufferAttribute);
    const center = box.getCenter(new THREE.Vector3());
    const dim = box.getSize(new THREE.Vector3());
    const scale = 2 / (Math.max(dim.x, dim.y, dim.z) || 1);
    return { center, scale, radius: (dim.length() * scale) / 2 };
  }, [geometry]);

  const lit = !!highlight && highlight.faces.length > 0;
  React.useEffect(() => {
    const pos = geometry.getAttribute("position");
    if (!lit) {
      geometry.deleteAttribute("color");
    } else {
      const c = new THREE.Color(highlight!.color);
      geometry.setAttribute("color", new THREE.BufferAttribute(computeHighlightVertexColors(pos.count, highlight!.faces, BASE, c), 3));
    }
    if (material.current) material.current.needsUpdate = true;
    invalidate();
  }, [geometry, lit, highlight, invalidate]);

  React.useEffect(() => {
    const dist = 2.2;
    const dir = new THREE.Vector3(0, 0.62, 1).normalize();
    const cam = camera as THREE.PerspectiveCamera;
    const d = perspectiveFramingDistance(norm.radius, size.width / Math.max(1, size.height), cam.fov, dist * 1.15);
    camera.position.copy(dir.multiplyScalar(d));
    // R3F camera framing is an imperative three.js boundary.
    // eslint-disable-next-line react-hooks/immutability
    camera.near = 0.05;
    camera.far = 100;
    cam.updateProjectionMatrix();
    camera.lookAt(0, 0, 0);
    invalidate();
  }, [camera, norm.radius, size.width, size.height, invalidate]);

  const anchor = React.useMemo(() => {
    if (!pin) return null;
    if (pin.region) return new THREE.Vector3(...pin.region).applyMatrix4(transform);
    return anchorPoint(geometry, pin.faces);
  }, [pin, geometry, transform]);

  const ray = React.useMemo(() => new THREE.Raycaster(), []);
  const last = React.useRef("");
  useFrame(() => {
    if (spin.tick()) invalidate();
    if (group.current) group.current.rotation.y = spin.yaw;
    if (!anchor || !group.current || !mesh.current) {
      if (last.current !== "none") {
        last.current = "none";
        onPin(null);
      }
      return;
    }
    group.current.updateMatrixWorld(true);
    const local = anchor.clone().sub(norm.center).multiplyScalar(norm.scale);
    const world = group.current.localToWorld(local);
    const toPoint = world.clone().sub(camera.position);
    const dist = toPoint.length();
    ray.set(camera.position, toPoint.normalize());
    const hit = ray.intersectObject(mesh.current, false)[0];
    const hidden = !!hit && hit.distance < dist - 0.03;
    const p = world.clone().project(camera);
    const next = { x: (p.x * 0.5 + 0.5) * size.width, y: (-p.y * 0.5 + 0.5) * size.height, hidden };
    const sig = `${Math.round(next.x)},${Math.round(next.y)},${hidden}`;
    if (sig !== last.current) {
      last.current = sig;
      onPin(next);
    }
  });

  return (
    <group ref={group}>
      <mesh ref={mesh} geometry={geometry} scale={norm.scale} position={norm.center.clone().multiplyScalar(-norm.scale)}>
        <meshStandardMaterial
          ref={material}
          color={lit ? "#ffffff" : "#DCE0E5"}
          vertexColors={lit}
          metalness={lit ? 0.12 : 0.45}
          roughness={lit ? 0.6 : 0.38}
          envMapIntensity={lit ? 0.8 : 1.1}
        />
      </mesh>
    </group>
  );
}

function Rig() {
  return (
    <Environment resolution={128} frames={1}>
      <Lightformer form="rect" intensity={2.6} position={[0, 5, 1]} rotation={[-Math.PI / 2, 0, 0]} scale={[10, 6, 1]} color="#ffffff" />
      <Lightformer form="rect" intensity={1.2} position={[-5, 1.5, 3]} scale={[5, 6, 1]} color="#e9edf2" />
      <Lightformer form="rect" intensity={0.9} position={[5, 2.5, -4]} scale={[6, 6, 1]} color="#dde3ea" />
    </Environment>
  );
}

export function Turntable({
  file,
  filename,
  units,
  analysisMeshHash,
  highlight,
  pin,
  label,
  onChooseFile,
  className,
}: {
  file: File | null;
  filename: string | null;
  units: "mm" | "inch";
  /** the DFM result's face fingerprint; faces are painted only when the preview matches it */
  analysisMeshHash?: string | null;
  highlight?: { faces: number[]; kind: string } | null;
  pin?: PinSpec | null;
  label: string;
  onChooseFile?: () => void;
  className?: string;
}) {
  const [webgl, setWebgl] = React.useState<boolean | null>(null);
  const [state, setState] = React.useState<{ file: File; units: string; loaded: Loaded | null; error: string | null } | null>(null);
  const [retry, setRetry] = React.useState(0);
  const [drag, setDrag] = React.useState(false);
  const [touched, setTouched] = React.useState(false);
  const [deg, setDeg] = React.useState(0);
  const [pinAt, setPinAt] = React.useState<{ x: number; y: number; hidden: boolean } | null>(null);
  const [spin] = React.useState(() => new Spin());
  const inval = React.useRef<() => void>(() => {});
  const setInvalidate = React.useCallback((fn: () => void) => {
    inval.current = fn;
  }, []);
  const ptr = React.useRef<{ x: number; t: number; id: number } | null>(null);

  React.useEffect(() => setWebgl(probeWebGlSupport()), []);
  React.useEffect(() => {
    if (!file) return;
    let live = true;
    setState({ file, units, loaded: null, error: null });
    loadShell(file, units).then(
      (loaded) => live && setState({ file, units, loaded, error: null }),
      (e) => live && setState({ file, units, loaded: null, error: e instanceof Error ? e.message : "Preview unavailable" }),
    );
    return () => {
      live = false;
    };
  }, [file, units, retry]);

  const current = state && state.file === file && state.units === units ? state : null;
  const loaded = current?.loaded ?? null;
  const aligned = !!loaded && loaded.aligned && !!analysisMeshHash && loaded.faceHash === analysisMeshHash;
  const color = highlight ? KIND_COLOR[highlight.kind] ?? KIND_COLOR.none : KIND_COLOR.none;
  const hl = React.useMemo(() => (aligned && highlight && highlight.faces.length ? { faces: highlight.faces, color } : null), [aligned, highlight, color]);
  const pinSpec = aligned ? pin ?? null : null;
  const wantsFaces = !!highlight?.faces.length || !!pin;
  const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  const syncDeg = () => setDeg(spin.degrees());

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    ptr.current = { x: e.clientX, t: performance.now(), id: e.pointerId };
    spin.grab();
    setDrag(true);
    setTouched(true);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const p = ptr.current;
    if (!p || p.id !== e.pointerId) return;
    const now = performance.now();
    const dx = e.clientX - p.x;
    spin.drag(dx * 0.012, now - p.t);
    ptr.current = { x: e.clientX, t: now, id: p.id };
    inval.current();
  };
  const onPointerUp = () => {
    ptr.current = null;
    spin.release(!!reduce);
    setDrag(false);
    syncDeg();
    inval.current();
  };
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step && e.key !== "Home") return;
    e.preventDefault();
    spin.step(e.key === "Home" ? null : (step * Math.PI) / 18);
    setTouched(true);
    syncDeg();
    inval.current();
  };

  let body: React.ReactNode;
  if (!file) {
    body = (
      <div className="vmsg">
        <b>3D needs the file</b>
        <span>{filename ? `${filename} isn’t kept in this browser.` : "The CAD file isn’t kept in this browser."} Choose it again to turn the part and see findings on it.</span>
        {onChooseFile ? (
          <button className="btn sm ink" type="button" onClick={onChooseFile}>
            Choose file
          </button>
        ) : null}
      </div>
    );
  } else if (current?.error) {
    body = (
      <div className="vmsg" role="alert">
        <b>Couldn’t load the 3D preview</b>
        <span>{/quota|allowance|checks/i.test(current.error) ? current.error : "Results are unaffected."}</span>
        <button className="btn sm" type="button" onClick={() => setRetry((n) => n + 1)}>
          Retry preview
        </button>
      </div>
    );
  } else if (webgl === false) {
    body = (
      <div className="vmsg" role="status">
        <b>3D isn’t available in this browser</b>
        <span>The measurements and findings are all here without it.</span>
      </div>
    );
  } else if (!loaded || webgl === null) {
    body = (
      <div className="vmsg" role="status">
        <span className="bar2" aria-hidden="true">
          <i />
        </span>
        <span>Loading the 3D preview</span>
      </div>
    );
  }

  if (body) {
    return (
      <div className={cx("wb-obj", className)} role="group" aria-label={label}>
        {body}
      </div>
    );
  }

  return (
    <div
      className={cx("wb-obj", drag && "drag", className)}
      role="slider"
      tabIndex={0}
      aria-label={`${label} Drag, or use the arrow keys, to turn it.`}
      aria-valuemin={0}
      aria-valuemax={359}
      aria-valuenow={deg}
      aria-valuetext={`Turned ${deg}°`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDown={onKeyDown}
    >
      <span className="shade" aria-hidden="true" />
      <div className="cv on" aria-hidden="true">
        <Canvas frameloop="demand" dpr={[1, 2]} gl={{ antialias: true, alpha: true }} camera={{ fov: 30, near: 0.05, far: 100, position: [0, 1.4, 2.4] }}>
          <ambientLight intensity={0.75} />
          <directionalLight position={[5, 8, 6]} intensity={1.3} />
          <directionalLight position={[-6, 3, -4]} intensity={0.45} />
          <React.Suspense fallback={null}>
            <Model loaded={loaded!} spin={spin} highlight={hl} pin={pinSpec} onPin={setPinAt} setInvalidate={setInvalidate} />
            <Rig />
          </React.Suspense>
        </Canvas>
      </div>
      {pinSpec && pinAt ? (
        <>
          <span className={cx("pin", `k-${pin?.kind ?? "none"}`, pinAt.hidden && "hid")} style={{ left: pinAt.x, top: pinAt.y }} aria-hidden="true">
            !
          </span>
          {pinAt.hidden ? <span className="far" role="status">On the far side. Drag to turn it.</span> : null}
        </>
      ) : null}
      {wantsFaces && loaded && !aligned ? (
        <span className="far" role="status" style={{ background: "var(--warn-bg)", color: "var(--warn)" }}>
          Exact faces can’t be shown on this preview
        </span>
      ) : null}
      <span className={cx("hint", touched && "gone")} aria-hidden="true">
        Drag to turn it
      </span>
    </div>
  );
}
