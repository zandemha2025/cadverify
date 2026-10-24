import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// The public share proxy runs on the frontend server, so without the signed
// client IP the API's per-IP share limit would count every visitor as that one
// server. It signs the visitor's IP for the exact path it calls, like the auth
// proxies do.
const source = await readFile(new URL("../app/api/public-share/[...path]/route.ts", import.meta.url), "utf8");

test("the public share proxy forwards the signed client IP", () => {
  assert.match(source, /import \{ signedAuthProxyHeaders \} from "@\/lib\/auth-proxy";/);
  assert.match(source, /const backendPath = `\/\$\{path\.join\("\/"\)\}`;/);
  assert.match(source, /fetch\(backendUrl\(backendPath\), \{[\s\S]*headers: signedAuthProxyHeaders\(request, backendPath\)/);
});

test("the request is still a cache-less GET that never follows redirects", () => {
  assert.match(source, /cache: "no-store"/);
  assert.match(source, /redirect: "error"/);
  assert.doesNotMatch(source, /method:\s*"(?!GET)/);
});
