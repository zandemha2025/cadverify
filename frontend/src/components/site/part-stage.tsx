"use client";

/**
 * PartStage — the reusable WebGL part-choreography stage for the dark-theater
 * marketing site. A faithful port of the fixed studio scene in
 * `handoff_cadverify_2026-07-04/site/Direction - Cinematic.dc.html`:
 * a turned-aluminum shaft (the real object.stl silhouette) floating in a
 * painted studio, with groove rings, an x-ray wireframe twin, a metrology
 * overlay + scan sweep, a soft contact shadow, ghost gearbox siblings that
 * seat around it, dust motes, and damped mouse parallax.
 *
 * PRODUCTION THREE: imports the repo's installed `three` (NO CDN / unpkg — the
 * design pulls three r160 from unpkg for standalone viewing only). All WebGL
 * touches happen in `useEffect`, so the component is SSR-safe (renders an empty
 * canvas on the server).
 *
 * REUSE SEAM: the per-frame choreography is a callback prop. With none passed
 * you get a tasteful default (idle spin + parallax + a gentle scroll-tied
 * orbit) — enough to make any page's shaft feel alive. The home page's exact
 * five-act choreography is provided as {@link makeHomeChoreography}, a factory
 * page builders wire to their own section refs WITHOUT editing this file.
 *
 * SHARED FOUNDATION — do not edit in a page branch.
 */

import * as THREE from "three";
import { useEffect, useRef, useState } from "react";
import { clamp01, lerp, smooth, documentScrollProgress, measureSection } from "@/lib/site/scroll-acts";
import { acquireWebGlContext } from "@/lib/site/webgl";

/** Live scene handles handed to a choreography every frame. */
export type StageObjects = {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  /** The part group (shaft + rings + wire + metrology + scan). */
  part: THREE.Group;
  materials: {
    alu: THREE.MeshPhysicalMaterial;
    ring: THREE.MeshStandardMaterial;
    wire: THREE.MeshBasicMaterial;
    metro: THREE.LineBasicMaterial;
    scan: THREE.MeshBasicMaterial;
    ghost: THREE.MeshStandardMaterial;
  };
  /** Ghost gearbox siblings; each carries `userData.seat` / `userData.scatter`. */
  ghosts: THREE.Mesh[];
  scan: THREE.Mesh;
  shadow: THREE.Mesh;
  dust: THREE.Points;
};

/** Everything a per-frame choreography needs. */
export type StageFrame = StageObjects & {
  THREE: typeof THREE;
  /** Seconds since previous frame (clamped for tab-restore safety). */
  dt: number;
  /** Total seconds since the scene mounted. */
  elapsed: number;
  /** Eased whole-document scroll progress, 0..1. */
  scrollT: number;
  width: number;
  height: number;
  /** Damped, normalized pointer position in [-1, 1]. */
  mouse: { x: number; y: number };
  /**
   * Project a PART-space anchor to screen pixels (applies part.matrixWorld then
   * the camera), matching the design's HUD label placement.
   */
  projectPart: (v: THREE.Vector3) => { x: number; y: number };
};

export type Choreography = (f: StageFrame) => void;

/** Idle spin + damped parallax + a gentle scroll-tied orbit (the default). */
const defaultChoreography: Choreography = (f) => {
  const { part, camera, mouse, dt, elapsed, scrollT } = f;
  part.rotation.y += dt * 0.22;
  const drift = smooth(clamp01(scrollT * 1.4));
  const radius = lerp(5.4, 4.2, drift);
  camera.position.x = mouse.x * 0.28;
  camera.position.z = radius;
  camera.position.y = 0.1 + Math.sin(elapsed * 0.5) * 0.03 - mouse.y * 0.2;
  camera.lookAt(0, 0, 0);
  part.position.y = -Math.sin(elapsed * 0.8) * 0.04;
};

export type PartStageProps = {
  className?: string;
  style?: React.CSSProperties;
  /** Per-frame choreography. Omit for the default idle/parallax behavior. */
  choreography?: Choreography;
  /** Cap device pixel ratio (default 2). Lower it on heavy pages. */
  maxDpr?: number;
  /** Pause the render loop (e.g. offscreen). Default false. */
  paused?: boolean;
};

/**
 * Build the shared studio scene. Returns the scene handles plus a `dispose`.
 * Kept as a plain function (not a hook) so the lifecycle is atomic and testable.
 */
function buildScene(canvas: HTMLCanvasElement, maxDpr: number): (StageObjects & { dispose: () => void }) | null {
  const context = acquireWebGlContext(canvas);
  if (!context) return null;

  const renderer = new THREE.WebGLRenderer({ canvas, context, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(maxDpr, window.devicePixelRatio || 1));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x050506, 0.045);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  camera.position.set(0, 0, 5.4);

  // ── studio environment: softboxes painted on black, as an equirect canvas ──
  const envCanvas = document.createElement("canvas");
  envCanvas.width = 512;
  envCanvas.height = 256;
  const ec = envCanvas.getContext("2d")!;
  ec.fillStyle = "#0a0b0d";
  ec.fillRect(0, 0, 512, 256);
  const soft = (x: number, y: number, w: number, h: number, bright: number) => {
    const g = ec.createRadialGradient(x + w / 2, y + h / 2, 2, x + w / 2, y + h / 2, Math.max(w, h) / 2);
    g.addColorStop(0, `rgba(255,255,255,${bright})`);
    g.addColorStop(1, "rgba(255,255,255,0)");
    ec.fillStyle = g;
    ec.fillRect(x, y, w, h);
  };
  soft(60, 20, 190, 130, 0.95); // key softbox upper-left
  soft(330, 130, 150, 90, 0.5); // fill lower-right
  soft(430, 10, 70, 60, 0.85); // rim ping
  ec.fillStyle = "rgba(255,255,255,0.06)";
  ec.fillRect(0, 118, 512, 6); // horizon strip
  const envTex = new THREE.CanvasTexture(envCanvas);
  envTex.mapping = THREE.EquirectangularReflectionMapping;
  envTex.colorSpace = THREE.SRGBColorSpace;
  scene.environment = envTex;

  // ── the machined part: a turned aluminum body (LatheGeometry) ──
  const pts: THREE.Vector2[] = [];
  const P = (r: number, y: number) => pts.push(new THREE.Vector2(r, y));
  P(0.001, -1.05); P(0.42, -1.05); P(0.46, -1.0); P(0.46, -0.62); P(0.58, -0.58);
  P(0.58, -0.34); P(0.72, -0.3); P(0.86, -0.22); P(0.9, -0.1); P(0.9, 0.14);
  P(0.86, 0.2); P(0.62, 0.24); P(0.58, 0.3); P(0.58, 0.66); P(0.4, 0.7);
  P(0.34, 0.76); P(0.34, 0.98); P(0.28, 1.05); P(0.001, 1.05);
  const bodyGeo = new THREE.LatheGeometry(pts, 128);
  const alu = new THREE.MeshPhysicalMaterial({
    color: 0xc8ccd2, metalness: 1.0, roughness: 0.3,
    clearcoat: 0.55, clearcoatRoughness: 0.28,
    envMapIntensity: 1.5, transparent: true, opacity: 1,
  });
  const body = new THREE.Mesh(bodyGeo, alu);

  // groove rings (machining marks)
  const ringMat = new THREE.MeshStandardMaterial({
    color: 0x9ba1a9, metalness: 1.0, roughness: 0.45, envMapIntensity: 1.2, transparent: true,
  });
  const rings = new THREE.Group();
  ([[-0.48, 0.585], [0.0, 0.905], [0.48, 0.585]] as const).forEach(([y, r]) => {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(r, 0.012, 12, 100), ringMat);
    ring.rotation.x = Math.PI / 2;
    ring.position.y = y;
    rings.add(ring);
  });

  // x-ray wireframe twin
  const wireMat = new THREE.MeshBasicMaterial({ color: 0xaebdcd, wireframe: true, transparent: true, opacity: 0 });
  const wire = new THREE.Mesh(new THREE.LatheGeometry(pts, 64), wireMat);
  wire.scale.setScalar(1.002);

  const part = new THREE.Group();
  part.add(body);
  part.add(rings);
  part.add(wire);
  part.rotation.z = 0.35;
  scene.add(part);

  // ── metrology overlay: dimension lines drawn on the part (routed act) ──
  const mLineMat = new THREE.LineBasicMaterial({ color: 0x8fb7dd, transparent: true, opacity: 0 });
  const metro = new THREE.Group();
  const seg3 = (a: [number, number, number], b: [number, number, number]) => {
    const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...a), new THREE.Vector3(...b)]);
    metro.add(new THREE.Line(g, mLineMat));
  };
  seg3([0, -1.6, 0], [0, 1.6, 0]); // datum axis
  seg3([-1.28, -0.02, 0], [1.28, -0.02, 0]); // diameter callout
  seg3([-1.28, -0.1, 0], [-1.28, 0.06, 0]);
  seg3([1.28, -0.1, 0], [1.28, 0.06, 0]);
  seg3([-0.9, -0.02, 0], [-0.9, -0.3, 0]);
  seg3([0.9, -0.02, 0], [0.9, -0.3, 0]);
  seg3([1.5, -1.05, 0], [1.5, 1.05, 0]); // height callout
  seg3([1.42, -1.05, 0], [1.58, -1.05, 0]);
  seg3([1.42, 1.05, 0], [1.58, 1.05, 0]);
  part.add(metro);

  // ── scan ring: a bright coil that sweeps the part while it's being read ──
  const scanMat = new THREE.MeshBasicMaterial({ color: 0x9fd0ff, transparent: true, opacity: 0 });
  const scan = new THREE.Mesh(new THREE.TorusGeometry(1.06, 0.0075, 10, 110), scanMat);
  scan.rotation.x = Math.PI / 2;
  part.add(scan);

  // ── contact shadow: soft dark pool beneath the part ──
  const shCanvas = document.createElement("canvas");
  shCanvas.width = 256;
  shCanvas.height = 256;
  const shc = shCanvas.getContext("2d")!;
  const shg = shc.createRadialGradient(128, 128, 8, 128, 128, 128);
  shg.addColorStop(0, "rgba(0,0,0,0.85)");
  shg.addColorStop(0.6, "rgba(0,0,0,0.35)");
  shg.addColorStop(1, "rgba(0,0,0,0)");
  shc.fillStyle = shg;
  shc.fillRect(0, 0, 256, 256);
  const shTex = new THREE.CanvasTexture(shCanvas);
  const shadow = new THREE.Mesh(
    new THREE.PlaneGeometry(4.6, 4.6),
    new THREE.MeshBasicMaterial({ map: shTex, transparent: true, opacity: 0.5, depthWrite: false }),
  );
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.y = -1.62;
  scene.add(shadow);

  // ── the gearbox housing: ghost siblings that seat around the shaft ──
  const ghostMat = new THREE.MeshStandardMaterial({
    color: 0x3a3f46, metalness: 0.9, roughness: 0.55, envMapIntensity: 0.5, transparent: true, opacity: 0,
  });
  const latheOf = (profile: [number, number][], segs = 80) =>
    new THREE.LatheGeometry(profile.map(([r, y]) => new THREE.Vector2(r, y)), segs);
  const flangeGeo = latheOf([[0.3, -0.16], [1.15, -0.16], [1.22, -0.08], [1.22, 0.06], [0.66, 0.1], [0.46, 0.14], [0.3, 0.14]]);
  const bushGeo = latheOf([[0.62, -0.34], [0.86, -0.34], [0.86, 0.34], [0.62, 0.34]]);
  const ghosts: THREE.Mesh[] = [];
  const addGhost = (geo: THREE.BufferGeometry, seat: [number, number, number], scatter: [number, number, number], rot?: [number, number, number]) => {
    const m = new THREE.Mesh(geo, ghostMat);
    if (rot) m.rotation.set(rot[0], rot[1], rot[2]);
    m.userData = { seat: new THREE.Vector3(...seat), scatter: new THREE.Vector3(...scatter) };
    m.position.copy(m.userData.scatter as THREE.Vector3);
    ghosts.push(m);
    scene.add(m);
  };
  addGhost(flangeGeo, [0, 1.32, 0], [0.6, 4.4, -1.2]); // top flange, drops in
  addGhost(flangeGeo, [0, -1.32, 0], [-0.5, -4.4, -1.0], [Math.PI, 0, 0]); // bottom flange, rises in
  addGhost(bushGeo, [0, -0.45, 0], [-4.6, -0.9, -1.6]); // bearing bushing, slides in
  addGhost(new THREE.TorusGeometry(1.05, 0.05, 12, 90), [0, 0.45, 0], [4.8, 1.1, -1.4], [Math.PI / 2, 0, 0]); // retaining ring
  addGhost(new THREE.CylinderGeometry(0.1, 0.1, 2.4, 20), [1.55, 0, -0.5], [1.9, 0, -5.5]); // guide rail
  addGhost(new THREE.CylinderGeometry(0.1, 0.1, 2.4, 20), [-1.55, 0, -0.5], [-1.9, 0, -5.5]); // guide rail

  // lights (shape the metal beyond the env)
  const key = new THREE.DirectionalLight(0xffffff, 2.4);
  key.position.set(-3, 4, 3);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xbcd2ff, 1.6);
  rim.position.set(4, -1, -3);
  scene.add(rim);
  scene.add(new THREE.AmbientLight(0x1a1d22, 1.2));

  // dust motes for depth
  const dustGeo = new THREE.BufferGeometry();
  const N = 220;
  const posArr = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    posArr[i * 3] = (Math.random() - 0.5) * 14;
    posArr[i * 3 + 1] = (Math.random() - 0.5) * 9;
    posArr[i * 3 + 2] = (Math.random() - 0.5) * 7 - 1;
  }
  dustGeo.setAttribute("position", new THREE.BufferAttribute(posArr, 3));
  const dust = new THREE.Points(dustGeo, new THREE.PointsMaterial({ color: 0x8892a0, size: 0.012, transparent: true, opacity: 0.45 }));
  scene.add(dust);

  const dispose = () => {
    renderer.dispose();
    scene.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (mesh.geometry) mesh.geometry.dispose();
      const mat = (mesh as THREE.Mesh).material;
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
      else if (mat) (mat as THREE.Material).dispose();
    });
    envTex.dispose();
    shTex.dispose();
  };

  return {
    scene, camera, renderer, part,
    materials: { alu, ring: ringMat, wire: wireMat, metro: mLineMat, scan: scanMat, ghost: ghostMat },
    ghosts, scan, shadow, dust, dispose,
  };
}

export function PartStage({ className, style, choreography, maxDpr = 2, paused = false }: PartStageProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [fallback, setFallback] = useState(false);
  const choreoRef = useRef<Choreography | undefined>(choreography);
  const pausedRef = useRef(paused);

  useEffect(() => {
    choreoRef.current = choreography;
  }, [choreography]);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || typeof window === "undefined") return;

    let built: ReturnType<typeof buildScene>;
    try {
      built = buildScene(canvas, maxDpr);
    } catch {
      built = null;
    }
    if (!built) {
      setFallback(true);
      return;
    }
    setFallback(false);
    const { renderer, camera, part } = built;

    let raf = 0;
    const onContextLost = (event: Event) => {
      event.preventDefault();
      cancelAnimationFrame(raf);
      setFallback(true);
    };
    canvas.addEventListener("webglcontextlost", onContextLost);

    const parent = canvas.parentElement ?? canvas;
    const size = () => ({
      w: parent.clientWidth || window.innerWidth,
      h: parent.clientHeight || window.innerHeight,
    });
    const applySize = () => {
      const { w, h } = size();
      if (w === 0 || h === 0) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
    };
    applySize();
    const ro = new ResizeObserver(applySize);
    ro.observe(parent);

    // damped mouse parallax — the studio breathes with the cursor
    const mouse = { x: 0, y: 0 };
    const mp = { x: 0, y: 0 };
    const onMouse = (e: MouseEvent) => {
      mouse.x = (e.clientX / window.innerWidth) * 2 - 1;
      mouse.y = (e.clientY / window.innerHeight) * 2 - 1;
    };
    window.addEventListener("mousemove", onMouse, { passive: true });

    const reduce =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let last = performance.now();
    const start = last;
    let scrollT = documentScrollProgress();
    let target = scrollT;
    const onScroll = () => {
      target = documentScrollProgress();
    };
    window.addEventListener("scroll", onScroll, { passive: true });

    const ndc = new THREE.Vector3();
    const projectPart = (v: THREE.Vector3) => {
      const { w, h } = size();
      ndc.copy(v).applyMatrix4(part.matrixWorld).project(camera);
      return { x: (ndc.x * 0.5 + 0.5) * w, y: (-ndc.y * 0.5 + 0.5) * h };
    };

    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      if (pausedRef.current) {
        last = now;
        return;
      }
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      scrollT = reduce ? target : lerp(scrollT, target, Math.min(1, dt * 5));
      mp.x = lerp(mp.x, mouse.x, Math.min(1, dt * 2.4));
      mp.y = lerp(mp.y, mouse.y, Math.min(1, dt * 2.4));
      const { w, h } = size();

      const frame: StageFrame = {
        ...built,
        THREE,
        dt,
        elapsed: (now - start) / 1000,
        scrollT,
        width: w,
        height: h,
        mouse: mp,
        projectPart,
      };
      (choreoRef.current ?? defaultChoreography)(frame);

      built.dust.rotation.y += dt * 0.01;
      renderer.render(built.scene, camera);
    };
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("mousemove", onMouse);
      window.removeEventListener("scroll", onScroll);
      canvas.removeEventListener("webglcontextlost", onContextLost);
      built.dispose();
    };
    // maxDpr is read once at scene build; choreography/paused are ref-tracked.
  }, [maxDpr]);

  return (
    <div
      className={className}
      data-render-mode={fallback ? "static" : "webgl"}
      style={{ position: "absolute", inset: 0, ...style }}
      aria-hidden="true"
    >
      {fallback && (
        <div
          data-testid="part-stage-static-fallback"
          style={{
            position: "absolute",
            inset: 0,
            overflow: "hidden",
            background:
              "radial-gradient(circle at 68% 46%, rgba(116,130,148,0.18), transparent 30%), radial-gradient(circle at 58% 52%, #11151b 0, #07090c 48%, #030405 100%)",
          }}
        >
          <svg
            viewBox="0 0 1200 800"
            preserveAspectRatio="xMidYMid slice"
            width="100%"
            height="100%"
            focusable="false"
          >
            <defs>
              <linearGradient id="cv-static-metal" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#e4e8ee" />
                <stop offset="0.28" stopColor="#8f98a5" />
                <stop offset="0.55" stopColor="#d5dae1" />
                <stop offset="1" stopColor="#515a67" />
              </linearGradient>
              <radialGradient id="cv-static-shadow">
                <stop offset="0" stopColor="#000" stopOpacity="0.72" />
                <stop offset="1" stopColor="#000" stopOpacity="0" />
              </radialGradient>
            </defs>
            <ellipse cx="780" cy="590" rx="300" ry="70" fill="url(#cv-static-shadow)" />
            <g transform="translate(790 410) rotate(-18)">
              <path
                d="M-310-66h95l24-34h95l28-32H68l28 32h95l24 34h95v132h-95l-24 34H96l-28 32H-68l-28-32h-95l-24-34h-95z"
                fill="url(#cv-static-metal)"
                stroke="#f4f6f9"
                strokeOpacity="0.35"
                strokeWidth="3"
              />
              <path d="M-214-66v132M-96-100v200M96-100v200M214-66v132" stroke="#434c58" strokeWidth="9" opacity="0.72" />
              <path d="M-300-48H300" stroke="#fff" strokeWidth="4" opacity="0.18" />
            </g>
          </svg>
        </div>
      )}
      <canvas
        ref={canvasRef}
        style={{ display: fallback ? "none" : "block", width: "100%", height: "100%" }}
      />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   makeHomeChoreography — the exact five-act cinematic choreography from
   `Direction - Cinematic.dc.html`, as a factory the home-page builder wires to
   its own section refs. Kept in the foundation so the choreography stays
   canonical and a page builder never re-derives (or drifts from) it.

   Pass refs to the act sections (each a tall section with a sticky child) plus
   the two HUD label spans and the monumental `$14.14` number element. The
   number counts up in the DOM (textContent) so it never triggers React renders.
   ═══════════════════════════════════════════════════════════════════════════ */

export type HomeChoreoRefs = {
  routed: React.RefObject<HTMLElement | null>;   // Act 2 — reads the shape
  glassBox: React.RefObject<HTMLElement | null>; // Act 3 — x-ray opens
  assembly: React.RefObject<HTMLElement | null>; // Act 3.5 — seats in housing
  number: React.RefObject<HTMLElement | null>;   // Act 4 — the number
  close: React.RefObject<HTMLElement | null>;    // Act 5 — close
  /** Optional: the monumental $14.14 element (counts up in place). */
  numberEl?: React.RefObject<HTMLElement | null>;
  /** Optional HUD label spans, projected from part-space each frame. */
  hud1?: React.RefObject<HTMLElement | null>;
  hud2?: React.RefObject<HTMLElement | null>;
};

export function makeHomeChoreography(refs: HomeChoreoRefs): Choreography {
  const hudA1 = new THREE.Vector3(-1.24, 0.14, 0);
  const hudA2 = new THREE.Vector3(1.56, 1.18, 0);

  return (f) => {
    const { part, camera, renderer, materials, ghosts, scan, shadow, dt, elapsed, mouse } = f;
    const m1 = measureSection(refs.routed.current);
    const m2 = measureSection(refs.glassBox.current);
    const m2b = measureSection(refs.assembly.current);
    const m3 = measureSection(refs.number.current);
    const m4 = measureSection(refs.close.current);

    const aHero = smooth(m1.ramp);
    const aRoute = smooth(clamp01(m1.ramp * 0.55 + m1.pin * 0.45));
    const aXray = smooth(clamp01(m2.ramp * 0.45 + m2.pin * 0.55));
    const aAsm = smooth(clamp01(m2b.ramp * 0.4 + m2b.pin * 0.6));
    const aNum = smooth(clamp01(m3.ramp * 0.5 + m3.pin * 0.5));
    const aClose = smooth(m4.ramp);

    // idle spin (settles while seated in the housing)
    const seatEase = smooth(aAsm * (1 - aNum));
    part.rotation.y += dt * (0.22 - 0.16 * seatEase);

    // assembly: ghosts fly in and seat; gone again by the number act
    materials.ghost.opacity = 0.5 * seatEase;
    for (const g of ghosts) {
      const seat = g.userData.seat as THREE.Vector3;
      const scatter = g.userData.scatter as THREE.Vector3;
      g.position.lerpVectors(scatter, seat, seatEase);
      g.visible = seatEase > 0.01;
    }

    // camera: drift in, orbit, push close, pull back for assembly, far for number
    const orbit = aRoute * 1.35;
    const radius = lerp(lerp(lerp(lerp(5.4, 4.1, aHero), 3.1, aXray), 6.0, aAsm), 7.5, aNum);
    camera.position.x = Math.sin(orbit) * radius + lerp(1.4, 0, aNum) * (1 - aHero * 0.4) + mouse.x * 0.28;
    camera.position.z = Math.cos(orbit) * radius;
    camera.position.y = lerp(lerp(0.1, 0.55, aRoute), -0.2, aXray) - mouse.y * 0.2;
    camera.lookAt(0, lerp(0, -0.1, aNum), 0);

    // x-ray dissolve factor
    const x = aXray * (1 - Math.max(aAsm, aNum));

    // metrology overlay + scan sweep, alive only while the engine reads the shape
    const metroIn = aRoute * (1 - aXray);
    materials.metro.opacity = metroIn * 0.55;
    const sweep = (elapsed * 0.45) % 1;
    scan.position.y = -1.1 + sweep * 2.2;
    scan.scale.setScalar(1 + Math.sin(sweep * Math.PI) * 0.02);
    materials.scan.opacity = metroIn * 0.85 * Math.sin(sweep * Math.PI);

    // project HUD labels from part-space anchors
    const placeHud = (el: HTMLElement | null | undefined, anchor: THREE.Vector3) => {
      if (!el) return;
      const p = f.projectPart(anchor.clone());
      el.style.transform = `translate(${p.x.toFixed(0)}px,${p.y.toFixed(0)}px)`;
      el.style.opacity = (metroIn * 0.9).toFixed(3);
    };
    placeHud(refs.hud1?.current, hudA1);
    placeHud(refs.hud2?.current, hudA2);

    // contact shadow follows and fades as the part lifts away
    shadow.position.x = part.position.x;
    (shadow.material as THREE.MeshBasicMaterial).opacity = 0.5 * (1 - aNum * 0.9) * (1 - x * 0.6);
    shadow.scale.setScalar(Math.max(0.6, 1 + (part.position.y + 0.1) * 0.12));

    // the number counts up as it arrives
    const numEl = refs.numberEl?.current;
    if (numEl) {
      const k = smooth(clamp01(aNum * 1.25));
      const txt = "$" + (14.14 * k).toFixed(2);
      if (numEl.textContent !== txt) numEl.textContent = txt;
    }

    // part offset: right of copy in hero, center later, sink + dim at number
    part.position.x = lerp(1.55, 0, Math.max(aRoute, aXray));
    part.position.y = lerp(0, -0.55, aNum) - Math.sin(elapsed * 0.8) * 0.04;
    part.rotation.z = lerp(lerp(0.35, 0.12, aRoute), 0, seatEase);
    part.scale.setScalar(lerp(1, 0.55, aNum * 0.9));

    // x-ray dissolve — re-solidifies before the assembly seats
    materials.alu.opacity = lerp(1, 0.12, x);
    materials.ring.opacity = lerp(1, 0.1, x);
    materials.wire.opacity = lerp(0, 0.55, x);
    const dimAll = 1 - aNum * 0.75 - aClose * 0.2;
    renderer.toneMappingExposure = 1.15 * Math.max(0.25, dimAll);
  };
}
