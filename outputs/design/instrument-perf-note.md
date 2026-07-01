# Living Instrument — resolve-time perf/UX fix

**File touched:** `frontend/src/components/instrument/LivingInstrument.tsx`
(no change needed in `frontend/src/lib/api.ts` — `costEstimate` and `validateFile`
were already independent calls.)

**Scope:** data-flow / perceived-performance fix only. Identity, layout, the
scrubber, glass box, auth/gating, and the instrument design are all unchanged.

---

## The problem (perceived ~15s "stuck rendering")

Dropping a part fires two full engine runs on the same mesh:

- `POST /api/v1/validate/cost` — the cost decision (the hero: the monumental
  $/unit, the quantity scrubber, make-vs-buy).
- `POST /api/v1/validate` — the full DFM analysis (issue flags on the geometry).

Each is a ~5–7s engine run. Back-to-back that reads as ~15s, and during it the
"RESOLVING THE DECISION" panel just sat there — its step sequence was a pure
`setInterval(720ms)` timer with no relation to the real work, so it felt frozen.

## What changed

1. **Both calls fired in true parallel, independently.** `handleFile` now does
   `Promise.allSettled([runCost(...), runDfm(...)])`. `allSettled` never rejects,
   so a failure in one can't bubble up and blank the other. Each call still owns
   its own try/catch + error state. Backend prod runs `uvicorn --workers 2`
   (Dockerfile / fly.toml) and both endpoints are `async def`, so the cost +
   DFM pair genuinely runs across the two worker processes — the wall-clock for
   the pair drops from ~sum (≈14s) toward ~max of one run (≈7s).

2. **Progressive render — the hero no longer waits on DFM.** The cost hero
   (DecisionReadout + quantity scrubber + make-vs-buy) was already gated only on
   `costLoading` / `report`, never on the DFM result; this fix preserves and
   hardens that. The "wow" now appears the instant `/validate/cost` returns —
   the DFM flags fill into their own panel afterward when `/validate` resolves,
   showing a subtle "analyzing…" state on just that panel in the meantime.

3. **The "RESOLVING THE DECISION" sequence reflects REAL progress.**
   `ResolveSequence` is now driven by actual call resolution, not a blind timer:
   - It only renders while the cost call is in flight and is torn down the
     instant that call resolves (the hero replaces it) — so it can **never add
     time beyond the real wait**.
   - When the DFM pass resolves (it genuinely measures geometry + scores the
     candidate processes), the "Measuring geometry" and "Routing the process"
     steps check off for real (`dfmDone` signal).
   - A gentle, **capped** timer paces the active pointer for liveliness but never
     marks the final make-vs-buy fit "done" on a timer alone — that step
     completes only when the real cost result lands. Tasteful reveal, zero gating.

4. **Per-panel errors via allSettled.** A DFM failure was previously swallowed
   silently. Now it surfaces a clean inline error on the DFM panel only
   ("DFM analysis unavailable — …" + a "Retry DFM" button that re-runs just the
   geometry pass). A cost failure still shows its own card. Neither takes the
   screen down; the unaffected panel renders normally.

## Before / after structure

**Before**
```
drop → void runCost(...)        ┐ (both dispatched, but the "resolving"
       void runDfm(...)         ┘  animation marched on a fake 720ms timer)
hero gated on costLoading
DFM error → swallowed (no inline surface)
```

**After**
```
drop → Promise.allSettled([ runCost(...), runDfm(...) ])   ← explicit parallel
         ├─ /validate/cost resolves → HERO renders immediately
         │                            (number + scrubber + make-vs-buy)
         └─ /validate resolves       → DFM flags fill into their own panel
ResolveSequence: capped timer for life + REAL check-offs from dfmDone,
                 unmounts the instant cost is back (never adds time)
either call errors → clean inline error on that panel only (allSettled)
```

## Perceived behavior now

- Cost hero appears at ~one engine run (≈7s on 2 workers) instead of waiting on
  two back-to-back (~15s). The scrubber + monumental $/unit are interactive as
  soon as the cost is back.
- The DFM flags resolve into their own panel a moment later with their own
  loading/error state — they no longer hold up the decision.
- The reveal animation tracks real work and gets out of the way immediately when
  the answer is ready, killing the "stuck" feel.

## Build proof

```
npx tsc --noEmit   → TSC_EXIT=0   (clean)
npm run build      → BUILD_EXIT=0 (✓ Compiled successfully, 23 routes generated)
```

## Honest remaining lever (out of scope here)

This fix removes the **serial stacking** and the **fake-progress stall** — that's
what killed the ~15s "stuck" feeling. But each **single** engine run is still
~5–7s of CPU on the mesh. Truly-instant resolution needs a backend-engine
optimization (e.g. caching the parsed/geometry pass shared by both endpoints so
the second run reuses it, profiling the cost/DFM hot paths, or precomputing
geometry once and fanning out to cost + DFM). That per-run latency is the next
real lever and is intentionally not touched here.
