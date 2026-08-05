/**
 * WCAG-AA contrast guard for the Verify muted-ink ramp.
 *
 * The product Verify surface is a fixed LIGHT instrument (bg #f6f6f7 / panels
 * #ffffff), so every `C.inkNN` token is dark type composited over one of those
 * two surfaces. Personas repeatedly flagged the faint captions/hints (ink40 /
 * ink45 and below) as sub-AA. This test re-derives each token's real contrast
 * ratio from the same rgba() string the app renders and asserts it clears the
 * WCAG 1.4.3 AA floor for normal (<18px) text — 4.5:1 — against BOTH surfaces.
 *
 * Pure math: sRGB → relative luminance → alpha composite → contrast ratio.
 * No DOM. If someone lightens a token back below AA this test fails loudly.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { C } from "./tokens.ts";

type RGB = { r: number; g: number; b: number };

const BG: RGB = { r: 246, g: 246, b: 247 }; // #f6f6f7 page
const PANEL: RGB = { r: 255, g: 255, b: 255 }; // #ffffff cards

function chan(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

function luminance({ r, g, b }: RGB): number {
  return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b);
}

function composite(fg: RGB, alpha: number, bg: RGB): RGB {
  return {
    r: fg.r * alpha + bg.r * (1 - alpha),
    g: fg.g * alpha + bg.g * (1 - alpha),
    b: fg.b * alpha + bg.b * (1 - alpha),
  };
}

function ratio(a: RGB, b: RGB): number {
  const l1 = luminance(a);
  const l2 = luminance(b);
  const hi = Math.max(l1, l2);
  const lo = Math.min(l1, l2);
  return (hi + 0.05) / (lo + 0.05);
}

/** Parse `rgba(r,g,b,a)` (the exact form the tokens use) into {rgb, alpha}. */
function parseRgba(value: string): { rgb: RGB; alpha: number } {
  const m = value.match(
    /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)/,
  );
  assert.ok(m, `not an rgba() token: ${value}`);
  return {
    rgb: { r: Number(m![1]), g: Number(m![2]), b: Number(m![3]) },
    alpha: m![4] === undefined ? 1 : Number(m![4]),
  };
}

/** Effective contrast of a translucent ink token on the worse of the two surfaces. */
function tokenContrast(token: string): number {
  const { rgb, alpha } = parseRgba(token);
  const onBg = ratio(composite(rgb, alpha, BG), BG);
  const onPanel = ratio(composite(rgb, alpha, PANEL), PANEL);
  return Math.min(onBg, onPanel);
}

/** Parse `#rrggbb` into RGB. */
function parseHex(value: string): RGB {
  const m = value.match(/^#([0-9a-fA-F]{6})$/);
  assert.ok(m, `not a #rrggbb token: ${value}`);
  const n = parseInt(m![1], 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

/** Effective contrast of an opaque hex token on the worse of the two surfaces. */
function hexContrast(token: string): number {
  const rgb = parseHex(token);
  return Math.min(ratio(rgb, BG), ratio(rgb, PANEL));
}

const AA_NORMAL = 4.5;

// Every muted-ink rung carries real caption/label/hint copy somewhere in the
// Verify surface, so each must clear AA for normal text on both surfaces.
const MUTED_TEXT_TOKENS: Array<[string, string]> = [
  ["ink35", C.ink35],
  ["ink40", C.ink40],
  ["ink45", C.ink45],
  ["ink50", C.ink50],
  ["ink55", C.ink55],
  ["ink60", C.ink60],
  ["ink70", C.ink70],
];

for (const [name, token] of MUTED_TEXT_TOKENS) {
  test(`C.${name} meets WCAG AA (4.5:1) on both instrument surfaces`, () => {
    const r = tokenContrast(token);
    assert.ok(
      r >= AA_NORMAL,
      `C.${name} contrast ${r.toFixed(2)}:1 is below AA ${AA_NORMAL}:1`,
    );
  });
}

// Provenance + status accents render as small (<18px) mono labels — the
// "● MEASURED" chip, the amber "N issues" count, the "ROUTE PICK" pill's kin.
// A human-sim persona measured the old amber (#b07818, 3.79:1) and blue
// (#3b7bb8, 4.13:1) as sub-AA. Each opaque accent must clear AA on both
// surfaces; if someone lightens one back below AA this fails loudly.
const STATUS_TEXT_TOKENS: Array<[string, string]> = [
  ["measured", C.measured],
  ["shop", C.shop],
  ["user", C.user],
  ["def", C.def],
  ["pass", C.pass],
  ["cond", C.cond],
  ["fail", C.fail],
];

for (const [name, token] of STATUS_TEXT_TOKENS) {
  test(`C.${name} accent meets WCAG AA (4.5:1) on both instrument surfaces`, () => {
    const r = hexContrast(token);
    assert.ok(
      r >= AA_NORMAL,
      `C.${name} accent contrast ${r.toFixed(2)}:1 is below AA ${AA_NORMAL}:1`,
    );
  });
}

test("muted-ink ramp stays monotonically ordered light→dark", () => {
  const ratios = MUTED_TEXT_TOKENS.map(([, t]) => tokenContrast(t));
  for (let i = 1; i < ratios.length; i++) {
    assert.ok(
      ratios[i] > ratios[i - 1],
      `ramp not increasing at index ${i}: ${ratios[i - 1].toFixed(2)} -> ${ratios[i].toFixed(2)}`,
    );
  }
});
