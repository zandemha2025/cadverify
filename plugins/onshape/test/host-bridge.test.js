import assert from "node:assert/strict";
import test from "node:test";
import { buildKeepAliveMessage, createHostBridge } from "../src/host-bridge.js";
import { parseExtensionContext } from "../src/context.js";

const ctx = parseExtensionContext("?documentId=d1&workspaceOrVersion=w&workspaceOrVersionId=w1&elementId=e1&server=https%3A%2F%2Fcad.onshape.com");

test("keepAlive carries document, workspace and element ids", () => {
  assert.deepEqual(buildKeepAliveMessage(ctx), {
    messageName: "keepAlive",
    documentId: "d1",
    workspaceId: "w1",
    elementId: "e1",
  });
});

test("announceReady posts keepAlive to the host origin", () => {
  const posts = [];
  const bridge = createHostBridge({ context: ctx, target: { postMessage: (msg, origin) => posts.push({ msg, origin }) } });
  bridge.announceReady();
  assert.equal(posts.length, 1);
  assert.equal(posts[0].origin, "https://cad.onshape.com");
  assert.equal(posts[0].msg.messageName, "keepAlive");
});

test("only messages from the host server origin are trusted", () => {
  const bridge = createHostBridge({ context: ctx, target: { postMessage: () => {} } });
  assert.equal(bridge.isTrustedMessage({ origin: "https://cad.onshape.com" }), true);
  assert.equal(bridge.isTrustedMessage({ origin: "https://evil.example" }), false);
  assert.equal(bridge.isTrustedMessage({}), false);
});
