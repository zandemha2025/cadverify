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
 */
import * as React from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { ContactShadows, Environment, Html, Lightformer, OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { computeLayeredHighlightVertexColors } from "@/lib/highlight-colors";
import { probeWebGlSupport } from "@/lib/site/webgl";

const TARGET = 2;
const BASE = new THREE.Color("#c3c8cf");

export interface ViewerHighlight {
  faces: number[];
  color: string;
  /** Region centre in source CAD coordinates, when the engine reported one. */
  region: [number, number, number] | null;
  label: string;
  kindClass: string;
}

export interface ViewerApi {
  turnBy: (radians: number) => void;
  turnToHighlight: () => boolean;
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
}: {
  loaded: Loaded;
  highlight: ViewerHighlight | null;
  xray: boolean;
  meshRef: React.RefObject<THREE.Mesh | null>;
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
    <mesh ref={meshRef} geometry={loaded.geometry} scale={loaded.scale} position={loaded.center.clone().multiplyScalar(-loaded.scale)}>
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

/** The pin's position in normalised scene space: the engine's region, else the faces' centroid. */
function pinPoint(loaded: Loaded, h: ViewerHighlight | null): THREE.Vector3 | null {
  if (!h || !h.faces.length) return null;
  let p: THREE.Vector3 | null = null;
  if (h.region) p = new THREE.Vector3(...h.region).applyMatrix4(loaded.transform);
  else {
    const pos = loaded.geometry.getAttribute("position");
    const acc = new THREE.Vector3();
    let n = 0;
    for (const f of h.faces.slice(0, 400)) {
      for (let k = 0; k < 3; k++) {
        const v = f * 3 + k;
        if (v >= pos.count) continue;
        acc.x += pos.getX(v);
        acc.y += pos.getY(v);
        acc.z += pos.getZ(v);
        n++;
      }
    }
    if (!n) return null;
    p = acc.multiplyScalar(1 / n);
  }
  const out = p.sub(loaded.center).multiplyScalar(loaded.scale);
  // Sit just off the surface so the pin isn't hidden by the face it marks.
  return out.length() > 1e-6 ? out.multiplyScalar(1.04) : out;
}

function Rig({
  controllerRef,
  controls,
  pin,
  reduce,
}: {
  controllerRef: ViewerController;
  controls: React.RefObject<OrbitControlsImpl | null>;
  pin: THREE.Vector3 | null;
  reduce: boolean;
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
      if (!c || !pin || pin.length() < 1e-6) return false;
      const dist = camera.position.length();
      const from = camera.position.clone().normalize();
      const to = pin.clone().normalize();
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
    controllerRef.current = { turnBy, turnToHighlight };
    return () => {
      controllerRef.current = null;
    };
  }, [controllerRef, controls, pin, camera, invalidate, reduce]);
  return null;
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
}: {
  url: string | null;
  kind?: "glb" | "stl";
  highlight: ViewerHighlight | null;
  xray: boolean;
  controllerRef: ViewerController;
  onState: (s: ViewerState) => void;
  onPinHidden?: (hidden: boolean) => void;
}) {
  const [loaded, setLoaded] = React.useState<Loaded | null>(null);
  const [webgl, setWebgl] = React.useState<boolean | null>(null);
  const [reduce, setReduce] = React.useState(false);
  const controls = React.useRef<OrbitControlsImpl | null>(null);
  const meshRef = React.useRef<THREE.Mesh | null>(null);
  const [pinHidden, setPinHidden] = React.useState(false);

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
  const pin = React.useMemo(() => (current ? pinPoint(current, highlight) : null), [current, highlight]);

  if (webgl !== true || !current) return null;
  const halfY = ((current.geometry.boundingBox!.max.y - current.geometry.boundingBox!.min.y) * current.scale) / 2;
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
        <Part loaded={current} highlight={highlight} xray={xray} meshRef={meshRef} />
        <Environment resolution={128} frames={1}>
          <Lightformer form="rect" intensity={2.6} position={[0, 5, 1]} rotation={[-Math.PI / 2, 0, 0]} scale={[10, 6, 1]} color="#ffffff" />
          <Lightformer form="rect" intensity={1.1} position={[-5, 1.5, 3]} scale={[5, 6, 1]} color="#e6ebf1" />
          <Lightformer form="ring" intensity={1.1} position={[3, 4, 2]} scale={2.4} color="#ffffff" />
        </Environment>
        <ContactShadows position={[0, -halfY - 0.03, 0]} scale={TARGET * 3.2} far={TARGET * 2} blur={2.6} opacity={0.22} resolution={512} color="#14181f" frames={1} />
        {pin && highlight ? (
          <Html position={pin.toArray()} center zIndexRange={[3, 0]} occlude={[meshRef as React.RefObject<THREE.Object3D>]} onOcclude={(h) => { setPinHidden(h); onPinHidden?.(h); }}>
            <span className={`v4-pin ${highlight.kindClass}${pinHidden ? " hid" : ""}`} aria-hidden="true">
              {highlight.label}
            </span>
          </Html>
        ) : null}
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
      />
      <Frame loaded={current} />
      <Rig controllerRef={controllerRef} controls={controls} pin={pin} reduce={reduce} />
    </Canvas>
  );
}
