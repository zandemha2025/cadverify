"use client";

import { useRef, useEffect, useState, useMemo, Suspense, useCallback } from "react";
import { Canvas, useLoader, useThree } from "@react-three/fiber";
import {
  OrbitControls,
  Environment,
  Center,
  ContactShadows,
  Lightformer,
} from "@react-three/drei";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { cn } from "@/lib/utils";
import { STAGE_UI } from "@/lib/stage-flag";
import { computeHighlightVertexColors } from "@/lib/highlight-colors";
import { probeWebGlSupport } from "@/lib/site/webgl";

/* Non-highlighted faces keep a machined tint when vertex-colouring is on (i.e.
   during DFM inspection) so the flagged faces still pop against them. Stage
   register: a warm-neutral machined grey under the stage-lit rig; legacy: the
   cool Datum-blue graphite tint. Gated so flag-off is byte-identical. */
const BASE_COLOR = new THREE.Color(STAGE_UI ? "#c2bfb8" : "#8ea6c4");

/* Every part is normalised so its largest dimension spans TARGET world units.
   This makes the studio lighting, contact shadow, and hero framing look
   identical whether the STL is a 6 mm insert or a 600 mm housing. */
const TARGET = 2;

function STLModel({
  url,
  highlightFaces,
  // Default face-highlight = the ERROR tone: stage crimson vs legacy coral. The
  // caller (PartWorkspace) passes an explicit severity hex; this is the fallback.
  highlightColor = STAGE_UI ? "#e05252" : "#f8716e",
  ghostUnhighlighted,
  onFaceClick,
  distanceScale = 1.6,
  onHalfHeight,
}: {
  url: string;
  highlightFaces?: number[];
  highlightColor?: string;
  ghostUnhighlighted?: boolean;
  onFaceClick?: (faceIndex: number) => void;
  /** camera pull-back as a multiple of the (normalised) part size. Lower =
   *  the part fills more of the frame (the Living Instrument wants it big). */
  distanceScale?: number;
  /** reports the normalised half-height so the contact shadow seats at the base. */
  onHalfHeight?: (h: number) => void;
}) {
  const geometry = useLoader(STLLoader, url);
  const meshRef = useRef<THREE.Mesh>(null);
  const materialRef = useRef<THREE.MeshStandardMaterial>(null);
  const hasHighlights = !!highlightFaces && highlightFaces.length > 0;
  const highlight = useMemo(() => new THREE.Color(highlightColor), [highlightColor]);

  // Normalise once: centre at origin, then derive a uniform scale to TARGET.
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

  useEffect(() => {
    onHalfHeight?.(norm.half);
  }, [norm.half, onHalfHeight]);

  // Per-face highlight via vertex colors (STL geometry is non-indexed:
  // face i -> vertices 3i, 3i+1, 3i+2).
  useEffect(() => {
    if (!geometry) return;
    const pos = geometry.getAttribute("position");
    if (!pos) return;
    const material = materialRef.current;
    if (!hasHighlights) {
      geometry.deleteAttribute("color");
      // R3F just flipped `material.vertexColors` back to false via a bare
      // assignment; force the shader to recompile so it stops sampling the
      // colour channel we just deleted.
      if (material) material.needsUpdate = true;
      return;
    }
    const colors = computeHighlightVertexColors(
      pos.count,
      highlightFaces!,
      BASE_COLOR,
      highlight
    );
    const colorAttribute = new THREE.BufferAttribute(colors, 3);
    colorAttribute.needsUpdate = true;
    geometry.setAttribute("color", colorAttribute);
    // ROOT-CAUSE FIX (locate highlight never rendered): @react-three/fiber's
    // applyProps sets `material.vertexColors = true` with a plain assignment and
    // never flips `material.needsUpdate`, so three.js keeps the cached program
    // that was compiled WITHOUT the `USE_COLOR` define and silently ignores this
    // colour attribute — the flagged faces stay the base tone. Flipping
    // needsUpdate forces the program rebuild so the vertex colours actually paint.
    if (material) material.needsUpdate = true;
  }, [geometry, hasHighlights, highlightFaces, highlight]);

  // Hero camera frame — a well-composed 3/4 with a gentle downward tilt, pulled
  // in so the part commands the canvas. Normalised units keep it consistent.
  const { camera } = useThree();
  useEffect(() => {
    const dist = TARGET * distanceScale;
    camera.position.set(dist * 0.6, dist * 0.44, dist * 0.68);
    // R3F camera framing is an imperative three.js boundary; React's compiler
    // cannot infer that mutating the camera instance here is intentional.
    // eslint-disable-next-line react-hooks/immutability
    camera.near = 0.05;
    camera.far = 100;
    if ((camera as THREE.PerspectiveCamera).isPerspectiveCamera) {
      camera.updateProjectionMatrix();
    }
    camera.lookAt(0, TARGET * 0.02, 0);
  }, [camera, distanceScale, norm.scale]);

  const ghosted = hasHighlights && ghostUnhighlighted;

  return (
    <Center>
      <mesh
        ref={meshRef}
        geometry={geometry}
        scale={norm.scale}
        onPointerDown={(e) => {
          if (onFaceClick && e.faceIndex != null) {
            e.stopPropagation();
            onFaceClick(e.faceIndex);
          }
        }}
      >
        {/* Idle: a premium machined-aluminium finish — high metalness picks up
            the studio environment as soft specular sweeps + a Datum-cool rim.
            Inspecting (highlights on): the material relaxes to a matte technical
            read so the flagged faces stay unmistakable. */}
        <meshStandardMaterial
          ref={materialRef}
          color={hasHighlights ? "#ffffff" : "#bcc6d2"}
          vertexColors={hasHighlights}
          metalness={hasHighlights ? 0.35 : 0.9}
          roughness={hasHighlights ? 0.5 : 0.42}
          envMapIntensity={hasHighlights ? 0.7 : 1.35}
          transparent={ghosted}
          opacity={ghosted ? 0.9 : 1}
          flatShading={false}
        />
      </mesh>
    </Center>
  );
}

/** A compact studio rig baked into the environment map: a big soft key overhead,
 *  a tinted fill, and a rim behind — the reflections that make the machined part
 *  read as a rendered product shot. Stage register: a warm-white key over a
 *  neutral fill and a quiet steel rim (one warm light source, Apple-cinematic).
 *  Legacy: the Datum-cool blueprint rig. Gated so flag-off is byte-identical. */
function StudioRig() {
  if (STAGE_UI) {
    return (
      <Environment resolution={256} frames={1}>
        {/* broad warm-white key from above — the single stage light */}
        <Lightformer
          form="rect"
          intensity={3.3}
          position={[0, 5, 1]}
          rotation={[-Math.PI / 2, 0, 0]}
          scale={[10, 6, 1]}
          color="#fbf6ee"
        />
        {/* neutral fill from the front-left, warm-side of grey */}
        <Lightformer
          form="rect"
          intensity={1.4}
          position={[-5, 1.5, 3]}
          scale={[5, 6, 1]}
          color="#d8d4cc"
        />
        {/* quiet steel rim from behind-right — separates part from the stage */}
        <Lightformer
          form="rect"
          intensity={1.3}
          position={[5, 2.5, -4]}
          scale={[6, 6, 1]}
          color="#8fa0a6"
        />
        {/* small warm ring for a crisp specular catch */}
        <Lightformer
          form="ring"
          intensity={1.4}
          position={[3, 4, 2]}
          scale={2.5}
          color="#fff4e6"
        />
      </Environment>
    );
  }
  return (
    <Environment resolution={256} frames={1}>
      {/* broad soft key from above */}
      <Lightformer
        form="rect"
        intensity={3.2}
        position={[0, 5, 1]}
        rotation={[-Math.PI / 2, 0, 0]}
        scale={[10, 6, 1]}
        color="#eef4ff"
      />
      {/* Datum-cool fill from the front-left */}
      <Lightformer
        form="rect"
        intensity={1.5}
        position={[-5, 1.5, 3]}
        scale={[5, 6, 1]}
        color="#bcd8f2"
      />
      {/* cool rim from behind-right — the blueprint edge glow */}
      <Lightformer
        form="rect"
        intensity={1.6}
        position={[5, 2.5, -4]}
        scale={[6, 6, 1]}
        color="#2f74ac"
      />
      {/* small hot ring for a crisp specular catch */}
      <Lightformer
        form="ring"
        intensity={1.4}
        position={[3, 4, 2]}
        scale={2.5}
        color="#dbe8fb"
      />
    </Environment>
  );
}

/**
 * The ONE 3D viewer. Merges ModelViewer (File) + reconstruct MeshCanvas (URL).
 * On the "instrument" surface the part is presented as a hero product shot:
 * studio image-based lighting, a machined-aluminium material, a soft contact
 * shadow grounding it, and a Datum-blue bloom behind so it sits in light.
 */
export default function CadViewer({
  file,
  src,
  highlightFaces,
  highlightColor,
  ghostUnhighlighted,
  onFaceClick,
  surface = "light",
  className,
}: CadViewerProps) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [halfH, setHalfH] = useState(1);
  const [webGlAvailable, setWebGlAvailable] = useState<boolean | null>(null);
  const onHalfHeight = useCallback((h: number) => setHalfH(h), []);

  // Probe before react-three-fiber mounts. When GPU/WebGL is unavailable,
  // mounting Canvas causes repeated renderer retries and leaves a blank panel.
  useEffect(() => {
    setWebGlAvailable(probeWebGlSupport());
  }, []);

  useEffect(() => {
    if (file && file.name.toLowerCase().endsWith(".stl")) {
      const url = URL.createObjectURL(file);
      setObjectUrl(url);
      return () => URL.revokeObjectURL(url);
    }
    setObjectUrl(null);
  }, [file]);

  const url = useMemo(() => src ?? objectUrl, [src, objectUrl]);

  const instrument = surface === "instrument";

  if (!url) {
    return (
      <div
        className={cn(
          "flex h-full items-center justify-center rounded-[var(--radius)] border",
          instrument
            ? "border-border bg-card-raised text-muted-foreground"
            : "border-border bg-muted text-muted-foreground",
          className
        )}
      >
        <p className="text-sm">
          {file ? "STEP preview requires backend conversion" : "Upload a file to preview"}
        </p>
      </div>
    );
  }

  if (webGlAvailable !== true) {
    return (
      <div
        role="status"
        className={cn(
          "flex h-full flex-col items-center justify-center rounded-[var(--radius)] border px-6 text-center",
          instrument
            ? "border-border bg-card-raised text-muted-foreground"
            : "border-border bg-muted text-muted-foreground",
          className,
        )}
      >
        <p className="text-sm font-medium text-foreground">
          {webGlAvailable === null
            ? "Preparing the interactive preview…"
            : "Interactive 3D is unavailable in this browser."}
        </p>
        {webGlAvailable === false && (
          <p className="mt-1 max-w-md text-xs leading-5">
            The generated STEP, measured dimensions, evidence hash, download, and Verify handoff
            remain available below.
          </p>
        )}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "h-full overflow-hidden rounded-[var(--radius)] border",
        instrument
          ? STAGE_UI
            ? "border-[#252a2f]"
            : "border-[#22344f]"
          : "border-border bg-card-raised",
        className
      )}
      style={
        instrument
          ? STAGE_UI
            ? {
                // Stage: a warm-white key bloom centred where the hero part sits,
                // over the stage-0 floor (one light source, no decorative colour —
                // molten is rationed for the cost answer, not the lighting).
                background:
                  "radial-gradient(60% 54% at 50% 42%, rgba(244,242,238,0.09) 0%, rgba(244,242,238,0) 60%)," +
                  "radial-gradient(120% 118% at 50% -8%, #14171a 0%, #0c0e10 52%, #08090b 100%)",
              }
            : {
                // Legacy: a Datum-blue bloom centred where the part sits (the part
                // "sits in light"), over a deep near-black twilight ground — the
                // WebGL canvas is transparent so this glow reads behind the part.
                background:
                  "radial-gradient(66% 58% at 50% 47%, rgba(50,124,188,0.34) 0%, rgba(50,124,188,0) 62%)," +
                  "radial-gradient(120% 118% at 50% -6%, #15273f 0%, #0c1828 50%, #070d17 100%)",
              }
          : undefined
      }
    >
      <Canvas
        dpr={[1, 2]}
        gl={{ antialias: true, powerPreference: "high-performance" }}
        camera={{ fov: 38, near: 0.05, far: 100, position: [2, 1.6, 2.4] }}
      >
        {instrument ? (
          STAGE_UI ? (
            <>
              <ambientLight intensity={0.32} />
              {/* the single warm key — a bright specular streak on the metal */}
              <directionalLight position={[6, 9, 5]} intensity={2.0} color="#fff4e6" />
              {/* quiet steel rim from behind — separates part from the stage */}
              <directionalLight position={[-6, 3, -5]} intensity={0.55} color="#8fa0a6" />
              {/* gentle warm underfill so the shadowed side isn't dead */}
              <directionalLight position={[0, -4, 3]} intensity={0.24} color="#e8e2d6" />
            </>
          ) : (
            <>
              <ambientLight intensity={0.35} />
              {/* direct key for a bright specular streak on the metal */}
              <directionalLight position={[6, 9, 5]} intensity={1.8} color="#ffffff" />
              {/* Datum rim from behind — the cyanotype edge */}
              <directionalLight position={[-6, 3, -5]} intensity={0.7} color="#5b9bd6" />
              {/* gentle underfill so the shadowed side isn't dead */}
              <directionalLight position={[0, -4, 3]} intensity={0.28} color="#b9d0e8" />
            </>
          )
        ) : (
          <>
            <ambientLight intensity={0.45} />
            <directionalLight position={[10, 10, 10]} intensity={0.85} />
            <directionalLight position={[-5, 5, -5]} intensity={0.3} />
          </>
        )}
        <Suspense fallback={null}>
          <STLModel
            url={url}
            highlightFaces={highlightFaces}
            highlightColor={highlightColor}
            ghostUnhighlighted={ghostUnhighlighted}
            onFaceClick={onFaceClick}
            distanceScale={instrument ? 1.55 : 1.9}
            onHalfHeight={onHalfHeight}
          />
          {/* Keep every viewer mode self-contained. Drei's named presets resolve
              to remote HDR assets; production CSP correctly blocks those
              requests, leaving a noisy console and a preview at risk. The
              Lightformer rig above builds the environment map in-process. */}
          <StudioRig />
          {/* soft contact shadow seats the part on an invisible plane */}
          <ContactShadows
            position={[0, -halfH - 0.02, 0]}
            scale={TARGET * 3.4}
            far={TARGET * 2}
            blur={2.6}
            opacity={instrument ? (STAGE_UI ? 0.75 : 0.72) : 0.5}
            resolution={512}
            color={instrument ? (STAGE_UI ? "#050506" : "#03080f") : "#334155"}
            frames={1}
          />
        </Suspense>
        <OrbitControls
          makeDefault
          enableDamping
          dampingFactor={0.1}
          enablePan={false}
          minDistance={1.4}
          maxDistance={12}
          target={[0, 0, 0]}
        />
        {!instrument && (
          <gridHelper
            args={[8, 16, "#3a4655", "#232c37"]}
            position={[0, -halfH - 0.01, 0]}
          />
        )}
      </Canvas>
    </div>
  );
}

interface CadViewerProps {
  /** STL provided as a File (object URL is created/revoked internally) */
  file?: File | null;
  /** STL provided as a URL (e.g. reconstruct/label mesh endpoints) */
  src?: string;
  /** face indices to spotlight (recolored to {highlightColor}) */
  highlightFaces?: number[];
  /** highlight colour (defaults to the fail tone). Pass a warn tone for advisory issues. */
  highlightColor?: string;
  /** drop non-highlighted faces to low opacity for a "spotlight" effect */
  ghostUnhighlighted?: boolean;
  /** two-way link: fires the picked triangle index when a face is clicked */
  onFaceClick?: (faceIndex: number) => void;
  /** frame treatment: "light" = machinist paper (default); "instrument" = the
   *  blueprint-twilight working canvas the Living Instrument floats the part on. */
  surface?: "light" | "instrument";
  className?: string;
}
