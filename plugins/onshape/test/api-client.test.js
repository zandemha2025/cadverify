import assert from "node:assert/strict";
import test from "node:test";
import { OnshapeApiClient, OnshapeApiError } from "../src/api-client.js";
import { parseExtensionContext } from "../src/context.js";

const ctx = parseExtensionContext("?documentId=doc1&workspaceOrVersion=w&workspaceOrVersionId=ws1&elementId=el1");
const json = (body, status = 200, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
const noSleep = async () => {};

function recorder(responses) {
  const calls = [];
  return {
    calls,
    fetch: async (url, init) => {
      calls.push({ url, init });
      const next = typeof responses[0] === "function" ? responses.shift()(url, init) : responses.shift();
      if (!next) throw new Error(`unexpected fetch: ${url}`);
      return next;
    },
  };
}

test("lists parts with bearer auth on the element path", async () => {
  const rec = recorder([json([{ partId: "JHD", name: "Bracket", isHidden: false }])]);
  const client = new OnshapeApiClient({ accessToken: "tok", fetchImpl: rec.fetch, sleep: noSleep });
  const parts = await client.listParts(ctx);
  assert.equal(rec.calls[0].url, "https://cad.onshape.com/api/parts/d/doc1/w/ws1/e/el1");
  assert.equal(rec.calls[0].init.headers.Authorization, "Bearer tok");
  assert.equal(parts[0].partId, "JHD");
});

test("part STEP export posts formatName STEP, partIds and storeInDocument=false", async () => {
  const rec = recorder([json({ id: "t1", requestState: "ACTIVE" })]);
  const client = new OnshapeApiClient({ accessToken: "tok", fetchImpl: rec.fetch, sleep: noSleep });
  await client.exportPartStep(ctx, "JHD", { destinationName: "Bracket" });
  assert.equal(rec.calls[0].url, "https://cad.onshape.com/api/partstudios/d/doc1/w/ws1/e/el1/translations");
  const body = JSON.parse(rec.calls[0].init.body);
  assert.equal(body.formatName, "STEP");
  assert.equal(body.partIds, "JHD");
  assert.equal(body.storeInDocument, false);
  assert.equal(body.notifyUser, false);
  assert.equal(rec.calls[0].init.headers["Content-Type"], "application/json;charset=UTF-8; qs=0.09");
});

test("studio STEP export uses the dedicated export/step endpoint", async () => {
  const rec = recorder([json({ id: "t2", requestState: "ACTIVE" })]);
  const client = new OnshapeApiClient({ accessToken: "tok", fetchImpl: rec.fetch, sleep: noSleep });
  await client.exportStudioStep(ctx);
  assert.equal(rec.calls[0].url, "https://cad.onshape.com/api/partstudios/d/doc1/w/ws1/e/el1/export/step");
  const body = JSON.parse(rec.calls[0].init.body);
  assert.equal(body.storeInDocument, false);
  assert.equal(body.excludeHiddenEntities, true);
});

test("full flow: export, poll to DONE, download external data", async () => {
  const rec = recorder([
    json({ id: "t1", requestState: "ACTIVE" }),
    json({ id: "t1", requestState: "ACTIVE" }),
    json({ id: "t1", requestState: "DONE", resultExternalDataIds: ["fid1"] }),
    new Response(new Blob(["ISO-10303-21; STEP DATA"]), {
      status: 200,
      headers: { "content-disposition": 'attachment; filename="bracket.step"' },
    }),
  ]);
  const client = new OnshapeApiClient({ accessToken: "tok", fetchImpl: rec.fetch, sleep: noSleep, pollIntervalMs: 0 });
  const result = await client.exportStepForContext(ctx, { partId: "JHD", destinationName: "Bracket" });
  assert.equal(rec.calls[1].url, "https://cad.onshape.com/api/translations/t1");
  assert.equal(rec.calls[3].url, "https://cad.onshape.com/api/documents/d/doc1/externaldata/fid1");
  assert.equal(result.filename, "bracket.step");
  assert.equal(result.translationId, "t1");
  assert.equal(result.partId, "JHD");
  assert.match(await result.bytes.text(), /STEP DATA/);
});

test("failed translation throws with the failure reason", async () => {
  const rec = recorder([json({ id: "t9", requestState: "FAILED", failureReason: "geometry kernel rejected part" })]);
  const client = new OnshapeApiClient({ accessToken: "tok", fetchImpl: rec.fetch, sleep: noSleep, pollIntervalMs: 0 });
  await assert.rejects(
    () => client.pollTranslation("t9"),
    (error) => error instanceof OnshapeApiError && /geometry kernel rejected part/.test(error.message) && error.translationId === "t9",
  );
});

test("polling that never terminates times out honestly", async () => {
  const rec = recorder([( ) => json({ id: "t5", requestState: "ACTIVE" })]);
  const client = new OnshapeApiClient({ accessToken: "tok", fetchImpl: rec.fetch, sleep: noSleep, pollIntervalMs: 0, maxPollMs: 0 });
  await assert.rejects(() => client.pollTranslation("t5"), /did not finish/);
});

test("a 401 refreshes once through onUnauthorized and retries with the new token", async () => {
  const rec = recorder([
    json({ message: "expired" }, 401),
    json([{ partId: "JHD", name: "Bracket" }]),
  ]);
  let refreshed = 0;
  const client = new OnshapeApiClient({
    accessToken: "old",
    fetchImpl: rec.fetch,
    sleep: noSleep,
    onUnauthorized: async () => { refreshed += 1; return "new-token"; },
  });
  const parts = await client.listParts(ctx);
  assert.equal(refreshed, 1);
  assert.equal(rec.calls[1].init.headers.Authorization, "Bearer new-token");
  assert.equal(parts[0].partId, "JHD");
});

test("downloads follow 307 redirects and re-attach the Authorization header", async () => {
  const rec = recorder([
    new Response(null, { status: 307, headers: { location: "https://cad.onshape.com/api/documents/d/doc1/externaldata/fid1?sig=abc" } }),
    new Response(new Blob(["STEP"]), { status: 200 }),
  ]);
  const client = new OnshapeApiClient({ accessToken: "tok", fetchImpl: rec.fetch, sleep: noSleep });
  const { blob } = await client.downloadExternalData("doc1", "fid1");
  assert.equal(rec.calls[1].url, "https://cad.onshape.com/api/documents/d/doc1/externaldata/fid1?sig=abc");
  assert.equal(rec.calls[1].init.headers.Authorization, "Bearer tok");
  assert.equal(await blob.text(), "STEP");
});

test("API errors include status and server message", async () => {
  const rec = recorder([json({ message: "element not found" }, 404)]);
  const client = new OnshapeApiClient({ accessToken: "tok", fetchImpl: rec.fetch, sleep: noSleep });
  await assert.rejects(
    () => client.listParts(ctx),
    (error) => error instanceof OnshapeApiError && error.status === 404 && /element not found/.test(error.message),
  );
});
