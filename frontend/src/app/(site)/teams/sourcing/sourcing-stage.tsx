"use client";

/**
 * SourcingStage — the page-local WebGL choreography for /teams/sourcing
 * ("For Sourcing"). A faithful port of the fixed studio scene + five-act
 * choreography in `handoff_cadverify_2026-07-04/site/For Sourcing.dc.html`.
 *
 * This is a PAGE-LOCAL stage, not the shared home shaft: its scene is specific
 * to the sourcing story — a turned-aluminum FLANGE (the quoted part) plus two
 * ghost copies that fan out into the "three quotes" (make in-house / make
 * outside / acquire), a copper "negotiation-lever" light on the divergent
 * driver, and a rank of portfolio minis that rise as triage runs across the
 * catalog. The shared PartStage builds a different scene (the shaft), so this
 * page owns its own faithful recreation here.
 *
 * PRODUCTION THREE: imports the repo's installed `three` (NO CDN / unpkg — the
 * design pulls three r160 from unpkg for standalone viewing only). All WebGL
 * touches happen in `useEffect`, so this is SSR-safe (empty canvas on server).
 *
 * The choreography reads the four act sections' live layout every frame via the
 * foundation's `measureSection`, so it never desyncs from the DOM. Caption
 * reveals are driven separately by the page (see sourcing-view.tsx) so the copy
 * still reveals even where WebGL is unavailable.
 */

import * as THREE from "three";
import { useEffect } from "react";
import { measureSection, lerp, clamp01, smooth } from "@/lib/site/scroll-acts";

export type SourcingStageRefs = {
  /** Act 1 — the three quotes fan in. */
  sec1: React.RefObject<HTMLElement | null>;
  /** Act 2 — the negotiation lever (copper light). */
  sec2: React.RefObject<HTMLElement | null>;
  /** Act 3 — the meeting (world dims, part recedes). */
  sec3: React.RefObject<HTMLElement | null>;
  /** Act 4 — the portfolio (minis rise, hero shrinks to join the ranks). */
  sec4: React.RefObject<HTMLElement | null>;
};

export function SourcingStage({ refs }: { refs: SourcingStageRefs }) {
  useEffect(() => {
    if (typeof window === "undefined") return;
    const stage = document.getElementById("sourcing-stage");
    if (!stage) return;

    const THREEns = THREE;
    const W = () => stage.clientWidth || window.innerWidth;
    const H = () => stage.clientHeight || window.innerHeight;

    const renderer = new THREEns.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setSize(W(), H());
    renderer.toneMapping = THREEns.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    stage.appendChild(renderer.domElement);
    renderer.domElement.style.display = "block";
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";

    // ── studio environment (softboxes painted on black, equirect canvas) ──
    const makeEnv = () => {
      const c = document.createElement("canvas");
      c.width = 512;
      c.height = 256;
      const x = c.getContext("2d")!;
      x.fillStyle = "#0a0b0d";
      x.fillRect(0, 0, 512, 256);
      const soft = (px: number, py: number, w: number, h: number, b: number) => {
        const g = x.createRadialGradient(px + w / 2, py + h / 2, 2, px + w / 2, py + h / 2, Math.max(w, h) / 2);
        g.addColorStop(0, `rgba(255,255,255,${b})`);
        g.addColorStop(1, "rgba(255,255,255,0)");
        x.fillStyle = g;
        x.fillRect(px, py, w, h);
      };
      soft(60, 20, 190, 130, 0.95);
      soft(330, 130, 150, 90, 0.5);
      soft(430, 10, 70, 60, 0.85);
      const t = new THREEns.CanvasTexture(c);
      t.mapping = THREEns.EquirectangularReflectionMapping;
      t.colorSpace = THREEns.SRGBColorSpace;
      return t;
    };

    const scene = new THREEns.Scene();
    const envTex = makeEnv();
    scene.environment = envTex;
    scene.fog = new THREEns.FogExp2(0x050506, 0.045);
    const camera = new THREEns.PerspectiveCamera(38, W() / H(), 0.1, 100);
    camera.position.set(0, 0, 5.4);

    // flange profile (the quoted part on this journey)
    const fl: [number, number][] = [
      [0.001, -0.28], [1.05, -0.28], [1.1, -0.2], [1.1, 0.02], [0.6, 0.08],
      [0.42, 0.12], [0.42, 0.5], [0.34, 0.56], [0.001, 0.56],
    ];
    const geo = new THREEns.LatheGeometry(fl.map(([r, y]) => new THREEns.Vector2(r, y)), 110);
    const aluBase = { metalness: 1.0, roughness: 0.32, envMapIntensity: 1.5, transparent: true };
    const aluA = new THREEns.MeshStandardMaterial({ color: 0xc8ccd2, ...aluBase });
    const aluB = new THREEns.MeshStandardMaterial({ color: 0xc8ccd2, ...aluBase, opacity: 0 });
    const aluC = new THREEns.MeshStandardMaterial({ color: 0xc8ccd2, ...aluBase, opacity: 0 });
    const hero = new THREEns.Mesh(geo, aluA);
    const quoteB = new THREEns.Mesh(geo, aluB);
    const quoteC = new THREEns.Mesh(geo, aluC);
    hero.rotation.z = 0.3;
    quoteB.rotation.z = 0.3;
    quoteC.rotation.z = 0.3;
    scene.add(hero);
    scene.add(quoteB);
    scene.add(quoteC);

    // portfolio minis
    const miniMat = new THREEns.MeshStandardMaterial({ color: 0x9aa2ac, ...aluBase, opacity: 0 });
    const minis: THREE.Mesh[] = [];
    for (let i = 0; i < 8; i++) {
      const m = new THREEns.Mesh(geo, miniMat);
      m.scale.setScalar(0.32);
      const col = i % 4;
      const row = Math.floor(i / 4);
      const mx = (col - 1.5) * 1.5;
      const my = row === 0 ? 0.9 : -0.9;
      m.position.set(mx, my, -2.5);
      m.rotation.z = 0.3 + i * 0.35;
      minis.push(m);
      scene.add(m);
    }

    const key = new THREEns.DirectionalLight(0xffffff, 2.4);
    key.position.set(-3, 4, 3);
    scene.add(key);
    const rim = new THREEns.DirectionalLight(0xbcd2ff, 1.6);
    rim.position.set(4, -1, -3);
    scene.add(rim);
    scene.add(new THREEns.AmbientLight(0x1a1d22, 1.2));

    const silver = new THREEns.Color(0xc8ccd2);
    const copper = new THREEns.Color(0xd08b4c);

    const onResize = () => {
      camera.aspect = W() / H();
      camera.updateProjectionMatrix();
      renderer.setSize(W(), H());
    };
    window.addEventListener("resize", onResize);
    const ro = new ResizeObserver(onResize);
    ro.observe(stage);

    let dead = false;
    let raf = 0;
    const clock = new THREEns.Clock();
    const loop = () => {
      if (dead) return;
      raf = requestAnimationFrame(loop);
      const dt = clock.getDelta();
      const elapsed = clock.elapsedTime;
      hero.rotation.y += dt * 0.22;
      quoteB.rotation.y += dt * 0.18;
      quoteC.rotation.y += dt * 0.26;

      const m1 = measureSection(refs.sec1.current); // three quotes
      const m2 = measureSection(refs.sec2.current); // lever
      const m3 = measureSection(refs.sec3.current); // meeting
      const m4 = measureSection(refs.sec4.current); // portfolio
      const a1 = smooth(clamp01(m1.ramp * 0.5 + m1.pin * 0.5));
      const a2 = smooth(clamp01(m2.ramp * 0.45 + m2.pin * 0.55));
      const a3 = smooth(clamp01(m3.ramp * 0.5 + m3.pin * 0.5));
      const a4 = smooth(clamp01(m4.ramp * 0.5 + m4.pin * 0.5));

      // three quotes fan in during act 1; hero centers
      const fan = a1 * (1 - a3);
      hero.position.x = lerp(1.55, 0, Math.max(a1, a2));
      hero.position.y = -Math.sin(elapsed * 0.8) * 0.04;
      aluB.opacity = 0.55 * fan * (1 - a2 * 0.6);
      aluC.opacity = 0.55 * fan * (1 - a2 * 0.6);
      quoteB.position.set(hero.position.x - lerp(0, 2.4, fan), 0.25, -0.8);
      quoteC.position.set(hero.position.x + lerp(0, 2.4, fan), -0.25, -0.8);
      quoteB.visible = aluB.opacity > 0.01;
      quoteC.visible = aluC.opacity > 0.01;

      // the lever: the hero part itself takes the copper light — the divergent line
      aluA.color.copy(silver).lerp(copper, a2 * (1 - a3) * 0.65);
      rim.color.set(0xbcd2ff).lerp(copper, a2 * (1 - a3) * 0.8);
      rim.intensity = 1.6 + a2 * (1 - a3) * 1.2;

      // meeting: dim world, part recedes low
      hero.position.y += lerp(0, -0.55, a3 * (1 - a4));
      renderer.toneMappingExposure = 1.15 * Math.max(0.32, 1 - a3 * 0.68 + a4 * 0.5);

      // portfolio: minis rise behind, hero shrinks to join the ranks
      miniMat.opacity = 0.5 * a4;
      minis.forEach((m) => {
        m.visible = a4 > 0.01;
        m.rotation.y += dt * 0.1;
        m.position.z = lerp(-6, -2.2, a4);
      });
      hero.scale.setScalar(lerp(1, 0.62, a4));

      // camera
      const orbit = a1 * 0.7 + a2 * 0.5;
      const radius = lerp(lerp(lerp(lerp(5.4, 4.6, a1), 3.4, a2), 7.4, a3), 6.2, a4);
      camera.position.x = Math.sin(orbit) * radius;
      camera.position.z = Math.cos(orbit) * radius;
      camera.position.y = lerp(0.1, 0.4, a1);
      camera.lookAt(0, 0, 0);

      renderer.render(scene, camera);
    };
    raf = requestAnimationFrame(loop);

    return () => {
      dead = true;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      ro.disconnect();
      if (renderer.domElement.parentElement === stage) stage.removeChild(renderer.domElement);
      geo.dispose();
      aluA.dispose();
      aluB.dispose();
      aluC.dispose();
      miniMat.dispose();
      envTex.dispose();
      renderer.dispose();
    };
    // refs are stable across renders; the scene is built once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div id="sourcing-stage" aria-hidden="true" style={{ position: "fixed", inset: 0, zIndex: 0 }} />;
}
