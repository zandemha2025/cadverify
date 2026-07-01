# Living Instrument — Beauty Pass (depth · lit part · composition)

Round-N render-and-look pass. Kept the locked identity (Datum Blue, Archivo
monumental numbers, Geist Mono, dark instrument), the hierarchy (part = hero
visual, $/unit = hero number, scrubber = bottom rail, Recalibrate tucked, DFM a
calm strip), and every function (scrubber, shop dial/knobs, glass-box, DFM
face-highlight linking, override re-cost, all states, honest ±/n=0 framing).

## 1. Depth + a touch of light (killed the flat navy)

Files: `frontend/src/app/globals.css`, `LivingInstrument.tsx`.

- **Richer near-black base.** `.cv-faceplate` was one flat mid-navy
  (`#14223a→#0e1a2e`). Rebuilt to a Linear/Raycast-dark stack: near-black
  `#0f1d31 → #0b1524 → #080f1c` with a **top-edge light-catch** bezel
  (`inset 0 1px 0 rgb(255 255 255 / .09)`), an inner floor darkening, and a real
  elevation drop shadow — so the plate reads as milled metal, not a CSS card.
- **A soft Datum bloom** washes in from the upper-left of the plate (radial
  `rgb(40 106 170 / .22)`) so the surface sits in light instead of one dead tone.
- **The part sits in light.** New `.cv-viewer-well` wraps the 3D canvas with a
  Datum bezel ring that catches light + a soft **Datum halo** (`0 0 80px …
  rgb(37 104 168 / .30)`). Behind the WebGL (transparent) is a centred Datum-blue
  radial bloom over a deep twilight ground — the part floats in a pool of light.
- **Elevation tiers.** New `.cv-elev` gives the DFM strip / tucked panels a
  raised top-highlight so surfaces step apart instead of sharing one navy.

## 2. The 3D part, as a rendered product shot

File: `frontend/src/components/ui/cad-viewer.tsx`.

- **Material:** satin **machined aluminium** — `meshStandardMaterial` color
  `#bcc6d2`, `metalness 0.9`, `roughness 0.42`, `envMapIntensity 1.35`. Picks up
  the studio env as soft specular sweeps with a cool Datum rim. During DFM
  inspection the material relaxes (metalness 0.35, matte) so flagged faces stay
  unmistakable — the face-highlight linking is preserved intact.
- **Lighting:** a baked **studio rig** via drei `<Environment>` + `<Lightformer>`
  (broad soft overhead key, Datum-cool front fill, cool rim behind, a hot ring
  for a crisp catch), plus a 3-point direct rig (white key, Datum rim, underfill).
- **Contact shadow:** drei `<ContactShadows>` seats the part on an invisible
  plane (near-black, soft blur) — grounds it like a photograph. The competing
  gridHelper floor is gone on the instrument surface.
- **Hero frame:** every part is **normalised to a uniform world size**, so the
  lighting, shadow, and framing look identical for a 6 mm insert or a 600 mm
  housing. Camera is a pulled-in 3/4 with a gentle downward tilt; pan disabled so
  the composition holds. `dpr` capped at 2 and all env/shadow `frames={1}` so the
  resolve isn't tanked.

## 3. Sharpened hero composition

Files: `LivingInstrument.tsx`, `DecisionReadout.tsx`.

- Broke the tidy 7/5 split — the part now commands **8 of 12** columns and stands
  taller (`lg:h-[680px]`), reading as the clear emotional centerpiece. The
  decision column tightens to 4 as a clean vertical stack (eyebrow → "Make by X"
  → monumental $/unit → metaline → confidence → provenance/actions).
- Added a **Datum witness line** under the hero number — a short caliper-mark
  gradient rule that seats the answer on the plate and anchors the eye. Focal
  path: the lit part (whoa) → the monumental number → the scrubber rail.

## Build proof

- `npx tsc --noEmit` → exit 0.
- `npm run build` → exit 0 (Compiled successfully; 18/18 static pages).
