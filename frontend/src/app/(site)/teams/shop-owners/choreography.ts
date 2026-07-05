/**
 * makeShopChoreography — the bespoke per-frame choreography for
 * /teams/shop-owners, ported faithfully from the render loop in
 * `handoff_cadverify_2026-07-04/site/For Shop Owners.dc.html`.
 *
 * Unlike the home choreography, this page's signature move is the LATHE CHUCK:
 * during the Friday-RFQ act three jaws + a chuck ring slide in and grip the
 * shaft while the spindle speeds up — the shop floor closing on the part. Those
 * meshes are not part of the shared studio, so this factory lazily builds them
 * into whatever scene the shared {@link PartStage} hands it (and rebuilds if the
 * stage remounts with a fresh scene). It also recolors the shared rim light
 * copper → amber → green across the four acts and dims toward the validated
 * floor. It touches the scene ONLY through the sanctioned choreography seam —
 * it edits no foundation file.
 *
 * PAGE-LOCAL — lives beside the page it drives, not in the foundation.
 */

import * as THREE from "three";
import type { RefObject } from "react";
import { clamp01, lerp, smooth, measureSection } from "@/components/site";
import type { Choreography, StageFrame } from "@/components/site";

export type ShopChoreoRefs = {
  /** 01 — Calibrate once (copper light rises). */
  sec1: RefObject<HTMLElement | null>;
  /** 02 — Friday, 4:50 PM (the chuck grips, spindle speeds up). */
  sec2: RefObject<HTMLElement | null>;
  /** 03 — Know which jobs don't fit (part tilts to the undercut side, amber). */
  sec3: RefObject<HTMLElement | null>;
  /** 04 — Close the loop (dim + green, the validated floor). */
  sec4: RefObject<HTMLElement | null>;
};

export function makeShopChoreography(refs: ShopChoreoRefs): Choreography {
  // per-scene state — rebuilt if PartStage remounts with a fresh scene.
  let builtFor: THREE.Scene | null = null;
  let jaws: THREE.Mesh[] = [];
  let chuckRing: THREE.Mesh | null = null;
  let jawMat: THREE.MeshStandardMaterial | null = null;
  let rim: THREE.DirectionalLight | null = null;
  let spin = 0.22;

  const rimBlue = new THREE.Color(0xbcd2ff);
  const copper = new THREE.Color(0xd08b4c);
  const amber = new THREE.Color(0xd9a856);
  const green = new THREE.Color(0x55b880);

  const build = (f: StageFrame) => {
    const T = f.THREE;
    // the chuck: three jaws that grip the shaft during the quoting act
    jawMat = new T.MeshStandardMaterial({
      color: 0x3a3f46, metalness: 0.9, roughness: 0.55,
      envMapIntensity: 0.5, transparent: true, opacity: 0,
    });
    jaws = [];
    for (let i = 0; i < 3; i++) {
      const jaw = new T.Mesh(new T.BoxGeometry(0.34, 0.6, 0.5), jawMat);
      jaw.userData = { ang: (i / 3) * Math.PI * 2 };
      jaw.visible = false;
      jaws.push(jaw);
      f.scene.add(jaw);
    }
    chuckRing = new T.Mesh(new T.TorusGeometry(1.5, 0.09, 14, 90), jawMat);
    chuckRing.rotation.x = Math.PI / 2;
    chuckRing.position.y = -1.35;
    chuckRing.visible = false;
    f.scene.add(chuckRing);

    // recolor the shared rim light — the (4, -1, -3) directional, x > 0
    let found: THREE.DirectionalLight | null = null;
    f.scene.traverse((o) => {
      const d = o as THREE.DirectionalLight;
      if (d.isDirectionalLight && d.position.x > 0) found = d;
    });
    rim = found;

    spin = 0.22;
    builtFor = f.scene;
  };

  return (f) => {
    if (builtFor !== f.scene) build(f);
    const { part, camera, renderer, dt, elapsed, mouse } = f;

    const m1 = measureSection(refs.sec1.current);
    const m2 = measureSection(refs.sec2.current);
    const m3 = measureSection(refs.sec3.current);
    const m4 = measureSection(refs.sec4.current);
    const a1 = smooth(clamp01(m1.ramp * 0.5 + m1.pin * 0.5));
    const a2 = smooth(clamp01(m2.ramp * 0.45 + m2.pin * 0.55));
    const a3 = smooth(clamp01(m3.ramp * 0.5 + m3.pin * 0.5));
    const a4 = smooth(clamp01(m4.ramp * 0.5 + m4.pin * 0.5));

    // 01 calibrate: the shop's copper light rises; amber on skip; green on loop
    const calib = a1 * (1 - a3);
    if (rim) {
      rim.color.copy(rimBlue).lerp(copper, calib * 0.85).lerp(amber, a3 * (1 - a4) * 0.7).lerp(green, a4 * 0.9);
      rim.intensity = 1.6 + calib * 1.2 + a4 * 1.4;
    }

    // 02 the RFQ: the chuck grips — jaws slide in, part seats, spindle speeds up
    const grip = a2 * (1 - a4);
    if (jawMat) jawMat.opacity = 0.55 * grip;
    const jawVisible = !!jawMat && jawMat.opacity > 0.01;
    const jawR = lerp(2.6, 1.02, smooth(grip));
    for (const j of jaws) {
      const worldAng = j.userData.ang as number;
      j.position.set(Math.cos(worldAng) * jawR, -0.85, Math.sin(worldAng) * jawR);
      j.lookAt(0, -0.85, 0);
      j.visible = jawVisible;
    }
    if (chuckRing) {
      chuckRing.visible = jawVisible;
      chuckRing.position.y = lerp(-2.6, -1.42, smooth(grip));
    }
    spin = lerp(spin, 0.22 + grip * 2.6 - a3 * 1.4, Math.min(1, dt * 3));
    part.rotation.y += dt * Math.max(0.08, spin);

    // 03 skip: the part tilts to reveal the undercut side
    part.rotation.z = lerp(0.35, lerp(0.12, -0.6, a3 * (1 - a4)), Math.max(a1, a2));
    part.position.x = lerp(1.55, 0, Math.max(a1, a2));
    part.position.y = lerp(0, -0.5, a4) - Math.sin(elapsed * 0.8) * 0.04 * (1 - grip);

    // 04 close the loop: dim toward the validated floor
    renderer.toneMappingExposure = 1.15 * Math.max(0.35, 1 - a4 * 0.6);

    // camera — orbit in on calibrate, push close for the grip, pull far for the loop
    const orbit = a1 * 0.8 + a3 * 0.7;
    const radius = lerp(lerp(lerp(lerp(5.4, 4.0, a1), 3.3, a2), 4.4, a3), 7.0, a4);
    camera.position.x = Math.sin(orbit) * radius + mouse.x * 0.15;
    camera.position.z = Math.cos(orbit) * radius;
    camera.position.y = lerp(0.1, lerp(0.5, -0.5, a2), a1) - mouse.y * 0.12;
    camera.lookAt(0, lerp(0, -0.5, a2 * (1 - a3)), 0);
  };
}
