"use client";
import { Canvas, useLoader } from "@react-three/fiber";
import { Bounds, OrbitControls } from "@react-three/drei";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import * as THREE from "three";
import { Suspense, useEffect, useMemo, useState } from "react";
import { probeWebGlSupport } from "@/lib/site/webgl";
import type { FitResult } from "@/lib/verify/context-fit";
import { fetchPreviewMesh } from "@/lib/verify/preview-mesh";
import { PreviewBoundary } from "./preview-boundary";

type ShellSource = { url: string; kind: "stl" | "glb"; revoke: () => void };
type ShellProps = { url: string; ghost: boolean; transform?: number[][] };
function StlShell({ url, ghost, transform }: ShellProps) {
  const raw = useLoader(STLLoader, url);
  const geometry = useMemo(() => raw.clone(), [raw]);
  const matrix = useMemo(() => transform ? new THREE.Matrix4().fromArray(transform.flat()).transpose() : new THREE.Matrix4(), [transform]);
  return <mesh geometry={geometry} matrix={matrix} matrixAutoUpdate={false}><meshStandardMaterial color={ghost ? "#9aa3ad" : "#5f83a5"} transparent={ghost} opacity={ghost ? 0.16 : 1} depthWrite={!ghost} metalness={0.25} roughness={0.65} /></mesh>;
}
function GlbShell({ url, ghost, transform }: ShellProps) {
  const gltf = useLoader(GLTFLoader, url);
  const matrix = useMemo(() => transform ? new THREE.Matrix4().fromArray(transform.flat()).transpose() : new THREE.Matrix4(), [transform]);
  const material = useMemo(() => new THREE.MeshStandardMaterial({ color: ghost ? "#9aa3ad" : "#5f83a5", transparent: ghost, opacity: ghost ? 0.16 : 1, depthWrite: !ghost, metalness: 0.25, roughness: 0.65 }), [ghost]);
  const scene = useMemo(() => {
    const clone = gltf.scene.clone();
    clone.traverse(node => { if (node instanceof THREE.Mesh) node.material = material; });
    return clone;
  }, [gltf.scene, material]);
  useEffect(() => () => material.dispose(), [material]);
  return <group matrix={matrix} matrixAutoUpdate={false}><primitive object={scene} /></group>;
}
function Shell({ source, ...props }: { source: ShellSource; ghost: boolean; transform?: number[][] }) {
  return source.kind === "stl" ? <StlShell url={source.url} {...props} /> : <GlbShell url={source.url} {...props} />;
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
  const [sources, setSources] = useState<{ part: ShellSource; context: ShellSource; partFile: File; contextFile: File } | null>(null);
  const [previewError, setPreviewError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [webGlAvailable, setWebGlAvailable] = useState<boolean | null>(null);
  const supported = [part, context].every(file => /\.(stl|step|stp|iges|igs)$/i.test(file.name));
  useEffect(() => { setWebGlAvailable(probeWebGlSupport()); }, []);
  useEffect(() => {
    setSources(null);
    setPreviewError(false);
    if (!supported || webGlAvailable !== true) return;
    let cancelled = false;
    const owned: ShellSource[] = [];
    const load = async (file: File): Promise<ShellSource | null> => {
      let source: ShellSource | null;
      if (file.name.toLowerCase().endsWith(".stl")) {
        const url = URL.createObjectURL(file);
        source = { url, kind: "stl", revoke: () => URL.revokeObjectURL(url) };
      } else {
        const preview = await fetchPreviewMesh(file);
        source = preview ? { url: preview.url, kind: "glb", revoke: preview.revoke } : null;
      }
      if (cancelled) { source?.revoke(); return null; }
      if (source) owned.push(source);
      return source;
    };
    void Promise.all([load(part), load(context)]).then(([a, b]) => {
      if (cancelled) return;
      if (a && b) setSources({ part: a, context: b, partFile: part, contextFile: context });
      else setPreviewError(true);
    }).catch(() => { if (!cancelled) setPreviewError(true); });
    return () => { cancelled = true; owned.forEach(source => source.revoke()); };
  }, [part, context, supported, webGlAvailable, retry]);
  if (!supported) return <div className="grid h-full place-items-center px-6 text-center text-xs text-muted-foreground">Pair measurement supports this format. Two-shell preview supports STL, STEP and IGES; no substitute geometry is shown.</div>;
  if (webGlAvailable !== true) return <div role="status" className="grid h-full place-items-center px-6 text-center text-xs text-muted-foreground">{webGlAvailable === null ? "Preparing the interactive preview…" : "3D preview is unavailable in this browser. Fit measurements remain available below."}</div>;
  if (previewError) return <div role="status" className="grid h-full place-items-center px-6 text-center text-xs text-muted-foreground"><div><p>Could not load the pair preview. Fit measurements remain available below.</p><button className="mt-3 min-h-11 rounded border px-3 text-foreground" onClick={() => setRetry(value => value + 1)}>Retry preview</button></div></div>;
  if (!sources || sources.partFile !== part || sources.contextFile !== context) return <div className="grid h-full place-items-center text-xs text-muted-foreground">Preparing submitted geometry…</div>;
  return <PreviewBoundary key={sources.part.url + sources.context.url} fallback={<div role="status" className="grid h-full place-items-center px-6 text-center text-xs text-muted-foreground">Could not draw this pair. Check the files or select another pair. Fit checks remain available below.</div>}><Canvas dpr={[1, 2]} gl={{ antialias: true, powerPreference: "high-performance" }} camera={{ position: [24, 20, 24], fov: 38 }}><ambientLight intensity={1.2}/><directionalLight position={[10,20,10]} intensity={1.5}/><Suspense fallback={null}><Bounds key={JSON.stringify([result?.seating.transform ?? null, hideContext])} fit clip observe><Shell source={sources.part} ghost={false}/>{!hideContext && <Shell source={sources.context} ghost transform={result?.seating.transform}/>}{selectedIssue === "collision" && <Region result={result}/>}</Bounds></Suspense><OrbitControls makeDefault enablePan={false}/></Canvas></PreviewBoundary>;
}
