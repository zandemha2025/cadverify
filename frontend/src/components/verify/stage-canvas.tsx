"use client";

/**
 * The part stage canvas — a light studio the part floats in. Client-only (WebGL),
 * dynamically imported with ssr:false by stage.tsx. Reuses three's STLLoader (the
 * same loader the app's CadViewer uses).
 *
 * Honesty: a dropped STL is rendered from its real geometry. A STEP file cannot be
 * parsed in the browser, so the stage falls back to a wireframe box sized to the
 * engine's MEASURED bbox (an honest envelope, not a fake shape) once costing
 * returns it, or a neutral cube before any measurement exists.
 */
import { useEffect, useMemo, useRef, useState, Suspense, type ReactNode } from "react";
import { Canvas, useLoader, useFrame } from "@react-three/fiber";
import { OrbitControls, Center, ContactShadows, Environment, Lightformer } from "@react-three/drei";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

const TARGET = 2;

export interface StageAssemblyContext {
  parentAssembly: string | null;
  program: string | null;
  unitsPerParent: number | null;
  serviceWorldDeclared: boolean;
}

function StlPart({ url, xray, hostile }: { url: string; xray: boolean; hostile: boolean }) {
  const geometry = useLoader(STLLoader, url);
  const norm = useMemo(() => {
    if (!geometry) return { scale: 1, half: 1 };
    geometry.computeVertexNormals();
    geometry.center();
    geometry.computeBoundingBox();
    const size = new THREE.Vector3();
    geometry.boundingBox?.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    const scale = TARGET / maxDim;
    return { scale, half: (size.y * scale) / 2 };
  }, [geometry]);

  return (
    <Center>
      <mesh geometry={geometry} scale={norm.scale}>
        <meshStandardMaterial
          color={hostile ? "#d8c6b6" : "#c6ccd4"}
          metalness={xray ? 0.1 : 0.85}
          roughness={xray ? 0.9 : 0.42}
          envMapIntensity={1.2}
          transparent={xray}
          opacity={xray ? 0.28 : 1}
          wireframe={xray}
          flatShading={false}
        />
      </mesh>
    </Center>
  );
}

function BoxEnvelope({ bbox, xray }: { bbox: [number, number, number] | null; xray: boolean }) {
  // Scale the measured bbox into the normalised TARGET frame; neutral cube when
  // there is no measurement yet.
  const dims = bbox && bbox.every((n) => n > 0) ? bbox : ([1, 1, 1] as [number, number, number]);
  const maxDim = Math.max(...dims) || 1;
  const s = TARGET / maxDim;
  return (
    <Center>
      <mesh scale={[dims[0] * s, dims[1] * s, dims[2] * s]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial
          color="#c6ccd4"
          metalness={0.2}
          roughness={0.7}
          transparent
          opacity={xray ? 0.12 : 0.5}
          wireframe={!bbox || xray}
        />
      </mesh>
    </Center>
  );
}

/** Seat-in-assembly cinematic: the part recedes (the view "pulls back") as it
 *  drops into its home in a larger assembly. Purely visual — it scales the part
 *  group down; it asserts nothing about the part or its cost. */
function SeatGroup({ seat, children }: { seat: boolean; children: ReactNode }) {
  const ref = useRef<THREE.Group>(null);
  useFrame(() => {
    const g = ref.current;
    if (!g) return;
    const target = seat ? 0.62 : 1;
    const s = THREE.MathUtils.lerp(g.scale.x, target, 0.08);
    g.scale.setScalar(Math.abs(s - target) < 0.002 ? target : s);
  });
  return <group ref={ref}>{children}</group>;
}

/** The ghost housing that converges around the part when it is seated — a
 *  translucent cavity (inner walls, BackSide) that fades in. Illustrative context
 *  only: no real neighboring geometry is claimed; it is a schematic visual home,
 *  which is why it stays featureless. */
function GhostHousing({ seat }: { seat: boolean }) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame(() => {
    const m = ref.current;
    if (!m) return;
    const mat = m.material as THREE.MeshStandardMaterial;
    const target = seat ? 0.16 : 0;
    mat.opacity = THREE.MathUtils.lerp(mat.opacity, target, 0.08);
    m.visible = mat.opacity > 0.004;
    const ts = seat ? 1 : 0.82;
    const s = THREE.MathUtils.lerp(m.scale.x, ts, 0.08);
    m.scale.setScalar(s);
  });
  return (
    <mesh ref={ref} visible={false}>
      <boxGeometry args={[2.9, 2.9, 2.9]} />
      <meshStandardMaterial
        color="#7f8a99"
        transparent
        opacity={0}
        metalness={0.05}
        roughness={0.85}
        side={THREE.BackSide}
        depthWrite={false}
      />
    </mesh>
  );
}

/** Declared-context envelope: not exact neighboring CAD, but a USER-declared
 * parent-assembly seat. Exact STEP/PLM assembly geometry can replace this
 * envelope once present; until then it stays visibly schematic and tagged in
 * the DOM readout rather than pretending to be measured CAD. */
function AssemblyEnvelope({
  seat,
  context,
  hostile,
}: {
  seat: boolean;
  context: StageAssemblyContext | null;
  hostile: boolean;
}) {
  const ref = useRef<THREE.Group>(null);
  const hasParent = Boolean(context?.parentAssembly);
  useFrame(() => {
    const g = ref.current;
    if (!g) return;
    const targetOpacity = seat && hasParent ? 1 : 0;
    for (const child of g.children) {
      if (child instanceof THREE.Mesh && child.material instanceof THREE.MeshStandardMaterial) {
        child.material.opacity = THREE.MathUtils.lerp(child.material.opacity, targetOpacity, 0.09);
        child.visible = child.material.opacity > 0.01;
      }
    }
    const targetY = seat ? -0.02 : 0.18;
    g.position.y = THREE.MathUtils.lerp(g.position.y, targetY, 0.08);
    const s = THREE.MathUtils.lerp(g.scale.x, seat ? 1 : 0.92, 0.08);
    g.scale.setScalar(s);
  });

  const materials = useMemo(
    () => ({
      parent: new THREE.MeshStandardMaterial({
        color: hostile ? "#7a675f" : "#65717f",
        metalness: 0.24,
        roughness: 0.72,
        transparent: true,
        opacity: 0,
      }),
      pocket: new THREE.MeshStandardMaterial({
        color: hostile ? "#4f3c35" : "#3d4b58",
        metalness: 0.12,
        roughness: 0.82,
        transparent: true,
        opacity: 0,
      }),
      anchor: new THREE.MeshStandardMaterial({
        color: "#b06a35",
        metalness: 0.45,
        roughness: 0.38,
        transparent: true,
        opacity: 0,
      }),
      rim: new THREE.MeshStandardMaterial({
        color: hostile || context?.serviceWorldDeclared ? "#d49a62" : "#8fa0a6",
        metalness: 0.08,
        roughness: 0.7,
        transparent: true,
        opacity: 0,
        wireframe: true,
      }),
    }),
    [hostile, context?.serviceWorldDeclared]
  );

  if (!hasParent) return <GhostHousing seat={seat} />;

  return (
    <group ref={ref} position={[0, 0.18, -0.16]} scale={0.92}>
      <mesh visible={false} position={[0, 0, -0.1]} material={materials.parent}>
        <boxGeometry args={[2.92, 1.72, 0.1]} />
      </mesh>
      <mesh visible={false} position={[0, 0, -0.025]} material={materials.pocket}>
        <boxGeometry args={[1.62, 0.48, 0.08]} />
      </mesh>
      <mesh visible={false} position={[-0.64, 0, 0.05]} material={materials.anchor}>
        <sphereGeometry args={[0.052, 20, 14]} />
      </mesh>
      <mesh visible={false} position={[0.64, 0, 0.05]} material={materials.anchor}>
        <sphereGeometry args={[0.052, 20, 14]} />
      </mesh>
      <mesh visible={false} position={[0, 0, 0.015]} material={materials.rim}>
        <boxGeometry args={[1.85, 0.62, 0.12]} />
      </mesh>
    </group>
  );
}

function AutoOrbit({ on }: { on: boolean }) {
  return (
    <OrbitControls
      makeDefault
      enableDamping
      dampingFactor={0.1}
      enablePan={false}
      autoRotate={on}
      autoRotateSpeed={0.8}
      minDistance={2.2}
      maxDistance={9}
      target={[0, 0, 0]}
    />
  );
}

export default function StageCanvas({
  fileUrl,
  isStl,
  bbox,
  xray,
  hostile,
  autoOrbit,
  seat,
  assemblyContext,
}: {
  fileUrl: string | null;
  isStl: boolean;
  bbox: [number, number, number] | null;
  xray: boolean;
  hostile: boolean;
  autoOrbit: boolean;
  seat: boolean;
  assemblyContext: StageAssemblyContext | null;
}) {
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  if (!ready) return null;

  return (
    <Canvas
      dpr={[1, 2]}
      gl={{ antialias: true, powerPreference: "high-performance", alpha: true }}
      camera={{ fov: 38, near: 0.05, far: 100, position: [2.1, 1.5, 2.6] }}
      style={{ background: "transparent" }}
    >
      <ambientLight intensity={0.55} />
      <directionalLight position={[6, 9, 5]} intensity={1.5} color="#ffffff" />
      {/* the rim warms when the part's declared world is hostile */}
      <directionalLight
        position={[-6, 3, -5]}
        intensity={hostile ? 1.1 : 0.5}
        color={hostile ? "#e0a06a" : "#9fb2c8"}
      />
      <directionalLight position={[0, -4, 3]} intensity={0.25} color="#e8ecf1" />
      <Suspense fallback={<BoxEnvelope bbox={bbox} xray={xray} />}>
        <SeatGroup seat={seat}>
          {fileUrl && isStl ? (
            <StlPart url={fileUrl} xray={xray} hostile={hostile} />
          ) : (
            <BoxEnvelope bbox={bbox} xray={xray} />
          )}
          <AssemblyEnvelope seat={seat} context={assemblyContext} hostile={hostile} />
        </SeatGroup>
        <Environment resolution={128} frames={1}>
          <Lightformer form="rect" intensity={2.6} position={[0, 5, 1]} rotation={[-Math.PI / 2, 0, 0]} scale={[10, 6, 1]} color="#ffffff" />
          <Lightformer form="rect" intensity={1.1} position={[-5, 1.5, 3]} scale={[5, 6, 1]} color="#e6ebf1" />
          <Lightformer form="ring" intensity={1.1} position={[3, 4, 2]} scale={2.4} color="#ffffff" />
        </Environment>
        <ContactShadows position={[0, -1.05, 0]} scale={7} far={4} blur={2.6} opacity={0.28} resolution={512} color="#17181a" frames={1} />
      </Suspense>
      <AutoOrbit on={autoOrbit} />
    </Canvas>
  );
}
