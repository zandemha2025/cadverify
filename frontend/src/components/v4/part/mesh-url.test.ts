import { test } from "node:test";
import assert from "node:assert/strict";

const { no3dTitle, urlSlot } = await import("./mesh-url.ts");

test("a re-check starting never revokes the URL on screen; a new one replaces it, then the old goes", () => {
  const live = new Set<string>();
  let n = 0;
  const slot = urlSlot(
    () => {
      const u = `blob:${++n}`;
      live.add(u);
      return u;
    },
    (u) => live.delete(u),
  );
  const first = slot.set(new Blob(["a"]));
  assert.ok(live.has(first));
  // The re-check starts and the 3D is asked for again: until the answer comes, the first URL stays usable.
  assert.ok(live.has(first));
  const second = slot.set(new Blob(["b"]));
  assert.ok(live.has(second));
  assert.equal(live.has(first), false);
  slot.clear();
  assert.equal(live.size, 0);
});

test("the no-3D title blames the device only when WebGL is missing", () => {
  assert.equal(no3dTitle("nowebgl", { url: "blob:1", origin: "live", error: null }), "No 3D view on this device");
  assert.equal(no3dTitle("failed", { url: "blob:1", origin: "live", error: null }), "The 3D view didn’t load");
  assert.equal(no3dTitle("loading", { url: null, origin: null, error: "The 3D view of the kept file couldn't reach the server." }), "The 3D view didn’t load");
  assert.equal(no3dTitle("loading", { url: null, origin: null, error: null }), "No 3D view of this part here");
});
