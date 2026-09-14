import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("./cad-viewer.tsx", import.meta.url), "utf8");

test("deselect clears the pinpoint projection dedupe signature before reselect", () => {
  const effect = source.match(/useEffect\(\(\) => \{\s*if \(!markerRegion\) \{([\s\S]*?)\}\s*\}, \[markerRegion, onPinpointProjection\]\);/);
  assert.ok(effect, "missing marker deselect effect");
  assert.match(effect[1], /lastProjection\.current = "";/);
  assert.match(effect[1], /onPinpointProjection\?\.\(null\);/);
  assert.ok(effect[1].indexOf('lastProjection.current = ""') < effect[1].indexOf("onPinpointProjection?.(null)"));
});
