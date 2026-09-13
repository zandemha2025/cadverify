"use client";
import { Canvas, useLoader } from "@react-three/fiber";
import { Center, OrbitControls } from "@react-three/drei";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import * as THREE from "three";
import { Suspense, useEffect, useMemo, useState } from "react";
import { probeWebGlSupport } from "@/lib/site/webgl";
import type { FitResult } from "@/lib/verify/context-fit";

function Shell({ url, ghost, transform }: { url: string; ghost: boolean; transform?: number[][] }) {
  const raw = useLoader(STLLoader, url);
  const geometry = useMemo(() => raw.clone(), [raw]);
  const matrix = useMemo(() => transform ? new THREE.Matrix4().fromArray(transform.flat()).transpose() : new THREE.Matrix4(), [transform]);
  return <mesh geometry={geometry} matrix={matrix} matrixAutoUpdate={false}><meshStandardMaterial color={ghost ? "#9aa3ad" : "#5f83a5"} transparent={ghost} opacity={ghost ? 0.16 : 1} depthWrite={!ghost} metalness={0.25} roughness={0.65} /></mesh>;
}
function LoadedExactRegion({ url }: { url: string }) {
  const gltf = useLoader(GLTFLoader, url);
  const shell = useMemo(() => {
    const clone = gltf.scene.clone();
    clone.traverse((node) => {
      if (!(node instanceof THREE.Mesh)) return;
      node.material = new THREE.MeshStandardMaterial({
        color: "#d64545",
        emissive: "#5b1111",
        emissiveIntensity: 0.45,
        transparent: true,
        opacity: 0.72,
        depthTest: false,
        depthWrite: false,
        side: THREE.DoubleSide,
      });
      node.renderOrder = 10;
    });
    return clone;
  }, [gltf.scene]);
  return <primitive object={shell} />;
}
function ExactRegion({ data }: { data: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    const bytes = Uint8Array.from(atob(data), (char) => char.charCodeAt(0));
    const next = URL.createObjectURL(new Blob([bytes], { type: "model/gltf-binary" }));
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [data]);
  return url ? <LoadedExactRegion url={url} /> : null;
}
function CentroidAnchor({ center }: { center: [number, number, number] }) {
  return <mesh position={center} renderOrder={10}><octahedronGeometry args={[0.5]} /><meshStandardMaterial color="#d64545" emissive="#5b1111" emissiveIntensity={0.6} wireframe depthTest={false} depthWrite={false} /></mesh>;
}
function Region({ result }: { result: FitResult | null }) {
  const region = result?.collision.region;
  if (!result?.collision.intersects || !region) return null;
  const render = region.render_geometry;
  if (render.available && render.data) return <ExactRegion data={render.data} />;
  return <CentroidAnchor center={region.region_center} />;
}
export default function ContextFitViewer({ part, context, result, hideContext, selectedIssue }: { part: File; context: File; result: FitResult | null; hideContext: boolean; selectedIssue: "collision" | "clearance" | null }) {
  const [urls, setUrls] = useState<{ part: string; context: string } | null>(null);
  const [webGlAvailable, setWebGlAvailable] = useState<boolean | null>(null);
  useEffect(() => { setWebGlAvailable(probeWebGlSupport()); }, []);
  useEffect(() => {
    const next = { part: URL.createObjectURL(part), context: URL.createObjectURL(context) };
    setUrls(next);
    return () => { URL.revokeObjectURL(next.part); URL.revokeObjectURL(next.context); };
  }, [part, context]);
  const supported = part.name.toLowerCase().endsWith(".stl") && context.name.toLowerCase().endsWith(".stl");
  if (!supported) return <div className="grid h-full place-items-center px-6 text-center text-xs text-muted-foreground">Pair measurement supports this format. In-browser two-shell preview currently needs STL; no substitute geometry is shown.</div>;
  if (!urls) return <div className="grid h-full place-items-center text-xs text-muted-foreground">Preparing submitted geometry…</div>;
  if (webGlAvailable !== true) return <div role="status" className="grid h-full place-items-center px-6 text-center text-xs text-muted-foreground">{webGlAvailable === null ? "Preparing the interactive preview…" : "3D preview is unavailable in this browser. Your measurements below are complete."}</div>;
  return <Canvas dpr={[1, 2]} gl={{ antialias: true, powerPreference: "high-performance" }} camera={{ position: [24, 20, 24], fov: 38 }}><ambientLight intensity={1.2}/><directionalLight position={[10,20,10]} intensity={1.5}/><Suspense fallback={null}><Center><Shell url={urls.part} ghost={false}/>{!hideContext && <Shell url={urls.context} ghost transform={result?.seating.transform}/>}{selectedIssue === "collision" && <Region result={result}/>}</Center></Suspense><OrbitControls makeDefault enablePan={false}/></Canvas>;
}
