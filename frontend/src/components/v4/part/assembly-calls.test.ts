import test from "node:test";
import assert from "node:assert/strict";

import { assemblyAnalysis, assemblyGlb, type PostAssembly } from "./assembly-calls.ts";
import { assemblyViews, busyMeta, busyTitle, serverMeta, stillBusyMeta } from "./busy-state.ts";
import { BUSY_BOUND_MS, type BusyWait } from "../../../lib/verify/busy.ts";

const busy = (after = "5") => Response.json({ detail: { code: "server_busy", message: "server is at capacity, retry shortly" } }, { status: 429, headers: { "retry-after": after } });

/** A fake clock: sleeping moves it. */
function clock() {
  let t = 2_000_000;
  const slept: number[] = [];
  return { now: () => t, sleep: async (ms: number) => { slept.push(ms); t += ms; }, slept };
}

/** Answers in order, recording each format asked for. */
function server(answers: (() => Response | null)[]) {
  const asked: string[] = [];
  const post: PostAssembly = async (format) => {
    asked.push(format);
    const next = answers.shift();
    return next ? next() : null;
  };
  return { post, asked };
}

test("the assembly's 3D view is asked again on 429 busy, after Retry-After, and counted down", async () => {
  const c = clock();
  const s = server([() => busy("7"), () => busy("3"), () => new Response(new Blob([new Uint8Array([1, 2, 3])]), { status: 200 })]);
  const waits: (BusyWait | null)[] = [];
  const out = await assemblyGlb(s.post, { now: c.now, sleep: c.sleep, random: () => 0, onWait: (w) => waits.push(w) }, () => "blob:glb");
  assert.deepEqual(s.asked, ["glb", "glb", "glb"]);
  assert.deepEqual(c.slept, [7000, 3000]);
  assert.equal(out.glbUrl, "blob:glb");
  assert.equal(out.stillBusy, null);
  assert.equal(waits.length, 3);
  assert.equal(waits[0]!.until - waits[0]!.since, 7000);
  assert.equal(waits.at(-1), null);
});

test("the assembly analysis is asked again on 429 busy, after Retry-After, then answers", async () => {
  const c = clock();
  const analysis = { per_part: [], interference: { pairs: [] } };
  const s = server([() => busy("5"), () => Response.json({ analysis })]);
  const out = await assemblyAnalysis(s.post, { now: c.now, sleep: c.sleep, random: () => 0 });
  assert.deepEqual(s.asked, ["analysis", "analysis"]);
  assert.deepEqual(c.slept, [5000]);
  assert.deepEqual(out.analysis, analysis);
  assert.equal(out.error, null);
  assert.equal(out.stillBusy, null);
});

test("both stop asking at the same bound as a part's calls, and say still busy", async () => {
  for (const call of ["glb", "analysis"] as const) {
    const c = clock();
    let n = 0;
    const post: PostAssembly = async () => {
      n += 1;
      return busy("5");
    };
    const out = call === "glb" ? await assemblyGlb(post, { now: c.now, sleep: c.sleep, random: () => 0 }) : await assemblyAnalysis(post, { now: c.now, sleep: c.sleep, random: () => 0 });
    assert.equal(n, 15, call);
    assert.ok(c.slept.reduce((x, y) => x + y, 0) <= BUSY_BOUND_MS, call);
    assert.equal(out.stillBusy?.kind, "server", call);
    assert.ok((out.stillBusy?.waitedMs ?? 0) > 160_000, call);
  }
});

test("a gateway timeout or no answer is ScaleCAD's side, asked once; the paid gate and real refusals keep their meaning", async () => {
  const c = clock();
  const o = { now: c.now, sleep: c.sleep, random: () => 0 };
  const g504 = server([() => new Response("Gateway Timeout", { status: 504 })]);
  assert.deepEqual(await assemblyGlb(g504.post, o), { glbUrl: null, gate: null, glbError: null, server: 504, stillBusy: null });
  assert.equal(g504.asked.length, 1);
  assert.equal((await assemblyGlb(server([() => null]).post, o)).server, 0);
  const a502 = await assemblyAnalysis(server([() => new Response("Bad Gateway", { status: 502 })]).post, o);
  assert.equal(a502.status, 502);
  assert.equal(a502.stillBusy, null);
  // The pilot tool's gate: a gate, not an error.
  const paid = () => Response.json({ detail: { code: "paid_access_required", message: "pilot" } }, { status: 403 });
  assert.equal((await assemblyGlb(server([paid]).post, o)).gate, "pilot");
  assert.equal((await assemblyAnalysis(server([paid]).post, o)).gate, "pilot");
  // A refusal of the file keeps the server's words.
  const refused = await assemblyGlb(server([() => Response.json({ detail: "No solid bodies" }, { status: 422 })]).post, o);
  assert.equal(refused.glbError, "No solid bodies");
  assert.equal(refused.server, null);
  assert.deepEqual(c.slept, []);
});

test("the assembly page shows these as the same busy state: countdown, still busy, or ScaleCAD's side", () => {
  const w: BusyWait = { kind: "server", attempt: 1, since: 0, until: 8000 };
  const waiting = assemblyViews({ assembly: w, assembly3d: w }, { analyzing: true });
  assert.equal(waiting.sheet?.phase, "waiting");
  assert.equal(waiting.stage?.phase, "waiting");
  assert.equal(busyTitle({ step: "assembly", wait: w }, 0), "ScaleCAD is busy. Checking again in 8 s…");
  assert.equal(busyTitle({ step: "assembly3d", wait: w }, 0), "The 3D view is waiting for room. Trying again in 8 s…");
  assert.match(busyMeta({ step: "assembly", wait: w }), /The product tree is ready; the per-part analysis starts once there's room/);
  const still = assemblyViews({}, { analysisBusy: { kind: "server", waitedMs: 170_000 }, glbBusy: { kind: "server", waitedMs: 171_000 } });
  assert.deepEqual(still.sheet, { phase: "still", still: { step: "assembly", kind: "server", waitedMs: 170_000 } });
  assert.equal(still.stage?.phase, "still");
  assert.match(stillBusyMeta({ step: "assembly", kind: "server", waitedMs: 170_000 }), /per-part analysis hasn't run/);
  const stopped = assemblyViews({}, { analysisError: "Gateway Timeout", analysisStatus: 504, glbServer: 502 });
  assert.deepEqual(stopped.sheet, { phase: "server", step: "assembly", status: 504 });
  assert.deepEqual(stopped.stage, { phase: "server", step: "assembly3d", status: 502 });
  assert.match(serverMeta("assembly", 504), /^ScaleCAD stopped before answering \(504\)\. The product tree is ready/);
  // A 4xx analysis error keeps the page's own note; a drawn 3D view or a finished analysis is no wait.
  assert.equal(assemblyViews({}, { analysisError: "No solid bodies", analysisStatus: 422 }).sheet, null);
  assert.equal(assemblyViews({}, { glbUrl: "blob:x", glbServer: 504 }).stage, null);
  assert.equal(assemblyViews({}, { analysis: { ok: 1 }, analysisBusy: { kind: "server", waitedMs: 1 } }).sheet, null);
});
