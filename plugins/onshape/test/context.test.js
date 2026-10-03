import assert from "node:assert/strict";
import test from "node:test";
import { ContextError, parseExtensionContext, contextFromLocation } from "../src/context.js";

const FULL = "?documentId=doc1&workspaceOrVersion=w&workspaceOrVersionId=ws1&elementId=el1&server=https%3A%2F%2Fcad.onshape.com&partId=JHD";

test("parses a full extension context and builds API paths", () => {
  const ctx = parseExtensionContext(FULL);
  assert.equal(ctx.documentId, "doc1");
  assert.equal(ctx.wvmType, "w");
  assert.equal(ctx.wvmId, "ws1");
  assert.equal(ctx.elementId, "el1");
  assert.equal(ctx.partId, "JHD");
  assert.equal(ctx.server, "https://cad.onshape.com");
  assert.equal(ctx.elementApiPath(), "/api/partstudios/d/doc1/w/ws1/e/el1");
  assert.equal(ctx.partsApiPath(), "/api/parts/d/doc1/w/ws1/e/el1");
});

test("supports version contexts", () => {
  const ctx = parseExtensionContext("?documentId=d&workspaceOrVersion=v&workspaceOrVersionId=v1&elementId=e");
  assert.equal(ctx.elementApiPath(), "/api/partstudios/d/d/v/v1/e/e");
});

test("rejects missing or invalid context with an actionable message", () => {
  assert.throws(() => parseExtensionContext("?documentId=d"), (error) => {
    assert.ok(error instanceof ContextError);
    assert.match(error.message, /workspaceOrVersionId/);
    assert.match(error.message, /elementId/);
    return true;
  });
  assert.throws(() => parseExtensionContext("?documentId=d&workspaceOrVersion=x&workspaceOrVersionId=w1&elementId=e"), ContextError);
});

test("partId is optional and empty values normalize to null", () => {
  const ctx = parseExtensionContext("?documentId=d&workspaceOrVersion=w&workspaceOrVersionId=w1&elementId=e&partId=");
  assert.equal(ctx.partId, null);
  assert.equal(ctx.apiOrigin, "https://cad.onshape.com");
});

test("contextFromLocation returns null outside a host instead of throwing", () => {
  assert.equal(contextFromLocation({ search: "" }), null);
  assert.equal(contextFromLocation({ search: "?psession=abc" }), null);
  const ctx = contextFromLocation({ search: FULL });
  assert.equal(ctx.partId, "JHD");
});
