/**
 * Canonical LIGHT-INSTRUMENT tokens for the product Verify surface.
 *
 * DESIGN-DECISIONS.md is binding: the product register is a light editorial
 * instrument (#f6f6f7 bg / #ffffff panels / #e2e2e6 hairlines / #17181a ink,
 * 16px-radius cards, ui-monospace evidence). The authed app is otherwise
 * DARK-FIRST (globals.css toggles `.dark` on <html>), so this surface uses
 * EXPLICIT hex — never the Tailwind semantic tokens — to stay independent of the
 * theme and keep flag-off byte-identical.
 *
 * Provenance/status colours are the canonical light pairs from DESIGN-DECISIONS.
 * Hours are ○ MODEL (computed from assumptions), never MEASURED.
 */

export const C = {
  bg: "#f6f6f7",
  panel: "#ffffff",
  hair: "#e2e2e6",
  hair2: "#e7e7ea",
  ink: "#17181a",
  // Muted-ink ramp — re-based into the WCAG-AA zone. Every rung is real body/
  // caption text on the #f6f6f7 / #ffffff instrument surfaces, so the lightest
  // rung sits at the 4.5:1 AA floor and the scale climbs from there while
  // staying a visibly ordered light→dark ramp. (Old alphas 0.35–0.60 were
  // 2.2–4.5:1 — sub-AA for <18px text.) Contrast (min over both surfaces):
  //   ink35 4.53  ink40 4.84  ink45 5.17  ink50 5.52  ink55 5.91  ink60 6.33  ink70 6.78
  ink70: "rgba(23,24,26,0.72)",
  ink60: "rgba(23,24,26,0.7)",
  ink55: "rgba(23,24,26,0.68)",
  ink50: "rgba(23,24,26,0.66)",
  ink45: "rgba(23,24,26,0.64)",
  ink40: "rgba(23,24,26,0.62)",
  ink35: "rgba(23,24,26,0.6)",
  sunken: "#f6f6f7",

  // provenance (light) — re-based into the WCAG-AA zone for small (<18px) mono
  // labels. Each hue is preserved but darkened until it clears 4.5:1 on BOTH the
  // #f6f6f7 and #ffffff surfaces (worst case #f6f6f7). Old values were 3.5–4.4:1.
  measured: "#3772ab", // 4.68:1
  shop: "#a06030", // 4.62:1
  user: "#745cc7", // 4.74:1
  def: "#69707d", // 4.61:1 · DEFAULT + MODEL share slate; MODEL renders "○ MODEL"

  // status
  pass: "#1d7f54", // 4.61:1
  cond: "#966614", // 4.62:1 (amber "issues" label — was 3.79:1, sub-AA)
  fail: "#c2453a", // 4.62:1 (already AA)
} as const;

export const MONO =
  "ui-monospace, 'SF Mono', 'SFMono-Regular', Menlo, monospace";
export const SANS =
  "'Helvetica Neue', -apple-system, BlinkMacSystemFont, system-ui, sans-serif";

export type Prov = "MEASURED" | "SHOP" | "USER" | "DEFAULT" | "MODEL";

export interface ProvMeta {
  label: string;
  color: string;
  /** filled dot = grounded; hollow ring = a generic guess (DEFAULT/MODEL). */
  filled: boolean;
  glyph: string; // "●" grounded, "○" hollow
  description: string;
}

const SLATE_DESC = "Generic fallback — no calibrated value yet.";

export const PROV: Record<Prov, ProvMeta> = {
  MEASURED: {
    label: "MEASURED",
    color: C.measured,
    filled: true,
    glyph: "●",
    description: "Measured directly from your CAD geometry.",
  },
  SHOP: {
    label: "SHOP",
    color: C.shop,
    filled: true,
    glyph: "●",
    description: "Your shop's calibrated rate — bound to your real numbers.",
  },
  USER: {
    label: "USER",
    color: C.user,
    filled: true,
    glyph: "●",
    description: "Declared by your team.",
  },
  DEFAULT: {
    label: "DEFAULT",
    color: C.def,
    filled: false,
    glyph: "○",
    description: SLATE_DESC,
  },
  MODEL: {
    label: "MODEL",
    color: C.def,
    filled: false,
    glyph: "○",
    description: "Computed from a DEFAULT assumption — not a measurement.",
  },
};

/** Normalise the engine's provenance strings (upper/lowercase) to a Prov key. */
export function normProv(p: string | null | undefined): Prov {
  const u = String(p ?? "").toUpperCase();
  if (u === "MEASURED" || u === "SHOP" || u === "USER" || u === "MODEL")
    return u as Prov;
  return "DEFAULT";
}

/** verdict/severity → light status colour. */
export function statusColor(v: string): string {
  switch (v) {
    case "pass":
      return C.pass;
    case "issues":
    case "warning":
    case "warn":
      return C.cond;
    case "fail":
    case "error":
      return C.fail;
    default:
      return C.def;
  }
}

export const PROCESS_LABELS: Record<string, string> = {
  fdm: "FDM / FFF",
  sla: "SLA Resin",
  dlp: "DLP Resin",
  sls: "SLS (Powder)",
  mjf: "MJF (HP)",
  dmls: "DMLS (Metal)",
  slm: "SLM (Metal)",
  ebm: "EBM (Metal)",
  binder_jetting: "Binder Jetting",
  ded: "DED",
  waam: "WAAM",
  cnc_3axis: "CNC 3-Axis",
  cnc_5axis: "CNC 5-Axis",
  cnc_turning: "CNC Turning",
  wire_edm: "Wire EDM",
  injection_molding: "Injection Molding",
  die_casting: "Die Casting",
  investment_casting: "Investment Casting",
  sand_casting: "Sand Casting",
  sheet_metal: "Sheet Metal",
  forging: "Forging",
};

export function procLabel(p: string | null | undefined): string {
  if (!p) return "—";
  return PROCESS_LABELS[p] ?? p;
}

export const USD = (n: number | null | undefined, dp?: number): string => {
  if (n == null || !Number.isFinite(n)) return "—";
  const d = dp ?? (n < 100 ? 2 : n < 1000 ? 1 : 0);
  return `$${n.toLocaleString("en-US", {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  })}`;
};

export const NUM = (n: number | null | undefined): string => {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toLocaleString("en-US");
};
