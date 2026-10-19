import assert from "node:assert/strict";
import test from "node:test";
import { ActivePartError, resolveActivePart, createOnshapeStepExporter } from "../src/export-step.js";
import { parseExtensionContext } from "../src/context.js";

const base = "?documentId=d&workspaceOrVersion=w&workspaceOrVersionId=w1&elementId=e";
const ctx = (extra = "") => parseExtensionContext(base + extra);

test("a selected partId in the context wins without listing parts", async () => {
  let listed = 0;
  const active = await resolveActivePart({ context: ctx("&partId=JHD"), listParts: async () => { listed += 1; return []; } });
  assert.equal(active.partId, "JHD");
  assert.equal(active.source, "selection");
  assert.equal(listed, 0);
});

test("a single visible part resolves automatically", async () => {
  const active = await resolveActivePart({
    context: ctx(),
    listParts: async () => [{ partId: "P1", name: "Bracket", isHidden: false }, { partId: "P2", name: "Old", isHidden: true }],
  });
  assert.equal(active.partId, "P1");
  assert.equal(active.name, "Bracket");
  assert.equal(active.source, "only-part");
});

test("zero visible parts is an honest error", async () => {
  await assert.rejects(
    () => resolveActivePart({ context: ctx(), listParts: async () => [{ partId: "P2", isHidden: true }] }),
    (error) => error instanceof ActivePartError && /no visible parts/.test(error.message),
  );
});

test("multiple parts asks for a selection and names the parts", async () => {
  await assert.rejects(
    () => resolveActivePart({
      context: ctx(),
      listParts: async () => [{ partId: "P1", name: "Bracket" }, { partId: "P2", name: "Housing" }],
    }),
    (error) => error instanceof ActivePartError && /2 parts/.test(error.message) && /Bracket/.test(error.message) && /Housing/.test(error.message),
  );
});

test("exporter end-to-end: resolve, export, return bytes for the controller", async () => {
  const calls = [];
  const client = {
    listParts: async () => [{ partId: "P1", name: "Bracket" }],
    exportStepForContext: async (context, { partId, destinationName }) => {
      calls.push({ partId, destinationName });
      return { bytes: new Blob(["STEP"]), filename: "bracket.step", translationId: "t1", partId };
    },
  };
  const exportStep = createOnshapeStepExporter({ client, context: ctx() });
  const result = await exportStep();
  assert.deepEqual(calls, [{ partId: "P1", destinationName: "Bracket" }]);
  assert.equal(result.filename, "bracket.step");
  assert.equal(result.source, "only-part");
  assert.equal(await result.bytes.text(), "STEP");
});
