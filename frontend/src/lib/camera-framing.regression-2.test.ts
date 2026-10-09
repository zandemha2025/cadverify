// Regression QA-006: opening Inspector cropped the normalized CAD preview.
// Found by /qa on 2026-10-08; live evidence: QA-001-live-recalled.png.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { perspectiveFramingDistance } from "./camera-framing.ts";

function projectCorners(extents: number[], aspect: number, distance: number, direction: THREE.Vector3) {
  const camera = new THREE.PerspectiveCamera(38, aspect, 0.05, 100);
  camera.position.copy(direction.clone().normalize().multiplyScalar(distance));
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld();
  const points: THREE.Vector3[] = [];
  for (const x of [-extents[0] / 2, extents[0] / 2])
    for (const y of [-extents[1] / 2, extents[1] / 2])
      for (const z of [-extents[2] / 2, extents[2] / 2])
        points.push(new THREE.Vector3(x, y, z).project(camera));
  return points;
}

test("the actual 288x340 Inspector layout contains the full 20x15x10 mm box", () => {
  const extents = [2, 1.5, 1]; // The viewer normalizes the largest dimension to 2.
  const direction = new THREE.Vector3(0.6, 0.44, 0.68);
  const oldDistance = 2 * 1.9 * direction.length();
  const aspect = 288 / 340;
  const old = projectCorners(extents, aspect, oldDistance, direction);
  assert.ok(old.some(p => Math.abs(p.x) > 1 || Math.abs(p.y) > 1), "baseline must actually crop");
  const distance = perspectiveFramingDistance(Math.hypot(...extents) / 2, aspect, 38, oldDistance);
  for (const p of projectCorners(extents, aspect, distance, direction)) {
    assert.ok(Math.abs(p.x) < 0.95 && Math.abs(p.y) < 0.95, `corner outside the padded frame: ${p.toArray()}`);
    assert.ok(p.z > -1 && p.z < 1, "corner inside near/far clipping planes");
  }
});

test("wide, flat, slender and cubic parts fit at phone/tablet widths after orbiting", () => {
  const extentsList = [[2, 1.5, 1], [2, 0.02, 1], [0.02, 2, 0.02], [2, 2, 2]];
  for (const extents of extentsList) {
    for (const width of [180, 288, 340, 342, 437, 1280]) {
      const aspect = width / 340;
      const distance = perspectiveFramingDistance(Math.hypot(...extents) / 2, aspect, 38, 3.83);
      for (const yaw of [0, 0.67, 1.57, 2.41, 3.9, 5.4]) {
        for (const pitch of [-1.2, -0.3, 0.5, 1.2]) {
          const direction = new THREE.Vector3(Math.cos(yaw) * Math.cos(pitch), Math.sin(pitch), Math.sin(yaw) * Math.cos(pitch));
          for (const p of projectCorners(extents, aspect, distance, direction)) {
            assert.ok(Math.abs(p.x) < 0.95 && Math.abs(p.y) < 0.95,
              `cropped ${extents} at ${width}px, yaw ${yaw}, pitch ${pitch}`);
            assert.ok(p.z > -1 && p.z < 1);
          }
        }
      }
    }
  }
});
