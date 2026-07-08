/**
 * Page-local WebGL choreography for /teams/design-engineering — a faithful port
 * of the render loop in `handoff_cadverify_2026-07-04/site/For Design
 * Engineering.dc.html`.
 *
 * NOT foundation. This is the page's own five-act choreography (flag → dial →
 * fix → gate) wired to its section refs, consuming the shared {@link PartStage}
 * scene through the public {@link StageFrame}. It augments the studio scene with
 * ONE page-specific mesh (the glowing flagged-sidewall band) added to the shaft
 * group, and reads the shared rim light — both without editing the foundation.
 *
 * The band pulses amber across the DFM/dial acts (the failing draft face lit on
 * the part), turns green when the fix re-runs, and fades for the gate close.
 * Caption reveals are handled separately by the page's useRafLoop (so copy
 * reveals even where WebGL is unavailable).
 */

import * as THREE from "three";
import type { Choreography } from "@/components/site";
import { measureSection, lerp, clamp01, smooth } from "@/components/site";

export type DesignChoreoRefs = {
  /** Act 1 — the flag (DFM names the failing draft face). */
  sec1: React.RefObject<HTMLElement | null>;
  /** Act 2 — the dial (the brief changes with the volume). */
  sec2: React.RefObject<HTMLElement | null>;
  /** Act 3 — the fix (add the draft, the route unlocks). */
  sec3: React.RefObject<HTMLElement | null>;
  /** Act 4 — the gate (the answer is on screen). */
  sec4: React.RefObject<HTMLElement | null>;
};

export function makeDesignChoreography(refs: DesignChoreoRefs): Choreography {
  const amber = new THREE.Color(0xd9a856);
  const green = new THREE.Color(0x55b880);
  const rimBlue = new THREE.Color(0xbcd2ff);

  // Cached, lazily-built handles. Keyed to the current part/scene so a PartStage
  // remount (Fast Refresh) rebuilds against the fresh scene rather than reusing
  // a disposed mesh.
  let flag: THREE.Mesh | null = null;
  let flagMat: THREE.MeshBasicMaterial | null = null;
  let flagPart: THREE.Group | null = null;
  let rim: THREE.DirectionalLight | null = null;
  let rimScene: THREE.Scene | null = null;

  return (f) => {
    const { THREE: T, part, camera, renderer, scene, shadow, dt, elapsed } = f;

    // the flagged sidewall — a glowing open band on the failing faces (r 0.585
    // hugs the 0.58 neck between y≈0.31 and y≈0.65: the one <1.0° draft wall).
    if (flag === null || flagPart !== part) {
      flagMat = new T.MeshBasicMaterial({ color: 0xd9a856, transparent: true, opacity: 0, side: T.DoubleSide });
      flag = new T.Mesh(new T.CylinderGeometry(0.585, 0.585, 0.34, 90, 1, true), flagMat);
      flag.position.y = 0.48;
      part.add(flag);
      flagPart = part;
    }
    // the cool back light (position.z < 0 is the rim; the key light is at z > 0)
    if (rim === null || rimScene !== scene) {
      let found: THREE.DirectionalLight | null = null;
      scene.traverse((o) => {
        const dl = o as THREE.DirectionalLight;
        if (dl.isDirectionalLight && dl.position.z < 0) found = dl;
      });
      rim = found;
      rimScene = scene;
    }

    part.rotation.y += dt * 0.22;

    const m1 = measureSection(refs.sec1.current); // flag
    const m2 = measureSection(refs.sec2.current); // dial
    const m3 = measureSection(refs.sec3.current); // fix
    const m4 = measureSection(refs.sec4.current); // gate
    const a1 = smooth(clamp01(m1.ramp * 0.5 + m1.pin * 0.5));
    const a2 = smooth(clamp01(m2.ramp * 0.45 + m2.pin * 0.55));
    const a3 = smooth(clamp01(m3.ramp * 0.5 + m3.pin * 0.5));
    const a4 = smooth(clamp01(m4.ramp * 0.5 + m4.pin * 0.5));

    // the flagged band: amber pulse during acts 1–2, greens at the fix, fades at
    // the gate.
    const flagIn = Math.max(a1, a2) * (1 - a4);
    const pulse = 0.55 + Math.sin(elapsed * 3.2) * 0.18;
    if (flagMat) {
      flagMat.opacity = flagIn * (a3 > 0.5 ? 0.5 : pulse) * 0.7;
      flagMat.color.copy(amber).lerp(green, a3);
    }
    if (rim) {
      rim.color.copy(rimBlue).lerp(a3 > 0.01 ? green : amber, Math.max(a1 * 0.5, a3 * 0.8) * (1 - a4 * 0.6));
      rim.intensity = 1.6 + flagIn * 0.8 + a3 * 0.8;
    }

    // camera: approach the flagged wall, tilt for the dial, settle for the fix,
    // pull to center for the gate.
    const orbit = a1 * 0.9 + a2 * 0.8 - a3 * 0.4;
    const radius = lerp(lerp(lerp(lerp(5.4, 3.6, a1), 3.2, a2), 4.2, a3), 7.2, a4);
    camera.position.x = Math.sin(orbit) * radius;
    camera.position.z = Math.cos(orbit) * radius;
    camera.position.y = lerp(lerp(0.1, 0.75, a1), 0.2, a3);
    camera.lookAt(0, lerp(0, 0.35, Math.max(a1, a2) * (1 - a3)), 0);

    part.position.x = lerp(1.55, 0, Math.max(a1, a2));
    part.position.y = lerp(0, -0.45, a4) - Math.sin(elapsed * 0.8) * 0.04;
    part.rotation.z = lerp(0.35, lerp(0.12, -0.25, a2 * (1 - a3)), a1);

    // contact shadow tracks the part and dims for the gate close.
    shadow.position.x = part.position.x;
    (shadow.material as THREE.MeshBasicMaterial).opacity = 0.5 * (1 - a4 * 0.7);

    // gate: dim the world for the closing statement.
    renderer.toneMappingExposure = 1.15 * Math.max(0.35, 1 - a4 * 0.62);
  };
}
