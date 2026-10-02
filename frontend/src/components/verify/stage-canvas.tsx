"use client";

/**
 * The part stage canvas — a light studio the part floats in. Client-only (WebGL),
 * dynamically imported with ssr:false by stage.tsx. Reuses three's STLLoader (the
 * same loader the app's CadViewer uses).
 *
 * Honesty: a dropped STL is rendered from its real geometry. A STEP/IGES part
 * cannot be parsed in the browser, so the stage fetches its REAL tessellated
 * shell (a decimated GLB) from our own backend and renders THAT — the part looks
 * like itself. Only when that shell is genuinely unavailable (still resolving, or
 * tessellation failed) does the stage fall back to a wireframe box sized to the
 * engine's MEASURED bbox (an honest envelope, not a fake shape), or a neutral cube
 * before any measurement exists. The GLB is a MESH-LEVEL shell (NOT B-rep / GD&T /
 * PMI) served zero-egress from our backend; it makes the part look right, it
 * asserts no analytic-surface semantics.
 */
import { useEffect, useMemo, useState, Suspense } from "react";
import { Canvas, useLoader } from "@react-three/fiber";
import { Bounds, OrbitControls, Center, ContactShadows, Environment, Lightformer, Html, Line } from "@react-three/drei";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import type { Issue } from "@/lib/api";
import { geometryIssueTitle } from "@/lib/verify/geometry-failure";

const TARGET = 2;

/** The kind of geometry the stage is rendering — drives the honest render-mode
 *  readout in stage.tsx. */
export type StageRenderKind = "stl" | "glb";

/** Normalise a BufferGeometry into the TARGET frame (centred, unit-ish scale) and
 *  render it with the shared studio material — the SAME look for STL and the GLB
 *  shell so the two paths are visually identical (x-ray, verdict tint, shading). */
function PartMesh({
  issue,
  sourceTransform,
  geometry,
  xray,
  hostile,
}: {
  issue: Issue | null;
  sourceTransform?: THREE.Matrix4;
  geometry: THREE.BufferGeometry;
  xray: boolean;
  hostile: boolean;
}) {
  const scale = useMemo(() => {
    geometry.computeBoundingBox();
    const size = new THREE.Vector3();
    geometry.boundingBox?.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    return TARGET / maxDim;
  }, [geometry]);

  return (
    <Center>
      <group scale={scale}>
      <mesh geometry={geometry}>
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
      {issue && <IssueOverlay issue={issue} sourceTransform={sourceTransform} />}
      </group>
    </Center>
  );
}

/** Coordinate overlays cannot drift when the display mesh is decimated. */
function IssueOverlay({ issue, sourceTransform }: { issue: Issue; sourceTransform?: THREE.Matrix4 }) {
  const points = useMemo(() => {
    return (issue.edge_segments ?? []).flat().map((point) => {
      const p = new THREE.Vector3(...point);
      return sourceTransform ? p.applyMatrix4(sourceTransform) : p;
    });
  }, [issue, sourceTransform]);
  const edge = issue.edge_segments?.[0];
  const anchor = edge
    ? new THREE.Vector3(...edge[0]).add(new THREE.Vector3(...edge[1])).multiplyScalar(0.5)
    : issue.region_center ? new THREE.Vector3(...issue.region_center) : null;
  if (anchor && sourceTransform) anchor.applyMatrix4(sourceTransform);
  return <>
    {!!points.length && <Line points={points} segments color="#dc2626" lineWidth={2} renderOrder={10}
      transparent depthTest={false} depthWrite={false} toneMapped={false} />}
    {anchor && <Html position={anchor.toArray()} zIndexRange={[6, 0]}>
      <span aria-hidden="true" style={{ position: "absolute", width: 10, height: 10, left: -5, top: -5, borderRadius: "50%", background: "#dc2626", border: "2px solid #fff" }} />
      <span aria-hidden="true" style={{ position: "absolute", width: 2, height: 20, left: 0, top: -20, background: "#dc2626" }} />
      <div data-testid="geometry-issue-marker" style={{ marginTop: -18, transform: "translate(-50%, -100%)", border: "1px solid #dc2626", borderRadius: 6, background: "#fff", color: "#991b1b", padding: "5px 8px", fontSize: 11, fontWeight: 600, width: 150, pointerEvents: "none", boxShadow: "0 2px 8px #0002" }}>
        {geometryIssueTitle(issue)}
        <div style={{ fontWeight: 400, fontSize: 10 }}>One detected location · rotate to inspect</div>
      </div>
    </Html>}
  </>;
}

function StlPart({ url, xray, hostile, issue }: { url: string; xray: boolean; hostile: boolean; issue: Issue | null }) {
  const raw = useLoader(STLLoader, url);
  const geometry = useMemo(() => {
    const g = raw.clone();
    g.computeVertexNormals();
    return g;
  }, [raw]);
  return <PartMesh geometry={geometry} xray={xray} hostile={hostile} issue={issue} />;
}

/** The REAL tessellated shell for a STEP/IGES part, streamed from our backend as
 *  a decimated GLB and rendered as its true shape (replacing the bbox envelope).
 *  We extract the first mesh's geometry, bake its node transform (trimesh's GLB
 *  export carries a Y-up conversion on the node) so orientation is faithful, then
 *  render it through the same PartMesh as STL. */
function GlbPart({ url, xray, hostile, issue }: { url: string; xray: boolean; hostile: boolean; issue: Issue | null }) {
  const gltf = useLoader(GLTFLoader, url);
  const { geometry, sourceTransform } = useMemo(() => {
    const sourceTransform = new THREE.Matrix4();
    let found: THREE.BufferGeometry | null = null;
    gltf.scene.updateMatrixWorld(true);
    gltf.scene.traverse((obj) => {
      if (found) return;
      const mesh = obj as THREE.Mesh;
      if (mesh.isMesh && mesh.geometry) {
        const g = (mesh.geometry as THREE.BufferGeometry).clone();
        sourceTransform.copy(mesh.matrixWorld);
        g.applyMatrix4(mesh.matrixWorld);
        g.computeVertexNormals();
        found = g;
      }
    });
    return { geometry: found, sourceTransform };
  }, [gltf]);

  if (!geometry) return null;
  return <PartMesh geometry={geometry} xray={xray} hostile={hostile} issue={issue} sourceTransform={sourceTransform} />;
}

/** The part-in-context render: the WHOLE assembly, every part in its baked world
 *  position, streamed as ONE combined GLB (named node per part). The part-of-
 *  interest is rendered with the SAME studio material as the single-part shell
 *  (identical metalness/roughness/x-ray) so it reads as the same instrument; the
 *  rest are ghosted to a neutral context — like a part highlighted inside its
 *  housing, but real geometry. Honest: a MESH-LEVEL shell, no B-rep/PMI.
 *
 *  Node matching: trimesh exports each part as a node named by its stable `id`
 *  (== the GLB node_name). We match the selected id against the mesh's own name
 *  and its parent's, so highlight tracks the real product-tree part. */
function AssemblyParts({
  url,
  selectedId,
  xray,
  hostile,
}: {
  url: string;
  selectedId: string | null;
  xray: boolean;
  hostile: boolean;
}) {
  const gltf = useLoader(GLTFLoader, url);
  const meshes = useMemo(() => {
    const out: { key: string; id: string; geometry: THREE.BufferGeometry }[] = [];
    gltf.scene.updateMatrixWorld(true);
    let i = 0;
    gltf.scene.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (mesh.isMesh && mesh.geometry) {
        const g = (mesh.geometry as THREE.BufferGeometry).clone();
        g.applyMatrix4(mesh.matrixWorld);
        g.computeVertexNormals();
        const id = mesh.name || mesh.parent?.name || "";
        out.push({ key: `${id || "part"}-${i++}`, id, geometry: g });
      }
    });
    return out;
  }, [gltf]);

  // Uniform scale for the WHOLE assembly so it fits the same frame the single
  // shell uses — parts keep their real relative positions.
  const scale = useMemo(() => {
    const bounds = new THREE.Box3();
    for (const m of meshes) {
      m.geometry.computeBoundingBox();
      if (m.geometry.boundingBox) bounds.union(m.geometry.boundingBox);
    }
    const size = new THREE.Vector3();
    bounds.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    return TARGET / maxDim;
  }, [meshes]);

  if (meshes.length === 0) return null;
  // When nothing is explicitly selected, everything renders as the highlighted
  // material (no dimming) so an assembly never looks broken.
  const anySelected = selectedId != null && meshes.some((m) => m.id === selectedId);

  return (
    <Center>
      <group scale={scale}>
        {meshes.map((m) => {
          const highlighted = !anySelected || m.id === selectedId;
          return (
            <mesh key={m.key} geometry={m.geometry}>
              {highlighted ? (
                <meshStandardMaterial
                  color={hostile ? "#d8c6b6" : "#c6ccd4"}
                  metalness={xray ? 0.1 : 0.85}
                  roughness={xray ? 0.9 : 0.42}
                  envMapIntensity={1.2}
                  transparent={xray}
                  opacity={xray ? 0.32 : 1}
                  wireframe={xray}
                  emissive={"#2b6da3"}
                  emissiveIntensity={xray ? 0.05 : 0.14}
                />
              ) : (
                // Context parts: ghosted neutral shell, same family of material so
                // it reads as the SAME render — just receded behind the part.
                <meshStandardMaterial
                  color="#aeb6c0"
                  metalness={0.15}
                  roughness={0.85}
                  transparent
                  opacity={xray ? 0.06 : 0.16}
                  depthWrite={false}
                />
              )}
            </mesh>
          );
        })}
      </group>
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
      target={[0, 0, 0]}
    />
  );
}

export default function StageCanvas({
  issue,
  renderUrl,
  renderKind,
  assemblyUrl,
  assemblySelectedId,
  bbox,
  xray,
  hostile,
  autoOrbit,
}: {
  issue: Issue | null;
  /** object URL for the geometry to render (STL blob or the backend GLB shell),
   *  or null → the honest bbox envelope fallback. */
  renderUrl: string | null;
  /** which loader to use for renderUrl; null → fall back to the box. */
  renderKind: StageRenderKind | null;
  /** object URL for the combined multi-part assembly GLB. When present, the
   *  stage renders the WHOLE assembly in context (overrides renderUrl). */
  assemblyUrl: string | null;
  /** id of the part-of-interest highlighted inside the assembly. */
  assemblySelectedId: string | null;
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
      <Suspense fallback={<Bounds fit clip observe><BoxEnvelope bbox={bbox} xray={xray} /></Bounds>}>
        <Bounds key={JSON.stringify(assemblyUrl ?? renderUrl ?? bbox)} fit clip observe>
          {assemblyUrl ? (
            <AssemblyParts
              url={assemblyUrl}
              selectedId={assemblySelectedId}
              xray={xray}
              hostile={hostile}
            />
          ) : renderUrl && renderKind === "stl" ? (
            <StlPart url={renderUrl} xray={xray} hostile={hostile} issue={issue} />
          ) : renderUrl && renderKind === "glb" ? (
            <GlbPart url={renderUrl} xray={xray} hostile={hostile} issue={issue} />
          ) : (
            <BoxEnvelope bbox={bbox} xray={xray} />
          )}
        </Bounds>
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
