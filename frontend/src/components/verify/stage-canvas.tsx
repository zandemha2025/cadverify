"use client";

/**
 * The part stage canvas — a light studio the part floats in. Client-only (WebGL),
 * dynamically imported with ssr:false by stage.tsx. Reuses three's STLLoader (the
 * same loader the app's CadViewer uses).
 *
 * Honesty: a dropped STL is rendered from its real geometry. A STEP file cannot be
 * parsed in the browser, so the stage falls back to a wireframe box sized to the
 * engine's MEASURED bbox (an honest envelope, not a fake shape) once costing
 * returns it, or a neutral placeholder before any measurement exists.
 */
import { useEffect, useMemo, useState, Suspense } from "react";
import { Canvas, useLoader } from "@react-three/fiber";
import { OrbitControls, Center, ContactShadows, Environment, Lightformer } from "@react-three/drei";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

const TARGET = 2;

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
}: {
  fileUrl: string | null;
  isStl: boolean;
  bbox: [number, number, number] | null;
  xray: boolean;
  hostile: boolean;
  autoOrbit: boolean;
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
        {fileUrl && isStl ? (
          <StlPart url={fileUrl} xray={xray} hostile={hostile} />
        ) : (
          <BoxEnvelope bbox={bbox} xray={xray} />
        )}
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
