"use client";
import { Canvas, useLoader } from "@react-three/fiber";
import { Bounds, OrbitControls } from "@react-three/drei";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import * as THREE from "three";
import { Suspense, useEffect, useMemo, useState } from "react";
import { probeWebGlSupport } from "@/lib/site/webgl";
import type { FitResult, FitUnits } from "@/lib/verify/context-fit";
import { fetchPreviewMesh } from "@/lib/verify/preview-mesh";
import { isQuotaErrorMessage, isLifetimeQuotaErrorMessage } from "@/lib/api-recovery";
import { PreviewBoundary } from "./preview-boundary";

type ShellSource = { url: string; revoke: () => void };
type ShellProps = { url: string; ghost: boolean; transform?: number[][] };
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
export default function ContextFitViewer({ part, context, units, result, hideContext, selectedIssue }: { part: File; context: File; units: FitUnits; result: FitResult | null; hideContext: boolean; selectedIssue: "collision" | "clearance" | null }) {
  const [sources, setSources] = useState<{ part: ShellSource; context: ShellSource; partFile: File; contextFile: File; units: FitUnits } | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [webGlAvailable, setWebGlAvailable] = useState<boolean | null>(null);
  const supported = [part, context].every(file => /\.(stl|obj|3mf|step|stp|iges|igs)$/i.test(file.name));
  useEffect(() => { setWebGlAvailable(probeWebGlSupport()); }, []);
  useEffect(() => {
    setSources(null);
    setPreviewError(null);
    if (!supported || webGlAvailable !== true) return;
    let cancelled = false;
    const owned: ShellSource[] = [];
    const load = async (file: File, sourceUnits: "mm" | "inch"): Promise<ShellSource | null> => {
      const preview = await fetchPreviewMesh(file, { units: sourceUnits });
      const source = preview ? { url: preview.url, revoke: preview.revoke } : null;
      if (cancelled) { source?.revoke(); return null; }
      if (source) owned.push(source);
      return source;
    };
    void Promise.all([load(part, units.part), load(context, units.context)]).then(([a, b]) => {
      if (cancelled) return;
      if (a && b) setSources({ part: a, context: b, partFile: part, contextFile: context, units });
      else setPreviewError("Preview unavailable");
    }).catch((error) => { if (!cancelled) setPreviewError(error instanceof Error ? error.message : "Preview unavailable"); });
    return () => { cancelled = true; owned.forEach(source => source.revoke()); };
  }, [part, context, units, supported, webGlAvailable, retry]);
  if (!supported) return <div className="grid h-full place-items-center px-6 text-center text-xs text-muted-foreground">Choose STL, OBJ, 3MF, STEP or IGES files for the pair preview.</div>;
  if (webGlAvailable !== true) return <div role="status" className="grid h-full place-items-center px-6 text-center text-xs text-muted-foreground">{webGlAvailable === null ? "Preparing the interactive preview…" : "3D preview is unavailable in this browser. Fit measurements remain available below."}</div>;
  if (previewError) return <div role="status" className="grid h-full place-items-center px-6 text-center text-xs text-muted-foreground"><div><p>{isQuotaErrorMessage(previewError) ? previewError : "Could not load the pair preview. Any completed fit measurements remain available below."}</p>{!isLifetimeQuotaErrorMessage(previewError) && <button className="mt-3 min-h-11 rounded border px-3 text-foreground" onClick={() => setRetry(value => value + 1)}>Retry preview</button>}</div></div>;
  if (!sources || sources.partFile !== part || sources.contextFile !== context || sources.units !== units) return <div className="grid h-full place-items-center text-xs text-muted-foreground">Preparing submitted geometry…</div>;
  return <PreviewBoundary key={sources.part.url + sources.context.url} fallback={<div role="status" className="grid h-full place-items-center px-6 text-center text-xs text-muted-foreground">Could not draw this pair. Check the files or select another pair. Fit checks remain available below.</div>}><Canvas dpr={[1, 2]} gl={{ antialias: true, powerPreference: "high-performance" }} camera={{ position: [24, 20, 24], fov: 38 }}><ambientLight intensity={1.2}/><directionalLight position={[10,20,10]} intensity={1.5}/><Suspense fallback={null}><Bounds key={JSON.stringify([result?.seating.transform ?? null, hideContext])} fit clip observe margin={2}><GlbShell url={sources.part.url} ghost={false}/>{!hideContext && <GlbShell url={sources.context.url} ghost transform={result?.seating.transform}/>}{selectedIssue === "collision" && <Region result={result}/>}</Bounds></Suspense><OrbitControls makeDefault enablePan={false}/></Canvas></PreviewBoundary>;
}
