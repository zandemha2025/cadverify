# ScaleCAD marketing website redesign — build reference

This folder is the **design reference** for rebuilding the public marketing site.
It is **not runnable code** — it's the design source so an engineer (Codex, or
anyone) can port it into the real Next.js app. The implementation on this branch is documented in `IMPLEMENTATION.md`.

**Source of truth / live design:** the Claude canvas "ScaleCAD Site Redesign"
→ https://claude.ai/artifact/3rdvLMrt1HwnnSRvVmSfRL (open it in a browser to see
the designs rendered). The files in `reference/` are exact copies of that canvas's
artboards.

## Pick: build direction **A · Precise**

The canvas has three homepage directions. **A · Precise is the chosen one** — build it.

| File | What it is | Build it? |
|---|---|---|
| `reference/Main.dc.html` | **A · Precise — homepage (desktop)** | ✅ YES — this is the direction |
| `reference/Mobile.dc.html` | A · Precise — homepage (mobile, 390px) | ✅ YES |
| `reference/Pricing.dc.html` | Pricing page | ✅ YES |
| `reference/NavStates.dc.html` | Nav — logged-out vs logged-in | ✅ YES (shared header) |
| `reference/SignupStates.dc.html` | Sign-up — email-tier states (empty / personal / work / link-sent) | ✅ YES |
| `reference/Logo.dc.html` | Logo options (the "period" question) | Pick one with the humans; "C · new mark" is the newest |
| `reference/Loud.dc.html` | B · Loud — homepage | ❌ exploration, reference only |
| `reference/Cinematic.dc.html` | C · Cinematic — homepage | ❌ exploration, reference only |
| `reference/canvas.json` | the canvas index (board titles, sizes, notes) | — map, not a page |

## How to read these files
Each `.dc.html` is a **Design-Component artboard** from the canvas editor, so it's
wrapped in `<x-dc>` / `<helmet>` / `<script src="./support.js">` / a
`<script type="text/x-dc">` block — **it will not render on its own** and is not
meant to. Read the markup *inside* it: the real structure, inline styles, copy, and
SVGs are all there and are the design spec. Reproduce them as React/Next components;
drop the `<x-dc>`, `<helmet>`, `support.js`, `data-props` and `renderVals()` wrappers.

## Design system (pulled from the artboards)
- **Colors:** ground `#F4F5F2` (cream-grey); ink `#0D0F0E` (near-black); accent
  `#FF5B1F` (orange); muted text `#474D4A` / `#5A605D` / `#636966`; hairlines
  `#DDE0DB` / `#E2E4E0`; success `#17603D` on `#E4F1E9`; caution `#5C3D00` on
  `#FBF6EC`.
- **Type (Google Fonts):** `Funnel Display` (display/headlines), `Funnel Sans`
  (body), `Martian Mono` (labels/mono). Tight display tracking (~-0.04em).
- **Shape language:** pill buttons (`border-radius:999px`), rounded cards
  (16–22px), subtle `inset 0 0 0 1px` hairlines + soft drop shadows, a cube/hex
  logo mark, mono eyebrow labels.
- **Primary CTA:** orange `#FF5B1F` pill, "Try ScaleCAD free"; secondary is a
  white/outline pill.

## Content that changes vs. today
- **Homepage headline:** "**Can you make it?**" (was "Know which of your parts you
  should be making").
- **Hero subcopy:** "Upload a 3D model of a part. ScaleCAD tells you whether your
  machines can make it, which materials will hold up, how long it takes and what it
  costs. Every number shows where it came from."
- **Sign-up tiers:** work email = 15 free checks, personal = 3; one email box, the
  number updates as you type (see `SignupStates.dc.html`).
- **Nav:** logged-out shows Product / Platform / Pricing / Security / Developers +
  "Log in" + "Try ScaleCAD free"; logged-in drops the sign-up CTA, shows checks-left
  + "Open ScaleCAD" + account menu (session read server-side, no flash).

## How to build it (for the engineer)
1. Work on this branch (`claude/site-redesign`). The target is the public/marketing
   routes in `frontend/src/app/` — landing `/`, `/teams/*`, pricing, security,
   developers, etc. Keep existing routes/SEO/content unless the design changes them.
2. Port A·Precise (`Main.dc.html` + `Mobile.dc.html`) into the homepage, the shared
   header from `NavStates.dc.html`, `Pricing.dc.html` into the pricing page, and
   `SignupStates.dc.html` behavior into the sign-up flow.
3. Reuse the shipped v4 product's design tokens where they overlap so site + app
   feel like one system; add the Funnel/Martian fonts the same way the product adds
   its fonts (local `next/font`, not a build-time Google fetch — the product already
   hit that issue).
4. **Images are placeholders.** The artboards reference canvas-hosted assets
   (`/_blob/<id>`) that won't resolve here; swap in real product renders/screenshots
   or agreed placeholders. Don't ship `/_blob/` URLs.
5. Don't invent marketing copy or claims beyond what's in the artboards — if more is
   needed, ask the humans.
6. Branch → CI green (Frontend Build & Lint, E2E) → PR → ships in a **later deploy**,
   after the product release. This does **not** block the product launch.

## Status
The artboards remain the design source. The React implementation is on this branch; see [IMPLEMENTATION.md](IMPLEMENTATION.md) for confirmed decisions, release sequencing and validation. This marketing release must follow the product release.
